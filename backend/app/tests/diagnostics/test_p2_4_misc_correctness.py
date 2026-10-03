from __future__ import annotations

import math

import numpy as np

from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource, FusedDiagnosis
from app.diagnostics.supply import SupplyDiagnostic


def test_p2_4_numpy_scalars_converted_at_verdict_boundary():
    """P2-4: np.float64/np.float32 must be cast to pure Python float at ChannelVerdict boundary."""
    np_conf = np.float64(0.85)
    np_sev = np.float32(0.42)
    np_t = np.float64(12.34)

    verdict = ChannelVerdict(
        source=DiagSource.ELECTRICAL_RESIDUAL,
        fault_type=DiagFault.BROKEN_ROTOR_BAR,
        confidence=np_conf,  # type: ignore[arg-type]
        severity=np_sev,    # type: ignore[arg-type]
        details={"np_val": np.float64(1.23), "nested": {"fl": np.float32(4.56)}, "lst": [np.float64(7.89)]},
    )

    assert type(verdict.confidence) is float
    assert type(verdict.severity) is float
    assert type(verdict.details["np_val"]) is float
    assert type(verdict.details["nested"]["fl"]) is float
    assert type(verdict.details["lst"][0]) is float

    # FusedDiagnosis boundary
    fused = FusedDiagnosis(
        t=np_t,  # type: ignore[arg-type]
        fault_type=DiagFault.BROKEN_ROTOR_BAR,
        confidence=np_conf,  # type: ignore[arg-type]
        severity=np_sev,    # type: ignore[arg-type]
        per_sensor_scores={"test": {"s": np.float64(0.99)}},
    )

    assert type(fused.t) is float
    assert type(fused.confidence) is float
    assert type(fused.severity) is float
    assert type(fused.per_sensor_scores["test"]["s"]) is float

    wire_dict = fused.to_dict()
    assert type(wire_dict["t"]) is float
    assert type(wire_dict["confidence"]) is float
    assert type(wire_dict["severity"]) is float


def test_p2_4_supply_verdict_uses_pure_floats():
    """P2-4: SupplyDiagnostic emits pure Python floats in confidence, severity and details."""
    v_peak = 400.0 * math.sqrt(2) / math.sqrt(3)
    supply_diag = SupplyDiagnostic(v_peak)

    fs = 5000.0
    n = 5000
    t = np.arange(n) / fs
    f_grid = 50.0

    # Clean balanced 3-phase voltage
    ua = v_peak * np.sin(2 * math.pi * f_grid * t)
    ub = v_peak * np.sin(2 * math.pi * f_grid * t - 2 * math.pi / 3)
    uc = v_peak * np.sin(2 * math.pi * f_grid * t + 2 * math.pi / 3)
    u_abc = np.vstack([ua, ub, uc])

    verdict_healthy = supply_diag.analyze(u_abc, fs, f_grid)
    assert verdict_healthy.fault_type == DiagFault.HEALTHY
    assert type(verdict_healthy.confidence) is float
    assert type(verdict_healthy.severity) is float
    for k, v in verdict_healthy.details.items():
        assert type(v) in (float, int, str, bool), f"Key {k} is not a Python primitive: {type(v)}"

    # Sagged / distorted voltage (excess >= 1.0)
    u_abc_sag = u_abc * 0.70  # 30% sag
    verdict_sag = supply_diag.analyze(u_abc_sag, fs, f_grid)
    assert verdict_sag.fault_type == DiagFault.VOLTAGE_SAG
    assert type(verdict_sag.confidence) is float
    assert type(verdict_sag.severity) is float
    for k, v in verdict_sag.details.items():
        assert type(v) in (float, int, str, bool), f"Key {k} is not a Python primitive: {type(v)}"


def test_p2_4_supply_harmonic_severity_mapping():
    """P2-4: Severity 0.5 gives THD ~6% (< 8% limit) and is healthy; severity >= 0.70 exceeds 8%."""
    v_peak = 400.0 * math.sqrt(2) / math.sqrt(3)
    supply_diag = SupplyDiagnostic(v_peak, thd_limit=0.08)

    fs = 5000.0
    n = 5000
    t = np.arange(n) / fs
    f_grid = 50.0

    # Fundamental
    ua = v_peak * np.sin(2 * math.pi * f_grid * t)
    ub = v_peak * np.sin(2 * math.pi * f_grid * t - 2 * math.pi / 3)
    uc = v_peak * np.sin(2 * math.pi * f_grid * t + 2 * math.pi / 3)

    # Add 5th and 7th harmonics corresponding to severity 0.5 (approx 6% THD)
    h5_amp = 0.045 * v_peak
    h7_amp = 0.035 * v_peak
    harm = h5_amp * np.sin(2 * math.pi * 5 * f_grid * t) + h7_amp * np.sin(2 * math.pi * 7 * f_grid * t)
    u_abc_05 = np.vstack([ua + harm, ub, uc])

    verdict_05 = supply_diag.analyze(u_abc_05, fs, f_grid)
    # At ~6% THD (below 8% limit), should be considered HEALTHY
    assert verdict_05.fault_type == DiagFault.HEALTHY
    assert verdict_05.details["thd"] < 0.08

    # Add higher harmonics corresponding to severe distortion (severity >= 0.75, THD ~ 12%)
    h5_heavy = 0.10 * v_peak
    h7_heavy = 0.08 * v_peak
    harm_heavy = h5_heavy * np.sin(2 * math.pi * 5 * f_grid * t) + h7_heavy * np.sin(2 * math.pi * 7 * f_grid * t)
    u_abc_heavy = np.vstack([ua + harm_heavy, ub, uc])

    verdict_heavy = supply_diag.analyze(u_abc_heavy, fs, f_grid)
    assert verdict_heavy.fault_type == DiagFault.SUPPLY_ANOMALY
    assert verdict_heavy.details["thd"] > 0.08
