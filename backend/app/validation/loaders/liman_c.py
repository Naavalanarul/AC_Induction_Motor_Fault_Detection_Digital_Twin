"""LIMAN-C: Three-phase induction-motor current measurements under multiple fault and load
conditions. Mendeley Data, doi 10.17632/kccmrf3864.1, licence CC BY 4.0.

Verified from the publisher's metadata (search snapshot 2026-10; re-check before use):
  * current only; 480 three-phase parent recordings = 1 440 phase-specific CSV files;
  * 16 384 samples per phase file over ~4 s (effective fs ~= 4 096 Hz);
  * four condition groups, EACH FROM A DIFFERENT SOURCE MOTOR: healthy (128), rotor-bar defect
    (136), bearing defect (139), inter-turn short (77). Do not build same-motor healthy/fault
    pairs: a classifier can learn the motor instead of the fault. Splits are grouped by
    recording and the motor confound is reported (leave-one-group-out is degenerate here because
    every group holds exactly one class);
  * nominal load 0/20/40/60/80/100 %; the inter-turn group only 60/80/100 %.
Assumed (checked at load time, overridable with --manifest):
  * the path/file naming encodes condition, load and phase; parsed by `parse_path`. Empty cells
    are kept as NaN and handled explicitly by the pre-processing (never zero-filled).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from app.validation.labels import LIMAN_C, map_label, normalise_token
from app.validation.loaders.base import (
    DatasetInfo,
    DatasetLoader,
    DatasetUnavailable,
    read_manifest,
    read_numeric_csv,
)
from app.validation.records import Record

N_SAMPLES = 16_384
DURATION_S = 4.0
LOADS = {0, 20, 40, 60, 80, 100}


def parse_path(rel: Path) -> tuple[str, float, str, str]:
    """Return (condition_token, load_pct, phase 'a'|'b'|'c', parent_id) from a relative path."""
    parts = [p for p in rel.with_suffix("").parts]
    tokens = [t for part in parts for t in re.split(r"[_\-\s.]+", part) if t]
    cond = None
    for size in (3, 2, 1):  # longest multi-token label first, e.g. "rotor_bar_defect"
        for i in range(len(tokens) - size + 1):
            cand = "".join(tokens[i:i + size])
            if normalise_token(cand) in LIMAN_C:
                cond = cand
                break
        if cond:
            break
    load = None
    for t in tokens:
        m = re.fullmatch(r"(?:load|l)?(\d{1,3})(?:pct|%|load)?", t.lower())
        if m and int(m.group(1)) in LOADS:
            load = float(m.group(1))
    phase = None
    m = re.search(r"(?:^|[_\-\s])(?:phase|ph|i)?([abc]|[123])$", parts[-1].lower())
    if m:
        phase = {"1": "a", "2": "b", "3": "c"}.get(m.group(1), m.group(1))
    if cond is None or load is None or phase is None:
        raise ValueError(f"condition={cond}, load={load}, phase={phase}")
    parent = re.sub(r"(?:[_\-\s])(?:phase|ph|i)?([abc]|[123])$", "", str(rel.with_suffix("")), flags=re.I)
    return cond, load, phase, parent


class LimanCLoader(DatasetLoader):
    info = DatasetInfo(
        name="liman_c",
        title="LIMAN-C: Three-Phase Induction-Motor Current Measurements under Multiple Fault and Load Conditions",
        source="https://data.mendeley.com/datasets/kccmrf3864/1",
        licence="CC BY 4.0",
        version="1",
        signals=("ia", "ib", "ic"),
        notes="Current only. Each class from a different motor -> motor/class confound.",
        verified=("current only", "1440 phase CSVs / 480 recordings", "16384 samples ~4 s", "4 motor groups", "load levels"),
        assumed=("file naming (condition/load/phase tokens)", "single value column per file"),
        citation="Khizhik, Ali, Ryzhikov, Derkach (LIMAN LLC / HSE), Mendeley Data, doi:10.17632/kccmrf3864.1",
    )

    def _index(self) -> dict[str, dict]:
        groups: dict[str, dict] = defaultdict(lambda: {"files": {}})
        if self.options.manifest:
            for row in read_manifest(self.options.manifest):
                try:
                    g = groups[row["recording_id"]]
                    g.update(cond=row["condition"], load=float(row["load_pct"]))
                    g["files"][row["phase"].lower()] = self.root / row["file"]
                except KeyError as exc:
                    raise DatasetUnavailable(f"liman_c manifest needs recording_id,condition,load_pct,phase,file: {exc}") from exc
            return groups
        bad = []
        for f in sorted(self.root.rglob("*.csv")):
            rel = f.relative_to(self.root)
            if any(k in rel.name.lower() for k in ("roster", "manifest", "checksum", "readme", "metadata")):
                continue
            try:
                cond, load, phase, parent = parse_path(rel)
            except ValueError as exc:
                bad.append(f"{rel}: {exc}")
                continue
            g = groups[parent]
            g.update(cond=cond, load=load)
            g["files"][phase] = f
        if bad:
            raise DatasetUnavailable(
                "liman_c: could not parse condition/load/phase from these paths -- pass --manifest "
                "(columns recording_id,condition,load_pct,phase,file):\n  " + "\n  ".join(bad[:10])
            )
        return groups

    def iter_records(self) -> Iterator[Record]:
        self.require_root()
        groups = self._index()

        def gen():
            for rid in sorted(groups):
                g = groups[rid]
                if set(g["files"]) != {"a", "b", "c"}:
                    raise DatasetUnavailable(f"liman_c {rid}: expected phase files a,b,c, found {sorted(g['files'])}")
                signals = {}
                n_nan = 0
                for ph in "abc":
                    _, data = read_numeric_csv(g["files"][ph])
                    col = data[:, -1]  # a time column, if present, comes first; the value is last
                    n_nan += int(np.isnan(col).sum())
                    signals[f"i{ph}"] = col
                n = len(signals["ia"])
                label = map_label(LIMAN_C, g["cond"], "liman_c")
                yield Record(
                    signals=signals, fs=n / DURATION_S if n else N_SAMPLES / DURATION_S, label=label,
                    load_pct=g["load"], motor_group=f"liman_{normalise_token(g['cond'])}",
                    source_file=str(g["files"]["a"].relative_to(self.root)) if g["files"]["a"].is_relative_to(self.root) else str(g["files"]["a"]),
                    raw_label=g["cond"], dataset="liman_c", recording_id=rid,
                    meta={"nan_cells": n_nan, "n_samples": n, "fs_note": "effective fs = samples / 4 s (approx.)"},
                )

        return self._capped(gen())
