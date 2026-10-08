"""Feature tables: window-level features + recording-level metadata, built by streaming records."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.validation import features as FT
from app.validation.labels import coarse
from app.validation.preprocessing import PreprocessingError, prepare
from app.validation.records import CURRENT, VIBRATION, VOLTAGE, Record

log = logging.getLogger(__name__)
VIEWS = ("current", "vibration")


@dataclass
class FeatureTable:
    """X[view]: (n_windows, F); y/groups per window; `records` one dict per recording."""

    X: dict[str, np.ndarray]
    y: dict[str, np.ndarray]
    groups: dict[str, np.ndarray]
    records: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    axes: tuple[str, ...] = FT.VIB_AXES

    def has(self, view: str) -> bool:
        return view in self.X and len(self.X[view]) > 0

    def subset(self, view: str, labels: set[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        m = np.isin(self.y[view], list(labels))
        return self.X[view][m], self.y[view][m], self.groups[view][m]

    def record_labels(self) -> dict[str, str]:
        return {r["group"]: r["label"] for r in self.records}


def build(records: Iterable[Record], axes: tuple[str, ...] = FT.VIB_AXES, nan_policy: str = "interpolate",
          views: tuple[str, ...] = VIEWS) -> FeatureTable:
    Xs: dict[str, list] = {v: [] for v in views}
    ys: dict[str, list] = {v: [] for v in views}
    gs: dict[str, list] = {v: [] for v in views}
    recs, skipped = [], []
    for rec in records:
        try:
            p = prepare(rec, nan_policy)
        except PreprocessingError as exc:
            skipped.append({"recording": rec.group_key, "reason": str(exc)})
            continue
        lab = coarse(rec.label)
        info = {
            "group": rec.group_key, "label": lab, "fine_label": rec.label, "raw_label": rec.raw_label,
            "motor_group": rec.motor_group, "load_pct": rec.load_pct, "severity": rec.severity,
            "supply_freq_hz": round(p.supply_freq_hz, 3), "slip": p.slip, "slip_source": p.slip_source,
            "nan_samples": p.nan_samples, "signals": sorted(rec.signals), "dataset": rec.dataset,
            "source_file": rec.source_file, "meta": {k: v for k, v in rec.meta.items() if _jsonable(v)},
        }
        for v in views:
            X = FT.compute(p, v, axes)
            if len(X):
                Xs[v].append(X)
                ys[v] += [lab] * len(X)
                gs[v] += [rec.group_key] * len(X)
        recs.append(info)
        rec.signals.clear()  # free memory: tables keep features only
    return FeatureTable(
        X={v: np.vstack(Xs[v]) if Xs[v] else np.zeros((0, len(FT.feature_names(v, axes)))) for v in views},
        y={v: np.array(ys[v], dtype=object) for v in views},
        groups={v: np.array(gs[v], dtype=object) for v in views},
        records=_dedupe(recs), skipped=skipped, axes=axes,
    )


def _dedupe(recs: list[dict]) -> list[dict]:
    """Bruinsma segments share a recording id: keep one record-level entry per group."""
    seen, out = set(), []
    for r in recs:
        if r["group"] not in seen:
            seen.add(r["group"])
            out.append(r)
    return out


def _jsonable(v) -> bool:
    try:
        json.dumps(v)
        return True
    except TypeError:
        return False


def save(t: FeatureTable, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {
        "records": np.array(json.dumps(t.records)), "skipped": np.array(json.dumps(t.skipped)),
        "axes": np.array(json.dumps(list(t.axes))),
    }
    for v in t.X:
        arrays[f"X_{v}"], arrays[f"y_{v}"], arrays[f"g_{v}"] = t.X[v], t.y[v].astype(str), t.groups[v].astype(str)
    np.savez_compressed(path, **arrays)  # type: ignore[arg-type]


def load(path: Path) -> FeatureTable:
    z = np.load(path, allow_pickle=False)
    views = [k[2:] for k in z.files if k.startswith("X_")]
    return FeatureTable(
        X={v: z[f"X_{v}"] for v in views}, y={v: z[f"y_{v}"].astype(object) for v in views},
        groups={v: z[f"g_{v}"].astype(object) for v in views}, records=json.loads(str(z["records"])),
        skipped=json.loads(str(z["skipped"])), axes=tuple(json.loads(str(z["axes"]))),
    )


def cache_key(obj: dict) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ---- which twin channels can be evaluated on a dataset ---------------------------------------

def channel_report(table: FeatureTable) -> dict[str, str]:
    """Explicit evaluability of the twin's four diagnostic channels on this data (never silent)."""
    sigs = set().union(*[set(r["signals"]) for r in table.records]) if table.records else set()
    has_i = set(CURRENT) <= sigs or "ia" in sigs
    has_v = set(VOLTAGE) <= sigs
    has_vib = bool(set(VIBRATION) & sigs)
    has_speed = any(r["slip_source"].startswith("speed") for r in table.records)
    rep = {}
    if has_i and has_v and has_speed:
        rep["electrical_residual"] = "evaluated (measured current, voltage and speed)"
    elif has_i and has_v:
        rep["electrical_residual"] = ("approximate: no speed signal -- speed derived from the slip estimated from "
                                      "the current spectrum; also evaluated via the MCSA current-spectrum classifier")
    elif has_i:
        rep["electrical_residual"] = ("NOT evaluable (needs measured voltage and speed); the electrical channel is "
                                      "evaluated via the MCSA current-spectrum classifier (view 'current') instead")
    else:
        rep["electrical_residual"] = "NOT evaluable (no current)"
    rep["ml_vibration_acoustic"] = (
        "evaluated on vibration features only (no acoustic channel in this dataset; the deployed 4-channel "
        "Conv-BiLSTM cannot be applied unchanged, validation classifiers use the twin's vibration feature "
        f"extractor on axes {list(table.axes)})" if has_vib else "NOT evaluable (no vibration)")
    rep["thermal"] = "NOT evaluable (no winding temperature in this dataset)"
    rep["supply"] = ("evaluated (false alarms of VUF/THD/sag checks on measured voltage)" if has_v
                     else "NOT evaluable (no voltage)")
    return rep
