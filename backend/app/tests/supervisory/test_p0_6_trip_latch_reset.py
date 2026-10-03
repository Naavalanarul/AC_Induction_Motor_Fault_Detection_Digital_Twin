from app.diagnostics.schema import DiagFault, DiagSource, FusedDiagnosis
from app.supervisory.sada import SadaConfig, SadaState, SadaSupervisor


def test_trip_latches_evidence():
    """Verify trip latches fault type, severity, temperature, and timestamp."""
    cfg = SadaConfig()
    s = SadaSupervisor(cfg)

    # Create severe diagnosis
    diag = FusedDiagnosis(
        t=12.5,
        fault_type=DiagFault.INTERTURN_SHORT,
        confidence=0.95,
        severity=0.98,
        per_sensor_scores={
            DiagSource.THERMAL.value: {"details": {"temp_c": 115.5}},
        },
    )

    out = s.update(diag, dt=0.1, current_temp=115.5)
    assert out.trip is True
    assert s.state == SadaState.TRIP

    # Check latched evidence
    assert s.latched_fault == DiagFault.INTERTURN_SHORT
    assert s.latched_severity is not None and s.latched_severity >= 0.95
    assert s.latched_temp == 115.5
    assert s.trip_time == 12.5
    assert out.latched_fault == DiagFault.INTERTURN_SHORT.value
    assert out.latched_temp == 115.5
    assert out.trip_time == 12.5

    # Run another tick with cleared/healthy diagnosis: latched values must persist
    diag_clear = FusedDiagnosis(t=12.6, fault_type=DiagFault.HEALTHY, confidence=0.99, severity=0.0, per_sensor_scores={})
    out2 = s.update(diag_clear, dt=0.1, current_temp=60.0)
    assert out2.trip is True  # still latched
    assert s.latched_fault == DiagFault.INTERTURN_SHORT
    assert s.latched_temp == 115.5
    assert s.trip_time == 12.5


def test_reset_cooldown_enforced():
    """Reset must be refused until minimum cooldown time (5.0s) has elapsed."""
    s = SadaSupervisor(SadaConfig(cooldown_s=5.0))
    diag = FusedDiagnosis(t=10.0, fault_type=DiagFault.OVERCURRENT, confidence=1.0, severity=1.0, per_sensor_scores={})
    s.update(diag, dt=0.1)
    assert s.state == SadaState.TRIP
    assert s.trip_time == 10.0

    # Advance to t=12.0 (elapsed = 2.0s < 5.0s)
    can, msg = s.can_reset(t=12.0)
    assert can is False
    assert "COOLDOWN_ACTIVE" in msg
    assert s.reset(t=12.0) is False
    assert s.state == SadaState.TRIP

    # Advance to t=15.1 (elapsed = 5.1s > 5.0s) with cleared fault
    s.smoothed = 0.1  # fault cleared
    can, msg = s.can_reset(t=15.1)
    assert can is True
    assert s.reset(t=15.1) is True
    assert s.state == SadaState.NORMAL


def test_reset_temperature_guard():
    """Reset must be refused if temperature >= warn_temp_c - 5.0 C without forced reason."""
    s = SadaSupervisor(SadaConfig(warn_temp_c=130.0, cooldown_s=5.0))
    s.trip("TRIP_THERMAL", t=10.0)
    s.smoothed = 0.0  # fault cleared

    # Cooldown has passed at t=20.0, but temp is 126.0 C (>= 125.0 C safe restart limit)
    can, msg = s.can_reset(t=20.0, current_temp=126.0)
    assert can is False
    assert "THERMAL_HIGH" in msg
    assert s.reset(t=20.0, current_temp=126.0) is False

    # Reset with forced audit reason bypasses thermal guard
    assert s.reset(t=20.0, current_temp=126.0, forced_reason="Emergency pump restart approved by plant manager") is True
    assert s.state == SadaState.NORMAL
    assert "RESET_BY_OPERATOR" in s.reason


def test_restart_attempt_limiting_lockout():
    """Exceeding 3 resets within 10 minutes (600s) triggers lockout."""
    s = SadaSupervisor(SadaConfig(max_reset_attempts=3, reset_window_s=600.0, cooldown_s=5.0))

    # Reset 1 at t=20.0
    s.trip("TRIP_1", t=10.0)
    s.smoothed = 0.0
    assert s.reset(t=20.0) is True

    # Reset 2 at t=40.0
    s.trip("TRIP_2", t=30.0)
    s.smoothed = 0.0
    assert s.reset(t=40.0) is True

    # Reset 3 at t=60.0
    s.trip("TRIP_3", t=50.0)
    s.smoothed = 0.0
    assert s.reset(t=60.0) is True

    # Trip 4 at t=70.0 -> attempt 4th reset at t=80.0
    s.trip("TRIP_4", t=70.0)
    s.smoothed = 0.0
    can, msg = s.can_reset(t=80.0)
    assert can is False
    assert "LOCKOUT" in msg
    assert s.reset(t=80.0) is False
    assert s.lockout is True

    # Operator explicitly unlocks
    s.clear_lockout()
    assert s.lockout is False
    assert s.reset(t=81.0) is True
    assert s.state == SadaState.NORMAL
