"""tests/validation/test_regression_invariance.py

Regression test ensuring paper experimentation code did not alter the live system behavior
of multi-sensor fusion (fuse) and SADA supervisory controller (SadaSupervisor) for fixed input sequences.
"""

from __future__ import annotations

from app.diagnostics.fusion import FusedDiagnosis, fuse
from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource
from app.supervisory.sada import SadaConfig, SadaState, SadaSupervisor


def test_fuse_regression_fixed_input():
    verdicts = [
        ChannelVerdict(
            source=DiagSource.ELECTRICAL_RESIDUAL,
            fault_type=DiagFault.INTERTURN_SHORT,
            severity=0.65,
            confidence=0.85,
            available=True,
        ),
        ChannelVerdict(
            source=DiagSource.ML_CLASSIFIER,
            fault_type=DiagFault.BROKEN_ROTOR_BAR,
            severity=0.40,
            confidence=0.70,
            available=True,
        ),
        ChannelVerdict(
            source=DiagSource.THERMAL,
            fault_type=DiagFault.BEARING_INNER,
            severity=0.30,
            confidence=0.60,
            available=True,
        ),
    ]

    fused = fuse(0.0, verdicts)

    assert isinstance(fused, FusedDiagnosis)
    assert fused.fault_type == DiagFault.INTERTURN_SHORT
    assert 0.4 <= fused.severity <= 0.8
    assert 0.5 <= fused.confidence <= 1.0


def test_sada_supervisor_regression_fixed_sequence():
    config = SadaConfig(
        watch=0.30,
        derate=0.50,
        trip=0.80,
        ema_alpha=0.20,
    )
    sada = SadaSupervisor(config)

    # 1. Healthy sequence
    h_diag = FusedDiagnosis(t=0.0, fault_type=DiagFault.HEALTHY, severity=0.05, confidence=0.90, per_sensor_scores={})
    for i in range(5):
        h_diag.t = i * 0.1
        out = sada.update(h_diag, dt=0.1)
    assert sada.state == SadaState.NORMAL
    assert out.state == SadaState.NORMAL
    assert out.load_cmd == 1.0

    # 2. Step jump to derate level (0.65 severity)
    d_diag = FusedDiagnosis(t=1.0, fault_type=DiagFault.BEARING_OUTER, severity=0.65, confidence=0.85, per_sensor_scores={})
    outputs = []
    for i in range(15):
        d_diag.t = 1.0 + i * 0.1
        outputs.append(sada.update(d_diag, dt=0.1))

    states = [o.state for o in outputs]
    assert SadaState.DERATE in states or SadaState.WATCH in states
    assert sada._current_load_cmd < 1.0

    # 3. Severe trip spike sustained
    trip_diag = FusedDiagnosis(t=5.0, fault_type=DiagFault.OVERCURRENT, severity=0.98, confidence=0.98, per_sensor_scores={})
    for i in range(15):
        trip_diag.t = 5.0 + i * 0.1
        final_out = sada.update(trip_diag, dt=0.1)

    assert sada.state == SadaState.TRIP
    assert final_out.state == SadaState.TRIP
    assert final_out.load_cmd == 0.0
