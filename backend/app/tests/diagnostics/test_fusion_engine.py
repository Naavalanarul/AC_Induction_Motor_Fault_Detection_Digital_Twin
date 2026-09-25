"""Phase 6: fusion output schema + channel isolation."""

import pytest

from app.diagnostics.fusion import fuse
from app.diagnostics.schema import SCHEMA_VERSION, ChannelVerdict, DiagFault, DiagSource


def v(source, fault, conf=0.9, sev=0.5, available=True):
    return ChannelVerdict(source, fault, conf, sev, available)


def test_fused_schema_is_frozen():
    d = fuse(1.0, [v(DiagSource.THERMAL, DiagFault.HEALTHY)]).to_dict()
    assert set(d) == {"t", "fault_type", "confidence", "severity", "per_sensor_scores", "secondary", "source",
                      "schema_version"}
    assert d["schema_version"] == SCHEMA_VERSION == "1.0"


def test_domain_weighting_prefers_authoritative_channel():
    d = fuse(0.0, [
        v(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.BROKEN_ROTOR_BAR, 0.8),
        v(DiagSource.ML_CLASSIFIER, DiagFault.UNBALANCE, 0.5),
        v(DiagSource.THERMAL, DiagFault.HEALTHY),
    ])
    assert d.fault_type == DiagFault.BROKEN_ROTOR_BAR
    assert d.secondary[0]["fault_type"] == "unbalance"


def test_all_healthy_and_all_unavailable():
    assert fuse(0, [v(DiagSource.THERMAL, DiagFault.HEALTHY)]).fault_type == DiagFault.HEALTHY
    assert fuse(0, [v(DiagSource.THERMAL, DiagFault.UNKNOWN, available=False)]).fault_type == DiagFault.UNKNOWN


def test_bearing_fault_detected_through_full_pipeline(pipeline):
    diag, *_ = pipeline("bearing_inner", 0.7, use_ml=False)
    assert diag.fault_type == DiagFault.BEARING_INNER


def test_ml_channel_crash_does_not_block_electrical(pipeline, monkeypatch):
    from app.diagnostics.engine import DiagnosticEngine

    def crash(self, frames, dt):
        raise RuntimeError("ml down")

    monkeypatch.setattr(DiagnosticEngine, "_run_mechanical", crash)
    diag, *_ = pipeline("interturn_short", 0.5, {"phase": "a"})
    assert diag.fault_type == DiagFault.INTERTURN_SHORT
    ml = diag.per_sensor_scores[DiagSource.ML_CLASSIFIER.value]
    assert ml["available"] is False and "error" in ml["details"]["reason"]


@pytest.mark.slow
def test_ml_backend_end_to_end(pipeline):
    diag, *_ = pipeline("misalignment", 0.7, use_ml=True)
    assert diag.fault_type == DiagFault.MISALIGNMENT
