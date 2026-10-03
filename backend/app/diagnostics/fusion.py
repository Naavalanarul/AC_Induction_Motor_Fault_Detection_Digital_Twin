"""diagnostics/fusion.py — weighted-voting fusion of channel verdicts.

Each available channel votes for its fault type with weight * confidence.
Weights reflect which channel is authoritative for which fault domain (e.g. the
electrical residual for rotor/stator faults, the vibration/acoustic classifier
for mechanical faults). The top-voted non-healthy fault wins if its vote
exceeds the healthy vote and a minimum confidence; the rest are reported as
secondary findings.
"""

from __future__ import annotations

import math

from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource, FusedDiagnosis

ELECTRICAL = {DiagFault.BROKEN_ROTOR_BAR, DiagFault.INTERTURN_SHORT, DiagFault.ECCENTRICITY}
MECHANICAL = {DiagFault.BEARING_INNER, DiagFault.BEARING_OUTER, DiagFault.BEARING_BALL,
              DiagFault.UNBALANCE, DiagFault.MISALIGNMENT}

WEIGHTS = {
    DiagSource.ELECTRICAL_RESIDUAL: {"electrical": 1.0, "mechanical": 0.3, "other": 0.3},
    DiagSource.ML_CLASSIFIER: {"electrical": 0.3, "mechanical": 1.0, "other": 0.3},
    DiagSource.THERMAL: {"electrical": 0.2, "mechanical": 0.2, "other": 1.0},
    DiagSource.SUPPLY: {"electrical": 0.2, "mechanical": 0.2, "other": 1.0},
}
MIN_CONFIDENCE = 0.35


def _domain(f: DiagFault) -> str:
    return "electrical" if f in ELECTRICAL else "mechanical" if f in MECHANICAL else "other"


def fuse(t: float, verdicts: list[ChannelVerdict]) -> FusedDiagnosis:
    per_sensor = {v.source.value: v.to_dict() for v in verdicts}
    for v in verdicts:
        if (
            not math.isfinite(v.severity)
            or not math.isfinite(v.confidence)
            or v.details.get("error") == "non_finite_signal"
        ):
            return FusedDiagnosis(t, DiagFault.UNKNOWN, 1.0, 1.0, per_sensor)

    available = [v for v in verdicts if v.available and v.fault_type != DiagFault.UNKNOWN]
    if not available:
        return FusedDiagnosis(t, DiagFault.UNKNOWN, 0.0, 0.0, per_sensor)

    faults: dict[DiagFault, dict] = {}
    healthy_votes = healthy_weight = 0.0
    for v in available:
        if v.fault_type == DiagFault.HEALTHY:
            healthy_votes += v.confidence
            healthy_weight += 1.0
            continue
        w = WEIGHTS[v.source][_domain(v.fault_type)]
        e = faults.setdefault(v.fault_type, {"vote": 0.0, "severity": 0.0, "sources": []})
        e["vote"] += w * v.confidence
        e["severity"] = max(e["severity"], v.severity)
        e["sources"].append(v.source.value)

    ranked = sorted(faults.items(), key=lambda kv: kv[1]["vote"], reverse=True)
    secondary = [{"fault_type": f.value, "confidence": round(min(1.0, e["vote"]), 4),
                  "severity": round(e["severity"], 4), "sources": e["sources"]} for f, e in ranked]
    if ranked:
        top, e = ranked[0]
        conf = min(1.0, e["vote"])
        if conf >= MIN_CONFIDENCE:
            return FusedDiagnosis(t, top, conf, e["severity"], per_sensor, secondary[1:])
    conf = healthy_votes / healthy_weight if healthy_weight else 0.5
    return FusedDiagnosis(t, DiagFault.HEALTHY, conf, 0.0, per_sensor, secondary)
