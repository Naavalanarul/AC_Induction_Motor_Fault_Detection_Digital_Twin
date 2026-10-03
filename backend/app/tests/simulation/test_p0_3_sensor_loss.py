"""backend/app/tests/simulation/test_p0_3_sensor_loss.py

Regression test suite for P0-3:
- Channel criticality and MHI never increasing upon channel starvation.
- SADA watchdog timer triggering TRIP_SENSOR_LOSS within grace period.
- Smoothed severity decay when UNKNOWN while sensors are healthy.
- Clearing fault while sensors are stale entering defined watchdog outcome.
- MotorWorker full loop verification.
"""

from __future__ import annotations

import asyncio

from app.diagnostics.health_index import CHANNEL_CRITICALITY, compute_mhi
from app.diagnostics.schema import DiagFault, DiagSource, FusedDiagnosis
from app.sensors.base import SensorMode, SensorStatus, SensorType
from app.supervisory.sada import SadaConfig, SadaState, SadaSupervisor
from app.tests._harness import make, run


def make_diag(fault=DiagFault.HEALTHY, conf=0.9, sev=0.0):
    per = {DiagSource.THERMAL.value: {"details": {"critical": False}}}
    return FusedDiagnosis(0.0, fault, conf, sev, per)


def test_mhi_never_increases_when_channels_lost():
    """MHI must strictly decrease or stay constant when sensor channels are degraded or lost."""
    d_healthy = make_diag(DiagFault.HEALTHY, sev=0.0)
    all_ok = {st.value: SensorStatus.OK for st in SensorType}

    mhi_baseline, zone = compute_mhi(d_healthy, SadaState.NORMAL, all_ok)
    assert mhi_baseline == 100.0
    assert zone == "A"

    # Acoustic missing (least critical: 4.0 penalty)
    one_stale = dict(all_ok)
    one_stale["acoustic"] = SensorStatus.STALE
    mhi_one, _ = compute_mhi(d_healthy, SadaState.NORMAL, one_stale)
    assert mhi_one == 100.0 - CHANNEL_CRITICALITY["acoustic"]
    assert mhi_one < mhi_baseline

    # Current missing (critical: 12.0 penalty)
    current_stale = dict(all_ok)
    current_stale["current"] = SensorStatus.STALE
    mhi_cur, _ = compute_mhi(d_healthy, SadaState.NORMAL, current_stale)
    assert mhi_cur == 100.0 - CHANNEL_CRITICALITY["current"]
    assert mhi_cur < mhi_baseline

    # All 6 channels stale
    all_stale = {st.value: SensorStatus.STALE for st in SensorType}
    mhi_all_stale, _ = compute_mhi(d_healthy, SadaState.NORMAL, all_stale)
    assert mhi_all_stale <= 50.0

    # Fault active at DERATE: MHI before sensor loss
    d_fault = make_diag(DiagFault.BEARING_OUTER, sev=0.64)
    mhi_fault_ok, _ = compute_mhi(d_fault, SadaState.DERATE, all_ok, latched_severity=0.64)

    # Sensors now lost (fused diagnosis drops to UNKNOWN with sev 0.0)
    d_unknown = make_diag(DiagFault.UNKNOWN, sev=0.0)
    mhi_fault_lost, _ = compute_mhi(d_unknown, SadaState.DERATE, all_stale, latched_severity=0.64)

    # MHI must NOT increase!
    assert mhi_fault_lost <= mhi_fault_ok
    assert mhi_fault_lost == 0.0


def test_sada_watchdog_trips_on_critical_sensor_loss():
    """If critical sensors remain lost past grace period (3.0s), SADA must trip with TRIP_SENSOR_LOSS."""
    cfg = SadaConfig(sensor_loss_grace_s=3.0, sensor_loss_action="trip")
    s = SadaSupervisor(cfg)
    d = make_diag(DiagFault.HEALTHY)

    # 2.8 seconds of sensor loss (28 ticks at dt=0.1) -> should NOT trip yet
    for _ in range(28):
        out = s.update(d, dt=0.1, critical_sensors_ok=False)
        assert not out.trip

    # 3.0 seconds reached -> watchdog engages
    out = s.update(d, dt=0.2, critical_sensors_ok=False)
    assert out.trip
    assert out.reason_code == "TRIP_SENSOR_LOSS"
    assert out.state == SadaState.TRIP

    # Reset refused while sensors are still lost
    assert s.reset() is False


def test_sada_decay_when_unknown_and_sensors_healthy():
    """When fault is cleared/UNKNOWN and sensors are healthy, smoothed severity must decay slowly to NORMAL."""
    s = SadaSupervisor()
    # Drive into DERATE
    d_fault = make_diag(DiagFault.BEARING_OUTER, sev=0.65)
    for _ in range(100):
        s.update(d_fault, dt=0.1, critical_sensors_ok=True)
    assert s.state == SadaState.DERATE

    # Now fault is cleared to UNKNOWN, sensors are healthy
    d_unknown = make_diag(DiagFault.UNKNOWN, sev=0.0)
    for _ in range(100):
        out = s.update(d_unknown, dt=0.1, critical_sensors_ok=True)

    # Must decay out of DERATE
    assert out.state in (SadaState.WATCH, SadaState.NORMAL)
    for _ in range(100):
        out = s.update(d_unknown, dt=0.1, critical_sensors_ok=True)
    assert out.state == SadaState.NORMAL
    assert out.reason_code == "OK"


def test_clearing_fault_while_sensors_stale_triggers_defined_watchdog_outcome():
    """Clearing fault while sensors are stale does not leave an unexplained DERATE; watchdog engages."""
    s = SadaSupervisor(SadaConfig(sensor_loss_grace_s=1.0))
    d_fault = make_diag(DiagFault.BEARING_OUTER, sev=0.65)
    for _ in range(50):
        s.update(d_fault, dt=0.1, critical_sensors_ok=True)
    assert s.state == SadaState.DERATE

    # Clear fault to UNKNOWN while sensors are STALE
    d_unknown = make_diag(DiagFault.UNKNOWN, sev=0.0)
    for _ in range(15):  # 1.5 s > 1.0 s grace
        out = s.update(d_unknown, dt=0.1, critical_sensors_ok=False)

    assert out.state == SadaState.TRIP
    assert out.reason_code == "TRIP_SENSOR_LOSS"


def test_worker_stale_sensor_full_integration():
    """Worker tick integration: switching sensors to hardware triggers stale status, watchdog trip, and no MHI rise."""
    w = make(load=8.0)

    # Warm up worker
    async def run_scenario():
        await run(w, 1.0)
        out_nominal = await w.tick()
        mhi_nominal = out_nominal["health_index"]
        assert mhi_nominal >= 85.0

        # Flip all sensors to hardware (placeholders report STALE)
        for st in SensorType:
            w.registry.set_mode(st, SensorMode.HARDWARE)

        # Run past the 3.0s watchdog grace period
        out_after = await run(w, 4.0)

        # MHI must not have increased
        assert out_after["health_index"] <= mhi_nominal

        # SADA must have tripped with TRIP_SENSOR_LOSS
        assert out_after["supervisory"]["trip"] is True
        assert out_after["supervisory"]["reason_code"] == "TRIP_SENSOR_LOSS"

    asyncio.run(run_scenario())
