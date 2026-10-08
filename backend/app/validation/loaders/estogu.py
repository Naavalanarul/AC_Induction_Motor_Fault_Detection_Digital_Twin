"""ESTOGU: a multimodal motor condition monitoring dataset for fault diagnosis in electrical
machines (Eskisehir Technical University). Zenodo record 18222578.

Verified from the publisher's metadata (search snapshot 2026-10; re-check before use):
  * vibration, current and voltage measurements; six conditions N, BB (ball), BR (bearing ring),
    RB3 / RB5 (3 / 5 broken bars), SW (shorted winding); two setups With_Driver (inverter-fed,
    45-50 Hz in 0.5 Hz steps) and Without_Driver (grid, 50 Hz); one sub-folder per condition and
    a metadata folder with a setup description and an index file;
  * file names follow {MACHINE}{LOAD}{FREQ}.csv.
NOT verified (the loader checks and stops otherwise):
  * the licence -- read it on the Zenodo record before use and record it in your paper;
  * whether currents are recorded per phase, the sampling rate and the column names. Columns are
    matched by name (current/voltage/vibration keywords); if that is ambiguous pass
    --column-map '{"ia": "<col>", "ib": ..., "vib_x": ...}' and the sampling rate via
    --column-map '{"fs": "<Hz>"}' when the files carry no time column.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import numpy as np

from app.validation.labels import ESTOGU, ESTOGU_SEVERITY, map_label, normalise_token
from app.validation.loaders.base import (
    DatasetInfo,
    DatasetLoader,
    DatasetUnavailable,
    find_one,
    read_manifest,
    read_numeric_csv,
)
from app.validation.records import Record

COLUMN_PATTERNS = {
    "ia": [r"^i_?a$", r"current.*(a|1|u)$", r"^ia\b", r"phase.?a.*cur"],
    "ib": [r"^i_?b$", r"current.*(b|2|v)$", r"^ib\b", r"phase.?b.*cur"],
    "ic": [r"^i_?c$", r"current.*(c|3|w)$", r"^ic\b", r"phase.?c.*cur"],
    "va": [r"^v_?a$", r"volt.*(a|1|u)$", r"^va\b"],
    "vb": [r"^v_?b$", r"volt.*(b|2|v)$", r"^vb\b"],
    "vc": [r"^v_?c$", r"volt.*(c|3|w)$", r"^vc\b"],
    "vib_x": [r"vib.*x", r"acc.*x"],
    "vib_y": [r"vib.*y", r"acc.*y"],
    "vib_z": [r"vib.*z", r"acc.*z"],
}
DEFAULT_NAME = r"^(?P<machine>RB3|RB5|BB|BR|SW|N)[_-]?(?P<load>\d{1,3})[_-]?(?P<freq>\d{2,3}(?:[._]\d)?)$"


def parse_name(stem: str, pattern: str = DEFAULT_NAME) -> tuple[str, float, float]:
    m = re.match(pattern, stem, re.I)
    if not m:
        raise ValueError(f"name does not match {pattern!r}")
    freq_tok = m.group("freq").replace("_", ".")
    freq = float(freq_tok)
    if freq > 100:  # e.g. "455" -> 45.5 Hz
        freq = freq / 10.0
    return m.group("machine").upper(), float(m.group("load")), freq


class EstoguLoader(DatasetLoader):
    info = DatasetInfo(
        name="estogu",
        title="ESTOGU: A Multimodal Motor Condition Monitoring Dataset for Fault Diagnosis in Electrical Machines",
        source="https://zenodo.org/records/18222578",
        licence="UNVERIFIED -- check the Zenodo record before use",
        version="Zenodo record 18222578",
        signals=("ia", "ib", "ic", "va", "vb", "vc", "vib_x", "vib_y", "vib_z"),
        notes="Inverter-fed (45-50 Hz) and grid-fed (50 Hz) setups.",
        verified=("6 conditions", "With_Driver/Without_Driver", "{MACHINE}{LOAD}{FREQ}.csv"),
        assumed=("load/frequency token encoding", "column names", "sampling rate", "licence"),
    )

    def _files(self):
        if self.options.manifest:
            for row in read_manifest(self.options.manifest):
                yield (self.root / row["file"], row["machine"].upper(), float(row["load"]), float(row["freq_hz"]),
                       row.get("setup", ""))
            return
        pattern = self.options.filename_regex or DEFAULT_NAME
        bad = []
        found = []
        for f in sorted(self.root.rglob("*.csv")):
            if "metadata" in (p.lower() for p in f.relative_to(self.root).parts):
                continue
            try:
                machine, load, freq = parse_name(f.stem, pattern)
            except ValueError as exc:
                bad.append(f"{f.relative_to(self.root)}: {exc}")
                continue
            setup = next((p for p in f.parts if p.lower().startswith(("with_driver", "without_driver"))), "")
            found.append((f, machine, load, freq, setup))
        if bad:
            raise DatasetUnavailable("estogu: unparseable file names -- pass --filename-regex or --manifest:\n  "
                                     + "\n  ".join(bad[:10]))
        yield from found

    def _columns(self, header: list[str] | None, n_cols: int, path) -> dict[str, int]:
        cmap = {k: v for k, v in self.options.column_map.items() if k != "fs"}
        if cmap:
            out = {}
            for canon, col in cmap.items():
                if col.isdigit():
                    out[canon] = int(col)
                elif header and col in header:
                    out[canon] = header.index(col)
                else:
                    raise DatasetUnavailable(f"estogu {path}: column {col!r} for {canon} not found in {header}")
            return out
        if not header:
            raise DatasetUnavailable(f"estogu {path}: no header row; pass --column-map to name the {n_cols} columns")
        out = {}
        for canon, pats in COLUMN_PATTERNS.items():
            idx = find_one(pats, header)
            if idx is not None:
                out[canon] = idx
        if not {"ia", "ib", "ic"} <= set(out) and not {"ia"} <= set(out):
            raise DatasetUnavailable(f"estogu {path}: cannot identify current columns in header {header}; "
                                     "pass --column-map")
        return out

    def iter_records(self) -> Iterator[Record]:
        self.require_root()

        def gen():
            for path, machine, load, freq, setup in self._files():
                header, data = read_numeric_csv(path)
                cols = self._columns(header, data.shape[1], path)
                fs = None
                if "fs" in self.options.column_map:
                    fs = float(self.options.column_map["fs"])
                elif header:
                    t_idx = find_one([r"^time", r"^t\b", r"^t\s*\(s\)"], header)
                    if t_idx is not None:
                        dt = np.nanmedian(np.diff(data[:, t_idx]))
                        fs = 1.0 / dt if dt > 0 else None
                if not fs:
                    raise DatasetUnavailable(f"estogu {path}: sampling rate unknown (no time column); "
                                             "pass --column-map '{\"fs\": \"<Hz>\"}'")
                signals = {canon: data[:, idx] for canon, idx in cols.items()}
                tok = normalise_token(machine)
                label = map_label(ESTOGU, machine, "estogu")
                rec_id = f"{setup}/{path.stem}"
                yield Record(
                    signals=signals, fs=float(fs), label=label, load_pct=load if load <= 100 else None,
                    motor_group=f"estogu_{tok}", source_file=str(path.relative_to(self.root)),
                    severity=ESTOGU_SEVERITY.get(tok, 0.0 if tok == "n" else 1.0), raw_label=machine,
                    dataset="estogu", recording_id=rec_id, supply_freq_hz=freq,
                    meta={"setup": setup, "load_code": load, "inverter_fed": setup.lower().startswith("with_driver")},
                )

        return self._capped(gen())
