"""diagnostics/health_index.py — Motor Health Index (MHI) and diagnostic error codes.

Computes a composite [0.0, 100.0] health scalar based on fused severity,
SADA supervisory state, and channel status. Maps to ISO 10816 / 20816 condition zones:
  - Zone A (Good):       85.0 <= MHI <= 100.0
  - Zone B (Acceptable): 70.0 <= MHI < 85.0
  - Zone C (Alert):      50.0 <= MHI < 70.0
  - Zone D (Danger):      0.0 <= MHI < 50.0

Generates concise industrial error codes:
  <SOURCE>-<FAULT>-<ZONE> (e.g. ELEC-BRB-D, VIB-BRGO-C, THM-OVH-C, SYS-OK-A)
"""

from __future__ import annotations

import math
from typing import Any

from app.diagnostics.schema import DiagFault, DiagSource, FusedDiagnosis
from app.supervisory.sada import SadaState

# State penalties applied to health index
STATE_PENALTY: dict[str, float] = {
    "NORMAL": 0.0,
    "WATCH": 10.0,
    "DERATE": 25.0,
    "TRIP": 60.0,
}

# Criticality weights for channel penalties when degraded/stale/lost
CHANNEL_CRITICALITY: dict[str, float] = {
    "current": 12.0,
    "voltage": 10.0,
    "speed": 10.0,
    "vibration": 8.0,
    "temp": 6.0,
    "temperature": 6.0,
    "thermal": 6.0,
    "acoustic": 4.0,
}

# Abbreviation mappings for error codes
SOURCE_ABBR: dict[str, str] = {
    "electrical_residual": "ELEC",
    "ml_classifier": "ML",
    "thermal": "THM",
    "supply": "SPLY",
    "protection": "PROT",
    "vibration": "VIB",
    "acoustic": "ACST",
    "fused": "FUSN",
    "sada": "SADA",
    "system": "SYS",
}

FAULT_ABBR: dict[str, str] = {
    "healthy": "OK",
    "broken_rotor_bar": "BRB",
    "interturn_short": "ITS",
    "eccentricity": "ECC",
    "bearing_inner": "BRGI",
    "bearing_outer": "BRGO",
    "bearing_ball": "BRGB",
    "unbalance": "UNB",
    "misalignment": "MIS",
    "overheating": "OVH",
    "supply_anomaly": "SPLY",
    "voltage_sag": "VSAG",
    "phase_loss": "PHL",
    "overload": "OVL",
    "overcurrent": "OVC",
    "stall": "STL",
    "indeterminate": "IND",
    "unknown": "UNK",
}

# Default source per fault type when source is generic fused/system
FAULT_DEFAULT_SOURCE: dict[str, str] = {
    "broken_rotor_bar": "ELEC",
    "interturn_short": "ELEC",
    "eccentricity": "ELEC",
    "bearing_inner": "VIB",
    "bearing_outer": "VIB",
    "bearing_ball": "VIB",
    "unbalance": "VIB",
    "misalignment": "VIB",
    "overheating": "THM",
    "supply_anomaly": "SPLY",
    "voltage_sag": "SPLY",
    "phase_loss": "PROT",
    "overload": "PROT",
    "overcurrent": "PROT",
    "stall": "PROT",
    "healthy": "SYS",
    "indeterminate": "SYS",
    "unknown": "SYS",
}


def zone_from_mhi(mhi: float) -> str:
    """Classifies Motor Health Index into ISO zones A, B, C, or D."""
    if mhi >= 85.0:
        return "A"
    if mhi >= 70.0:
        return "B"
    if mhi >= 50.0:
        return "C"
    return "D"


def compute_mhi(
    diag_or_severity: FusedDiagnosis | float,
    sada_state: SadaState | str = SadaState.NORMAL,
    channel_status: dict[str, Any] | None = None,
    latched_severity: float | None = None,
) -> tuple[float, str]:
    """Computes the Motor Health Index (MHI) in [0.0, 100.0] and the ISO zone.

    Args:
        diag_or_severity: FusedDiagnosis instance or float severity in [0.0, 1.0].
        sada_state: Current SADA supervisory state.
        channel_status: Optional mapping of sensor channel statuses.
        latched_severity: Optional latched severity (e.g. from SADA) to ensure MHI never
            increases during channel starvation or sensor loss.

    Returns:
        tuple (mhi: float, zone: str) where zone is 'A', 'B', 'C', or 'D'.
    """
    if isinstance(diag_or_severity, FusedDiagnosis):
        severity = float(diag_or_severity.severity)
    else:
        severity = float(diag_or_severity)
    if latched_severity is not None and math.isfinite(latched_severity):
        severity = max(severity, float(latched_severity))
    severity = max(0.0, min(1.0, severity))

    state_name = sada_state.value if isinstance(sada_state, SadaState) else str(sada_state).upper()
    state_pen = STATE_PENALTY.get(state_name, 0.0)

    # Severity deduction: scales from 0 to 60.0
    sev_pen = severity * 60.0

    # Sensor channel deduction (if any channel is degraded/error/stale/lost)
    chan_pen = 0.0
    if channel_status:
        for chan_name, status_val in channel_status.items():
            st = getattr(status_val, "value", str(status_val)).lower()
            if st in ("degraded", "fault", "error", "lost", "stale", "offline"):
                crit = CHANNEL_CRITICALITY.get(str(chan_name).lower(), 6.0)
                chan_pen += crit
        chan_pen = min(50.0, chan_pen)

    mhi = max(0.0, min(100.0, 100.0 - sev_pen - state_pen - chan_pen))
    mhi = round(mhi, 1)
    return mhi, zone_from_mhi(mhi)


compute_health_index = compute_mhi


def error_code(
    source: str | DiagSource = "fused",
    fault_type: str | DiagFault = "healthy",
    zone: str = "A",
) -> str:
    """Formats an industrial diagnostic error code: <SOURCE>-<FAULT>-<ZONE>.

    Examples:
        error_code("electrical_residual", "broken_rotor_bar", "D") -> "ELEC-BRB-D"
        error_code("fused", "healthy", "A") -> "SYS-OK-A"
        error_code("thermal", "overheating", "C") -> "THM-OVH-C"
    """
    src_val = source.value if isinstance(source, DiagSource) else str(source).lower()
    flt_val = fault_type.value if isinstance(fault_type, DiagFault) else str(fault_type).lower()

    if flt_val in ("healthy", "none"):
        return f"SYS-OK-{zone}"

    src_abbr = SOURCE_ABBR.get(src_val)
    if src_abbr is None or src_abbr == "FUSN":
        src_abbr = FAULT_DEFAULT_SOURCE.get(flt_val, "SYS")

    flt_abbr = FAULT_ABBR.get(flt_val, flt_val[:3].upper())
    return f"{src_abbr}-{flt_abbr}-{zone}"
