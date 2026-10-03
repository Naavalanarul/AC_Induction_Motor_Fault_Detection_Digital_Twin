import asyncio

from app.diagnostics.engine import DiagnosticEngine
from app.diagnostics.ml.classifier import MechanicalClassifier
from app.diagnostics.schema import DiagFault, FusedDiagnosis
from app.sensors import SensorRegistry
from app.simulation import faults as F
from app.simulation.twin_state import MotorSimulator
from app.supervisory.sada import SadaConfig, SadaState, SadaSupervisor


def test_derate_minimum_dwell_time_prevents_cycling():
    """Verify that once DERATE is entered, SADA dwells for at least 5.0 s before upward recovery."""
    cfg = SadaConfig(derate_min_dwell_s=5.0, derate=0.5, trip=0.8, hysteresis=0.05)
    s = SadaSupervisor(cfg)

    # 1. Drive into DERATE with severe fault
    d_severe = FusedDiagnosis(t=1.0, fault_type=DiagFault.BEARING_OUTER, confidence=0.9, severity=0.65, per_sensor_scores={})
    # Step just enough to enter DERATE (~18 ticks)
    for _ in range(20):
        s.update(d_severe, dt=0.1)
    assert s.state == SadaState.DERATE
    initial_dwell = s._derate_dwell_timer
    assert initial_dwell < 2.0  # just entered derate recently

    # 2. Symptoms suddenly dip to mild/healthy (severity = 0.0)
    d_mild = FusedDiagnosis(t=5.0, fault_type=DiagFault.HEALTHY, confidence=0.9, severity=0.0, per_sensor_scores={})

    # Within the 5.0s dwell window (advance 2.5s -> 25 ticks), SADA must NOT leave DERATE!
    for _ in range(25):
        out = s.update(d_mild, dt=0.1)
        assert out.state == SadaState.DERATE, f"State jumped to {out.state} before minimum dwell time"

    # 3. Advance past 5.0s total dwell in DERATE (another 35 ticks = 3.5s -> total dwell > 6.0s)
    for _ in range(35):
        out = s.update(d_mild, dt=0.1)
    assert out.state in (SadaState.WATCH, SadaState.NORMAL)


def test_asymmetric_load_rate_limiting():
    """Verify load commands ramp down quickly on fault and ramp up slowly on recovery."""
    cfg = SadaConfig(ramp_down_rate=0.8, ramp_up_rate=0.05)
    s = SadaSupervisor(cfg)
    s.state = SadaState.DERATE
    s._current_load_cmd = 1.0

    # Step into derate requiring target load = 0.6
    s.smoothed = 0.74  # frac = (0.74-0.5)/0.3 = 0.8 -> target_load = 1 - 0.8*0.5 = 0.6
    d = FusedDiagnosis(t=1.0, fault_type=DiagFault.BEARING_OUTER, confidence=0.9, severity=0.74, per_sensor_scores={})

    # One 0.1s tick: ramps down by at most ramp_down_rate * dt = 0.8 * 0.1 = 0.08
    out = s.update(d, dt=0.1)
    assert out.load_cmd <= 1.0 - 0.05  # responsive ramp down

    # Let it settle at target load 0.6
    for _ in range(50):
        out = s.update(d, dt=0.1)
    assert abs(out.load_cmd - 0.6) < 0.01

    # Now recover to NORMAL (target load = 1.0)
    s.state = SadaState.NORMAL
    s.smoothed = 0.0
    d_norm = FusedDiagnosis(t=10.0, fault_type=DiagFault.HEALTHY, confidence=0.9, severity=0.0, per_sensor_scores={})

    # At ramp_up_rate = 0.05/s, one 0.1s tick increases load by at most 0.005
    out_rec = s.update(d_norm, dt=0.1)
    assert out_rec.load_cmd <= 0.6 + 0.01  # slow smooth recovery ramp
    assert out_rec.load_cmd < 0.7  # does not jump directly to 1.0


def test_closed_loop_sustained_fault_stabilizes_without_hunting():
    """Closed-loop simulation under sustained fault does not oscillate; load stabilizes without cycling to 1.0."""
    sim = MotorSimulator(base_load_nm=8.0)
    reg = SensorRegistry(sim.state)
    eng = DiagnosticEngine(sim.state.params, sim.fs, classifier=MechanicalClassifier(use_ml=False))
    F.inject(sim.faults, "unbalance", 0.65, {})
    s = SadaSupervisor(SadaConfig(derate_min_dwell_s=5.0, hysteresis=0.05))

    loads: list[float] = []
    states: list[str] = []

    for _ in range(80):
        st = sim.step()
        frames = asyncio.run(reg.read_all())
        diag = eng.process(st.t, frames, sim.chunk_s)
        out = s.update(diag)
        sim.state.load_cmd = out.load_cmd
        sim.state.tripped = out.trip
        loads.append(out.load_cmd)
        states.append(out.state.value)

    # In the second half of the run (sustained derate/watch), load should be derated and stable
    second_half_states = states[40:]
    second_half_loads = loads[40:]

    # Once derate/watch is active, motor must not oscillate back to NORMAL
    assert second_half_states[-1] in (SadaState.DERATE.value, SadaState.WATCH.value)
    # Load in second half must not jump back to 1.0
    assert max(second_half_loads) < 1.0
    # Load spread during settled operation is small (no hunting limit cycle)
    load_spread = max(second_half_loads[-20:]) - min(second_half_loads[-20:])
    assert load_spread < 0.10, f"Load hunting detected, spread = {load_spread:.3f}"
