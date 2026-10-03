"""diagnostics/calibration.py — Unified Calibration & Feature Mapping for Fault Severity.

Provides single-source-of-truth mappings for:
1. Broken Rotor Bar (BRB):
   - MCSA sideband magnitude (dBc) -> continuous severity [0.0, 1.0]
   - Broken bar count (1..8) -> continuous severity [0.0, 1.0]
   - Severity -> expected broken bar count
2. Air-Gap Eccentricity (static, dynamic, mixed):
   - MCSA sideband magnitude (dBc) -> continuous severity [0.0, 1.0]
   - Eccentricity air-gap depth fraction -> continuous severity [0.0, 1.0]
   - Severity -> (dynamic_depth, static_depth)
3. Electrical Residual:
   - Fault Detection index (FD) -> continuous severity [0.0, 1.0]
4. Continuous severity [0.0, 1.0] -> discrete FaultSeverity enum
"""

from __future__ import annotations

from app.core_physics.fault_models import EccentricityType

# Thresholds in dBc relative to fundamental
BRB_DBC_MIN = -45.0  # Threshold of detection (~0% severity)
BRB_DBC_MAX = -20.0  # Severe multi-bar damage (100% severity)

ECC_DBC_MIN = -45.0  # Threshold of detection (~0% severity)
ECC_DBC_MAX = -20.0  # Severe air-gap rub risk (100% severity)

MAX_BROKEN_BARS = 8
MAX_AIRGAP_DEPTH = 0.15  # Max 15% air-gap clearance variation


def brb_db_to_severity(db: float | None) -> float:
    """Strictly monotonically maps BRB sideband magnitude (dBc) to [0.0, 1.0]."""
    if db is None or db <= BRB_DBC_MIN:
        return 0.0
    if db >= BRB_DBC_MAX:
        return 1.0
    return float((db - BRB_DBC_MIN) / (BRB_DBC_MAX - BRB_DBC_MIN))


def brb_count_to_severity(count: int, max_bars: int = MAX_BROKEN_BARS) -> float:
    """Strictly monotonically maps broken rotor bar count to severity [0.0, 1.0]."""
    if count <= 0:
        return 0.0
    return float(min(1.0, count / max_bars))


def brb_severity_to_count(severity: float, max_bars: int = MAX_BROKEN_BARS) -> int:
    """Maps continuous severity to expected broken rotor bar count."""
    return int(round(min(1.0, max(0.0, severity)) * max_bars))


def eccentricity_db_to_severity(db: float | None) -> float:
    """Strictly monotonically maps eccentricity sideband magnitude (dBc) to [0.0, 1.0]."""
    if db is None or db <= ECC_DBC_MIN:
        return 0.0
    if db >= ECC_DBC_MAX:
        return 1.0
    return float((db - ECC_DBC_MIN) / (ECC_DBC_MAX - ECC_DBC_MIN))


def eccentricity_depth_to_severity(depth: float, max_depth: float = MAX_AIRGAP_DEPTH) -> float:
    """Strictly monotonically maps air-gap depth variation fraction to severity [0.0, 1.0]."""
    if depth <= 0.0:
        return 0.0
    return float(min(1.0, depth / max_depth))


def eccentricity_severity_to_depth(
    severity: float,
    ecc_type: str = "dynamic",
    max_depth: float = MAX_AIRGAP_DEPTH,
) -> tuple[float, float]:
    """Maps continuous severity to (dynamic_depth, static_depth) airgap variation fractions.

    For mixed eccentricity, dynamic and static components share the total modulation.
    """
    s = min(1.0, max(0.0, float(severity)))
    depth = max_depth * s
    kind = ecc_type.lower()
    if kind == EccentricityType.STATIC.value:
        return 0.0, depth
    elif kind == EccentricityType.MIXED.value:
        return depth * 0.6, depth * 0.4
    else:  # default dynamic
        return depth, 0.0


def residual_fd_to_severity(
    fd: float,
    fd_threshold: float = 0.015,
    fd_full_scale: float = 0.15,
) -> float:
    """Strictly monotonically maps electrical residual FD index to severity [0.0, 1.0]."""
    if fd <= fd_threshold:
        return 0.0
    if fd >= fd_full_scale:
        return 1.0
    return float((fd - fd_threshold) / (fd_full_scale - fd_threshold))
