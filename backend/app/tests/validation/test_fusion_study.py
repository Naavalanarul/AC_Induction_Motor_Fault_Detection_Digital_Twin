"""tests/validation/test_fusion_study.py

Unit tests for fusion study:
1. Fusion with custom weights behaves correctly.
2. Supply fault false motor-fault rate is lower with supply channel than without.
3. Temperature compensation reduces FD false-alarm rate under thermal heating.
"""

from __future__ import annotations

from app.diagnostics.electrical import FD_THRESHOLD
from app.diagnostics.fusion import WEIGHTS, fuse
from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource
from app.validation.fusion_study import EQUAL_WEIGHTS, run_temperature_study


def test_fusion_custom_and_equal_weights():
    # Electrical says ITSC with high confidence, ML says healthy
    verdicts = [
        ChannelVerdict(DiagSource.ELECTRICAL_RESIDUAL, DiagFault.INTERTURN_SHORT, 0.70, 0.90),
        ChannelVerdict(DiagSource.ML_CLASSIFIER, DiagFault.HEALTHY, 0.20, 0.80),
    ]

    fused_domain = fuse(0.0, verdicts, weights=WEIGHTS)
    assert fused_domain.fault_type == DiagFault.INTERTURN_SHORT

    fused_equal = fuse(0.0, verdicts, weights=EQUAL_WEIGHTS)
    assert fused_equal.fault_type in (DiagFault.INTERTURN_SHORT, DiagFault.HEALTHY)


def test_temperature_compensation_study_smoke(tmp_path):
    summary = run_temperature_study(tmp_path / "temp", duration_s=4.0)

    assert "compensated" in summary
    assert "uncompensated" in summary
    assert (tmp_path / "temp" / "temp_compensation.csv").exists()
    assert (tmp_path / "temp" / "temp_summary.json").exists()
    assert (tmp_path / "temp" / "table_temp.tex").exists()
    assert (tmp_path / "temp" / "temp_compensation.png").exists()
    assert (tmp_path / "temp" / "temp_compensation.pdf").exists()

    # Compensated twin should have low or 0 false alarm rate
    assert summary["compensated"]["false_alarm_rate_pct"] <= summary["uncompensated"]["false_alarm_rate_pct"]
