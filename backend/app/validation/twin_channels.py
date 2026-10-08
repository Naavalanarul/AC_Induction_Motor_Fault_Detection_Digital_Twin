"""Run the twin's OWN diagnostic channels (not re-trained classifiers) on prepared records:
electrical residual FD, supply checks, and the twin's severity mappings."""

from __future__ import annotations

import math

import numpy as np

from app.diagnostics.calibration import brb_db_to_severity
from app.diagnostics.electrical import FD_THRESHOLD, ElectricalResidualDiagnostic
from app.diagnostics.features import FEATURE_NAMES, N_FEATURES
from app.diagnostics.ml.classifier import severity_from_features
from app.diagnostics.supply import SupplyDiagnostic
from app.simulation.params import MotorParams
from app.validation import features as FT
from app.validation.preprocessing import ELEC_FS, Prepared

CHUNK = int(0.1 * ELEC_FS)


SETTLE_VALUES = 3  # first verdicts after the observer's settle time still carry the start-up transient


def residual_fd(p: Prepared, params: MotorParams, slip: float | None = None, max_seconds: float | None = None) -> list[float]:
    """FD_norm values of the twin's residual diagnostic over a record (needs current + voltage).

    Speed: synchronous speed x (1 - slip), held constant (no encoder in the public datasets). `slip`
    defaults to the record's estimate (current spectrum or load-based guess). FD is very sensitive
    to this: on simulator data a slip error of ~0.009 raises healthy FD from ~0.017 to ~0.46.
    """
    if not ({"ia", "ib", "ic", "va", "vb", "vc"} <= set(p.elec)):
        return []
    diag = ElectricalResidualDiagnostic(params, ELEC_FS)
    f = p.supply_freq_hz
    s = slip if slip is not None else (p.slip if p.slip is not None else 0.03)
    wm = 2 * math.pi * f * (1 - s) / params.pole_pairs
    n = p.elec["ia"].shape[0] if max_seconds is None else min(p.elec["ia"].shape[0], int(max_seconds * ELEC_FS))
    i = np.vstack([p.elec[k][:n] for k in ("ia", "ib", "ic")])
    u = np.vstack([p.elec[k][:n] for k in ("va", "vb", "vc")])
    out = []
    for a in range(0, i.shape[1] - CHUNK + 1, CHUNK):
        v = diag.update(i[:, a:a + CHUNK], u[:, a:a + CHUNK], np.full(CHUNK, wm), supply_freq=f)
        if v.available and "FD_norm" in v.details:
            out.append(float(v.details["FD_norm"]))
    return out[SETTLE_VALUES:]


def sensorless_slip(p: Prepared, params: MotorParams, lo: float = 0.0005, hi: float = 0.1) -> float:
    """Slip that minimises the twin's residual (a model-based sensorless speed estimate).

    Optimistic by construction: fitting speed to the residual also absorbs part of any fault
    signature, so detection rates in this mode are an upper bound.
    """
    from scipy.optimize import minimize_scalar

    def cost(s):
        v = residual_fd(p, params, slip=float(s), max_seconds=3.0)
        return float(np.mean(v)) if v else 1e9

    res = minimize_scalar(cost, bounds=(lo, hi), method="bounded", options={"xatol": 2e-4, "maxiter": 25})
    return float(res.x)


def supply_flags(p: Prepared, rated_phase_peak: float) -> list[bool]:
    """Per 0.1 s chunk: does the twin's supply check flag an anomaly (VUF > 2 %, THD > 8 %, sag)?"""
    if not ({"va", "vb", "vc"} <= set(p.elec)):
        return []
    sd = SupplyDiagnostic(rated_phase_peak)
    u = np.vstack([p.elec[k] for k in ("va", "vb", "vc")])
    flags = []
    for a in range(0, u.shape[1] - CHUNK + 1, CHUNK):
        v = sd.analyze(u[:, a:a + CHUNK], ELEC_FS, p.supply_freq_hz)
        if v.available:
            flags.append(v.fault_type.value == "supply_anomaly")
    return flags


def twin_severity(label: str, current_row: np.ndarray | None, vib_row: np.ndarray | None,
                  axes: tuple[str, ...]) -> tuple[float | None, str]:
    """The twin's severity score for one recording (mean features) and the mapping used."""
    if label == "broken_rotor_bar" and current_row is not None:
        names = FT.CURRENT_FEATURES
        db = max(current_row[names.index("brb_lsb_db")], current_row[names.index("brb_usb_db")])
        return brb_db_to_severity(float(db)), "brb_db_to_severity(max sideband dBc)"
    if label == "interturn_short" and current_row is not None:
        return float(current_row[FT.CURRENT_FEATURES.index("neg_seq_ratio")]), "negative-sequence current ratio"
    if label in ("bearing", "bearing_inner", "bearing_outer", "bearing_ball", "unbalance", "misalignment") \
            and vib_row is not None:
        # rebuild the twin's 4-channel feature layout (x, y, z, acoustic) for severity_from_features
        full = np.zeros(4 * N_FEATURES)
        for j, ax in enumerate(("vib_x", "vib_y", "vib_z")):
            if ax in axes:
                k = axes.index(ax)
                full[j * N_FEATURES:(j + 1) * N_FEATURES] = vib_row[k * N_FEATURES:(k + 1) * N_FEATURES]
        fault = "bearing_outer" if label == "bearing" else label
        return severity_from_features(fault, full), f"severity_from_features({fault})"
    return None, "no twin severity mapping for this class/data"


__all__ = ["FD_THRESHOLD", "FEATURE_NAMES", "residual_fd", "supply_flags", "twin_severity"]
