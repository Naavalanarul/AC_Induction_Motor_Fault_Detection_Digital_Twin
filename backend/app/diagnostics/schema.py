"""diagnostics/schema.py

Frozen output schema of the diagnostic engine (SCHEMA_VERSION 1.0).
Every channel emits a `ChannelVerdict`; fusion emits one `FusedDiagnosis`.
Do not change field names/semantics without bumping SCHEMA_VERSION and the API version.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

SCHEMA_VERSION = "1.0"


class DiagFault(str, Enum):
    HEALTHY = "healthy"
    BROKEN_ROTOR_BAR = "broken_rotor_bar"
    INTERTURN_SHORT = "interturn_short"
    ECCENTRICITY = "eccentricity"
    BEARING_INNER = "bearing_inner"
    BEARING_OUTER = "bearing_outer"
    BEARING_BALL = "bearing_ball"
    UNBALANCE = "unbalance"
    MISALIGNMENT = "misalignment"
    OVERHEATING = "overheating"
    SUPPLY_ANOMALY = "supply_anomaly"
    VOLTAGE_SAG = "voltage_sag"
    OVERLOAD = "overload"
    OVERCURRENT = "overcurrent"
    STALL = "stall"
    PHASE_LOSS = "phase_loss"
    INDETERMINATE = "indeterminate"
    UNKNOWN = "unknown"


class DiagSource(str, Enum):
    ELECTRICAL_RESIDUAL = "electrical_residual"
    ML_CLASSIFIER = "ml_classifier"
    THERMAL = "thermal"
    SUPPLY = "supply"
    PROTECTION = "protection"
    FUSED = "fused"


def _sanitize_val(val: object) -> object:
    if hasattr(val, "item") and callable(val.item):
        return val.item()
    if isinstance(val, dict):
        return {k: _sanitize_val(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_sanitize_val(v) for v in val]
    return val


@dataclass
class ChannelVerdict:
    source: DiagSource
    fault_type: DiagFault
    confidence: float           # [0, 1]
    severity: float             # [0, 1]
    available: bool = True      # False when the channel could not produce a verdict
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = float(self.confidence)
        self.severity = float(self.severity)
        if self.details:
            self.details = _sanitize_val(self.details)  # type: ignore[assignment]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source"] = self.source.value
        d["fault_type"] = self.fault_type.value
        return d


@dataclass
class FusedDiagnosis:
    t: float
    fault_type: DiagFault
    confidence: float
    severity: float
    per_sensor_scores: dict[str, dict]
    secondary: list[dict] = field(default_factory=list)
    source: DiagSource = DiagSource.FUSED
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.t = float(self.t)
        self.confidence = float(self.confidence)
        self.severity = float(self.severity)
        if self.per_sensor_scores:
            self.per_sensor_scores = _sanitize_val(self.per_sensor_scores)  # type: ignore[assignment]
        if self.secondary:
            self.secondary = _sanitize_val(self.secondary)  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "t": float(self.t),
            "fault_type": self.fault_type.value,
            "confidence": round(float(self.confidence), 4),
            "severity": round(float(self.severity), 4),
            "per_sensor_scores": self.per_sensor_scores,
            "secondary": self.secondary,
            "source": self.source.value,
            "schema_version": self.schema_version,
        }
