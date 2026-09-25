from app.diagnostics.schema import DiagFault, DiagSource, FusedDiagnosis
from app.supervisory.sada import SadaConfig, SadaState, SadaSupervisor


def diag(fault=DiagFault.HEALTHY, conf=0.9, sev=0.0, thermal_critical=False):
    per = {DiagSource.THERMAL.value: {"details": {"critical": thermal_critical}}}
    return FusedDiagnosis(0.0, fault, conf, sev, per)


def run(s, d, n):
    out = None
    for _ in range(n):
        out = s.update(d)
    return out


def test_low_confidence_is_gated():
    s = SadaSupervisor()
    out = run(s, diag(DiagFault.UNBALANCE, conf=0.4, sev=0.9), 100)
    assert out.state == SadaState.NORMAL and out.load_cmd == 1.0


def test_graded_escalation_and_derate():
    s = SadaSupervisor()
    out = run(s, diag(DiagFault.BEARING_OUTER, sev=0.65), 200)
    assert out.state == SadaState.DERATE
    assert 0.5 < out.load_cmd < 1.0
    assert out.reason_code == "DERATE_BEARING_OUTER"


def test_trip_latches_until_reset_and_reset_refused_while_severe():
    s = SadaSupervisor()
    out = run(s, diag(DiagFault.INTERTURN_SHORT, sev=0.9), 200)
    assert out.trip and out.load_cmd == 0.0
    assert s.reset() is False  # still severe
    out = run(s, diag(), 200)
    assert out.state == SadaState.TRIP  # latched
    assert s.reset() is True
    assert s.update(diag()).state == SadaState.NORMAL


def test_thermal_critical_trips_immediately():
    s = SadaSupervisor()
    out = s.update(diag(thermal_critical=True))
    assert out.trip and out.reason_code == "TRIP_THERMAL"


def test_emergency_bypasses_smoothing():
    s = SadaSupervisor(SadaConfig())
    out = s.update(diag(DiagFault.INTERTURN_SHORT, conf=0.95, sev=0.97))
    assert out.trip and out.reason_code.startswith("TRIP_EMERGENCY")


def test_hysteresis_prevents_chatter():
    s = SadaSupervisor()
    run(s, diag(DiagFault.UNBALANCE, sev=0.35), 300)
    assert s.state == SadaState.WATCH
    s.smoothed = 0.28  # just below watch threshold but within hysteresis band
    assert s.update(diag(DiagFault.UNBALANCE, sev=0.28)).state == SadaState.WATCH


def test_manual_override():
    s = SadaSupervisor()
    s.set_manual_load(0.4)
    out = s.update(diag())
    assert out.manual_override and out.load_cmd == 0.4
    s.set_manual_load(None)
    assert s.update(diag()).load_cmd == 1.0


def test_closed_loop_derate_reduces_load(pipeline):
    s = SadaSupervisor()
    _, out, sim, _ = pipeline("unbalance", 0.8, chunks=100, sada=s)
    assert out.state in (SadaState.DERATE, SadaState.WATCH)
    assert sim.state.load_cmd < 1.0 or out.state == SadaState.WATCH
