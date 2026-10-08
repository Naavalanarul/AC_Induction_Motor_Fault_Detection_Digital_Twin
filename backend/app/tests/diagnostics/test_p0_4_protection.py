"""backend/app/tests/diagnostics/test_p0_4_protection.py

Regression test suite for P0-4:
- Current-based protection channel (IEEE C37.96 / IEC 60255).
- I^2 t inverse-time thermal overload curve vs rated_current (2x and 2.5x load).
- Instantaneous overcurrent protection (immediate trip).
- Locked-rotor / stall protection (rapid trip upon speed collapse under current).
- Single-phasing / phase-loss protection (current unbalance).
- Voltage sag fault reachability and recommendation catalog completeness.
"""

from __future__ import annotations

import asyncio

import numpy as np

from app.diagnostics.health_index import error_code
from app.diagnostics.protection import ProtectionDiagnostic
from app.diagnostics.recommendations import get_recommendation
from app.diagnostics.schema import DiagFault, DiagSource, FusedDiagnosis
from app.diagnostics.supply import SupplyDiagnostic
from app.simulation.params import DEFAULT_MOTOR
from app.supervisory.sada import SadaSupervisor
from app.tests._harness import make


def make_sin_3ph(i_peak: float, n_samples: int = 500, fs: float = 5000.0, f0: float = 50.0) -> np.ndarray:
    t = np.arange(n_samples) / fs
    ia = i_peak * np.sin(2 * np.pi * f0 * t)
    ib = i_peak * np.sin(2 * np.pi * f0 * t - 2 * np.pi / 3)
    ic = i_peak * np.sin(2 * np.pi * f0 * t + 2 * np.pi / 3)
    return np.vstack([ia, ib, ic])


def test_i2t_inverse_time_overload():
    """Verifies that 2.5x current trips faster than 2.0x current under I^2 t inverse time curve."""
    params = DEFAULT_MOTOR
    prot = ProtectionDiagnostic(params, tau_ovl_s=20.0)
    dt = 0.1
    i_rated = params.rated_current

    # 1. Rated current: accumulator remains 0, stays HEALTHY
    i_1x = make_sin_3ph(i_rated * np.sqrt(2))
    for _ in range(50):
        v = prot.update(1.0, i_1x, 1450.0, dt)
    assert v.fault_type == DiagFault.HEALTHY
    assert prot.thermal_accumulator == 0.0

    # 2. 2.0x rated current: measure time to trip
    prot.reset()
    i_2x = make_sin_3ph(2.0 * i_rated * np.sqrt(2))
    t_trip_2x = None
    for step in range(300):
        v = prot.update(1.0 + step * dt, i_2x, 1420.0, dt)
        if v.fault_type == DiagFault.OVERLOAD and v.severity >= 1.0:
            t_trip_2x = step * dt
            break
    assert t_trip_2x is not None
    assert 5.0 <= t_trip_2x <= 10.0

    # 3. 2.5x rated current: should trip strictly faster than 2.0x
    prot.reset()
    i_25x = make_sin_3ph(2.5 * i_rated * np.sqrt(2))
    t_trip_25x = None
    for step in range(300):
        v = prot.update(1.0 + step * dt, i_25x, 1380.0, dt)
        if v.fault_type == DiagFault.OVERLOAD and v.severity >= 1.0:
            t_trip_25x = step * dt
            break
    assert t_trip_25x is not None
    assert t_trip_25x < t_trip_2x
    assert 2.0 <= t_trip_25x <= 6.0


def test_instantaneous_overcurrent_trips_immediately():
    """Current spikes >= 5.0x rated current trigger instantaneous OVERCURRENT with 1.0 severity."""
    params = DEFAULT_MOTOR
    prot = ProtectionDiagnostic(params)
    i_spike = make_sin_3ph(5.5 * params.rated_current * np.sqrt(2))

    v = prot.update(1.0, i_spike, 1450.0, 0.1)
    assert v.fault_type == DiagFault.OVERCURRENT
    assert v.confidence == 1.0
    assert v.severity == 1.0

    sada = SadaSupervisor()
    fused = FusedDiagnosis(1.0, DiagFault.OVERCURRENT, 1.0, 1.0, {})
    out = sada.update(fused)
    assert out.trip is True
    assert out.reason_code == "TRIP_OVERCURRENT"


def test_locked_rotor_stall_trips_fast():
    """High current with collapsed shaft speed triggers STALL within 0.6s."""
    params = DEFAULT_MOTOR
    prot = ProtectionDiagnostic(params)
    i_stall = make_sin_3ph(2.5 * params.rated_current * np.sqrt(2))
    dt = 0.1

    # Before 0.5s of stall condition: not tripped yet
    for step in range(4):
        v = prot.update(1.0 + step * dt, i_stall, rpm=50.0, dt=dt)
        assert v.fault_type != DiagFault.STALL

    # At 0.5s: STALL engages
    v = prot.update(1.4, i_stall, rpm=50.0, dt=dt)
    assert v.fault_type == DiagFault.STALL
    assert v.confidence == 1.0
    assert v.severity == 1.0

    from app.diagnostics.schema import FusedDiagnosis
    sada = SadaSupervisor()
    out = sada.update(FusedDiagnosis(1.5, DiagFault.STALL, 1.0, 1.0, {}))
    assert out.trip is True
    assert out.reason_code == "TRIP_STALL"


def test_phase_loss_single_phasing_detected():
    """Loss of one phase (current drops to 0 on phase C) triggers PHASE_LOSS."""
    params = DEFAULT_MOTOR
    prot = ProtectionDiagnostic(params)
    t = np.arange(500) / 5000.0
    ia = 4.0 * np.sqrt(2) * np.sin(2 * np.pi * 50.0 * t)
    ib = 4.0 * np.sqrt(2) * np.sin(2 * np.pi * 50.0 * t - 2 * np.pi / 3)
    ic = np.zeros_like(ia)  # lost phase
    i_missing = np.vstack([ia, ib, ic])
    dt = 0.1

    for step in range(2):
        prot.update(1.0 + step * dt, i_missing, rpm=1400.0, dt=dt)

    v = prot.update(1.3, i_missing, rpm=1400.0, dt=dt)
    assert v.fault_type == DiagFault.PHASE_LOSS
    assert v.confidence == 1.0
    assert v.severity >= 0.90

    from app.diagnostics.schema import FusedDiagnosis
    sada = SadaSupervisor()
    out = sada.update(FusedDiagnosis(1.3, DiagFault.PHASE_LOSS, 1.0, 0.95, {}))
    assert out.trip is True
    assert out.reason_code == "TRIP_PHASE_LOSS"


def test_voltage_sag_reachable_and_diagnosed():
    """SupplyDiagnostic produces DiagFault.VOLTAGE_SAG when voltage drops below 0.9 pu."""
    params = DEFAULT_MOTOR
    supply = SupplyDiagnostic(params.rated_voltage * np.sqrt(2) / np.sqrt(3))
    n = 500
    t = np.arange(n) / 5000.0
    # Sag to 0.75 pu
    v_peak = 0.75 * (params.rated_voltage * np.sqrt(2) / np.sqrt(3))
    ua = v_peak * np.sin(2 * np.pi * 50.0 * t)
    ub = v_peak * np.sin(2 * np.pi * 50.0 * t - 2 * np.pi / 3)
    uc = v_peak * np.sin(2 * np.pi * 50.0 * t + 2 * np.pi / 3)
    u_abc = np.vstack([ua, ub, uc])

    v = supply.analyze(u_abc, fs=5000.0, f=50.0)
    assert v.fault_type == DiagFault.VOLTAGE_SAG
    assert v.available is True


def test_protection_faults_have_recommendations_and_error_codes():
    """All protection faults have complete recommendation catalog entries and valid error codes."""
    protection_faults = [
        DiagFault.OVERLOAD,
        DiagFault.OVERCURRENT,
        DiagFault.STALL,
        DiagFault.PHASE_LOSS,
        DiagFault.VOLTAGE_SAG,
    ]
    for flt in protection_faults:
        # Recommendations in zones C and D
        rec_c = get_recommendation(1, flt, "C", 60.0)
        assert rec_c["fault_type"] == flt.value
        assert "checklist" in rec_c and len(rec_c["checklist"]) > 0

        rec_d = get_recommendation(1, flt, "D", 20.0)
        assert rec_d["fault_type"] == flt.value
        assert rec_d["urgency"] == "immediate"

        # Error code generation
        code = error_code(DiagSource.PROTECTION, flt, "D")
        assert flt.value[:3].upper() in code or code.startswith("PROT-") or code.startswith("SPLY-")


def test_worker_trips_on_heavy_overload():
    """Under 2.5x rated load (25 Nm on 1.5 kW motor), worker trips through protection channel."""
    # 1.5 kW motor rated torque is ~9.8 Nm. 25.0 Nm is 2.5x rated.
    w = make(load=25.0)

    async def scenario():
        tripped = False
        trip_reason = None
        for _ in range(150):  # 15 seconds simulated
            out = await w.tick()
            if out["supervisory"]["trip"]:
                tripped = True
                trip_reason = out["supervisory"]["reason_code"]
                break
        assert tripped is True
        assert (
            "OVERLOAD" in trip_reason
            or "STALL" in trip_reason
            or "OVERCURRENT" in trip_reason
            or "THERMAL" in trip_reason
        )

    asyncio.run(scenario())


def test_restart_after_deenergisation_gets_inrush_allowance():
    """Regression: the DOL start window used to be keyed on absolute time t<=0.5 s, so any restart
    later in a run (e.g. after a trip reset) tripped on the 5x running overcurrent limit."""
    params = DEFAULT_MOTOR
    prot = ProtectionDiagnostic(params)
    dt = 0.1
    running = make_sin_3ph(0.95 * params.rated_current * np.sqrt(2))
    off = make_sin_3ph(0.0)
    inrush = make_sin_3ph(5.4 * params.rated_current * np.sqrt(2))
    for k in range(20):
        prot.update(0.1 * (k + 1), running, rpm=1478.0, dt=dt)
    for k in range(50):  # tripped: supply off, rotor coasting down
        prot.update(2.0 + 0.1 * (k + 1), off, rpm=max(0.0, 1400 - 30 * k), dt=dt)
    # restart: first block already above 40 % speed while still drawing 5.4x inrush
    v = prot.update(7.1, inrush, rpm=1208.0, dt=dt)
    assert v.fault_type != DiagFault.OVERCURRENT
    v = prot.update(7.2, running, rpm=1478.0, dt=dt)
    assert v.fault_type == DiagFault.HEALTHY
    # ...but a genuine 5x overcurrent once running still trips
    for k in range(6):
        prot.update(7.3 + 0.1 * k, running, rpm=1478.0, dt=dt)
    assert prot.update(8.0, inrush, rpm=1478.0, dt=dt).fault_type == DiagFault.OVERCURRENT
