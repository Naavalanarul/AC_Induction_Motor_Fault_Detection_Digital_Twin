import itertools

from app.diagnostics.fusion import fuse
from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource, FusedDiagnosis
from app.supervisory.sada import SadaConfig, SadaState, SadaSupervisor


def test_motor_fault_prioritized_over_supply_anomaly_in_fusion():
    """Verify motor faults are prioritized over supply anomalies in ranking and SADA."""
    # Bearing outer fault (ML classifier source, weight 0.35)
    v_bearing = ChannelVerdict(
        source=DiagSource.ML_CLASSIFIER,
        fault_type=DiagFault.BEARING_OUTER,
        confidence=0.75,
        severity=0.64,
        details={"sideband_snr_db": 15.0},
    )
    # Voltage sag (supply source, weight 0.20)
    v_supply = ChannelVerdict(
        source=DiagSource.SUPPLY,
        fault_type=DiagFault.VOLTAGE_SAG,
        confidence=0.85,
        severity=0.52,
        details={"v_sag_pct": 18.0},
    )

    # 1. Fusion order test
    fused = fuse(1.0, [v_bearing, v_supply])
    assert fused.fault_type == DiagFault.BEARING_OUTER
    assert fused.severity >= 0.64
    # Both reported
    reported_faults = {fused.fault_type.value} | {s["fault_type"] for s in fused.secondary}
    assert DiagFault.BEARING_OUTER.value in reported_faults
    assert DiagFault.VOLTAGE_SAG.value in reported_faults

    # 2. SADA integration test: SADA derates on BEARING_OUTER with 0.64 severity
    sada = SadaSupervisor(SadaConfig(derate=0.5, trip=0.8))
    out = None
    for _ in range(150):
        out = sada.update(fused)
    assert out is not None
    assert out.state == SadaState.DERATE
    assert out.fault_type == DiagFault.BEARING_OUTER.value
    assert "BEARING_OUTER" in out.reason_code
    assert 0.5 <= out.load_cmd < 1.0


def test_fusion_permutation_invariance():
    """Changing the order of verdicts passed to fuse() yields identical ranking and top fault."""
    v1 = ChannelVerdict(
        source=DiagSource.ML_CLASSIFIER,
        fault_type=DiagFault.BEARING_INNER,
        confidence=0.70,
        severity=0.55,
    )
    v2 = ChannelVerdict(
        source=DiagSource.ELECTRICAL_RESIDUAL,
        fault_type=DiagFault.BROKEN_ROTOR_BAR,
        confidence=0.65,
        severity=0.60,
    )
    v3 = ChannelVerdict(
        source=DiagSource.SUPPLY,
        fault_type=DiagFault.VOLTAGE_SAG,
        confidence=0.80,
        severity=0.45,
    )

    verdicts = [v1, v2, v3]
    baseline_fused: FusedDiagnosis | None = None

    for perm in itertools.permutations(verdicts):
        result = fuse(2.0, list(perm))
        if baseline_fused is None:
            baseline_fused = result
        else:
            assert result.fault_type == baseline_fused.fault_type
            assert result.confidence == baseline_fused.confidence
            assert result.severity == baseline_fused.severity
            # Check secondary list identical in order and content
            assert len(result.secondary) == len(baseline_fused.secondary)
            for s_res, s_base in zip(result.secondary, baseline_fused.secondary, strict=True):
                assert s_res["fault_type"] == s_base["fault_type"]
                assert s_res["confidence"] == s_base["confidence"]
                assert s_res["severity"] == s_base["severity"]
                assert s_res["sources"] == s_base["sources"]


def test_coexisting_brb_and_bearing_inner():
    """Coexisting BRB + bearing_inner: both reported in fused output and highest risk prioritized."""
    v_brb = ChannelVerdict(
        source=DiagSource.ELECTRICAL_RESIDUAL,
        fault_type=DiagFault.BROKEN_ROTOR_BAR,
        confidence=0.75,
        severity=0.70,
    )
    v_bearing = ChannelVerdict(
        source=DiagSource.ML_CLASSIFIER,
        fault_type=DiagFault.BEARING_INNER,
        confidence=0.65,
        severity=0.50,
    )

    fused = fuse(3.0, [v_brb, v_bearing])
    reported = [fused.fault_type.value] + [s["fault_type"] for s in fused.secondary]
    assert DiagFault.BROKEN_ROTOR_BAR.value in reported
    assert DiagFault.BEARING_INNER.value in reported
    assert fused.fault_type == DiagFault.BROKEN_ROTOR_BAR
    assert fused.severity >= 0.70


def test_sada_inspects_secondary_credible_fault_worst_case():
    """If primary is low severity but credible secondary is high severity, SADA tracks the worst fault."""
    # Synthetic fused diagnosis with low severity primary and high severity secondary
    fused = FusedDiagnosis(
        t=10.0,
        fault_type=DiagFault.UNBALANCE,
        confidence=0.80,
        severity=0.35,
        per_sensor_scores={},
        secondary=[
            {
                "fault_type": DiagFault.INTERTURN_SHORT.value,
                "confidence": 0.75,
                "severity": 0.85,
                "sources": ["electrical_residual"],
            }
        ],
    )

    sada = SadaSupervisor()
    out = None
    for _ in range(150):
        out = sada.update(fused)
    assert out is not None
    # SADA should escalate based on the worse credible secondary fault (INTERTURN_SHORT with 0.85 severity)
    assert out.state == SadaState.TRIP
    assert out.fault_type == DiagFault.INTERTURN_SHORT.value
