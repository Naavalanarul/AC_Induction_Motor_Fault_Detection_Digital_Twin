"""Mapping of dataset labels onto the twin's DiagFault labels.

Where a dataset class has no twin equivalent (loose foot, soft foot, cavitation, impeller damage,
coupling degradation, bent shaft) it is mapped to OUT_OF_SCOPE and only used for the
healthy-vs-anomaly decision. Where the bearing location is not specified (LIMAN-C "bearing",
ESTOGU "bearing ring") the coarse label BEARING is used and evaluation for that class happens at
the coarse level (any of the twin's bearing_inner/outer/ball predictions counts).
"""

from __future__ import annotations

from app.diagnostics.schema import DiagFault

OUT_OF_SCOPE = "out_of_scope"
BEARING = "bearing"
HEALTHY = DiagFault.HEALTHY.value

BEARING_FINE = {DiagFault.BEARING_INNER.value, DiagFault.BEARING_OUTER.value, DiagFault.BEARING_BALL.value}

# Labels the twin can actually produce (its fault vocabulary), coarse-grained for evaluation.
TWIN_LABELS = {
    HEALTHY,
    DiagFault.BROKEN_ROTOR_BAR.value,
    DiagFault.INTERTURN_SHORT.value,
    DiagFault.ECCENTRICITY.value,
    BEARING,
    DiagFault.UNBALANCE.value,
    DiagFault.MISALIGNMENT.value,
}


def coarse(label: str) -> str:
    """Collapse the twin's fine bearing labels onto BEARING (the common evaluation granularity)."""
    return BEARING if label in BEARING_FINE else label


def is_anomaly(label: str) -> bool:
    return label != HEALTHY


# ---- per-dataset tables -------------------------------------------------------------------
# Keys are normalised (lower case, no separators) tokens as they appear in the dataset.

LIMAN_C = {
    "healthy": HEALTHY, "normal": HEALTHY, "reference": HEALTHY,
    "rotorbar": DiagFault.BROKEN_ROTOR_BAR.value, "brokenrotorbar": DiagFault.BROKEN_ROTOR_BAR.value,
    "rotorbardefect": DiagFault.BROKEN_ROTOR_BAR.value, "rbd": DiagFault.BROKEN_ROTOR_BAR.value,
    "bearing": BEARING, "bearingdefect": BEARING,
    "interturn": DiagFault.INTERTURN_SHORT.value, "interturnshortcircuit": DiagFault.INTERTURN_SHORT.value,
    "itsc": DiagFault.INTERTURN_SHORT.value,
}

ESTOGU = {
    "n": HEALTHY,
    "bb": DiagFault.BEARING_BALL.value,   # bearing ball defect
    "br": BEARING,                         # bearing ring defect: inner vs outer not specified
    "rb3": DiagFault.BROKEN_ROTOR_BAR.value,
    "rb5": DiagFault.BROKEN_ROTOR_BAR.value,
    "sw": DiagFault.INTERTURN_SHORT.value,  # shorted (stator) winding
}
ESTOGU_SEVERITY = {"rb3": 3.0, "rb5": 5.0}  # severity = number of broken bars

BRUINSMA = {
    "healthy": HEALTHY, "baseline": HEALTHY, "normal": HEALTHY, "ref": HEALTHY,
    "bearing": BEARING, "bearingdefect": BEARING,
    "bearinginner": DiagFault.BEARING_INNER.value, "innerrace": DiagFault.BEARING_INNER.value,
    "bearingouter": DiagFault.BEARING_OUTER.value, "outerrace": DiagFault.BEARING_OUTER.value,
    "bearingball": DiagFault.BEARING_BALL.value,
    "statorshort": DiagFault.INTERTURN_SHORT.value, "statorwindingshort": DiagFault.INTERTURN_SHORT.value,
    "shortcircuit": DiagFault.INTERTURN_SHORT.value, "winding": DiagFault.INTERTURN_SHORT.value,
    "brokenrotorbar": DiagFault.BROKEN_ROTOR_BAR.value, "rotorbar": DiagFault.BROKEN_ROTOR_BAR.value,
    "brb": DiagFault.BROKEN_ROTOR_BAR.value,
    "misalignment": DiagFault.MISALIGNMENT.value, "misalign": DiagFault.MISALIGNMENT.value,
    "unbalance": DiagFault.UNBALANCE.value, "imbalance": DiagFault.UNBALANCE.value,
    # no twin equivalent -> anomaly-only evaluation
    "loosefoot": OUT_OF_SCOPE, "softfoot": OUT_OF_SCOPE, "impeller": OUT_OF_SCOPE,
    "impellerdamage": OUT_OF_SCOPE, "cavitation": OUT_OF_SCOPE, "coupling": OUT_OF_SCOPE,
    "couplingdegradation": OUT_OF_SCOPE, "bentshaft": OUT_OF_SCOPE,
}

USP_BRB = {f"r{k}b": DiagFault.BROKEN_ROTOR_BAR.value for k in range(1, 5)} | {"rs": HEALTHY}
USP_BRB_SEVERITY = {"rs": 0.0} | {f"r{k}b": float(k) for k in range(1, 5)}


def normalise_token(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def map_label(table: dict[str, str], raw: str, dataset: str) -> str:
    key = normalise_token(raw)
    if key in table:
        return table[key]
    raise KeyError(
        f"{dataset}: unknown class label {raw!r}. Add it to app/validation/labels.py "
        f"(map to a DiagFault value, '{BEARING}', or '{OUT_OF_SCOPE}') -- labels are never guessed."
    )
