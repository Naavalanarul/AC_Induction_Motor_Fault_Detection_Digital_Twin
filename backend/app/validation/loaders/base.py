"""Loader interface, shared helpers and the dataset error type.

A loader never fabricates data: missing files, unknown labels, unexpected columns or an
unparseable naming scheme raise DatasetUnavailable with a message that says what to fix
(usually: pass --manifest or --column-map). The CLI turns that into a clean non-zero exit.
"""

from __future__ import annotations

import csv
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.validation.records import Record


class DatasetUnavailable(RuntimeError):
    """The dataset cannot be loaded as-is (missing, login-gated, unexpected format, ...)."""


@dataclass
class DatasetInfo:
    name: str
    title: str
    source: str
    licence: str
    version: str
    signals: tuple[str, ...]
    notes: str
    # Which details were verified from the publisher's metadata vs. assumed (checked at load time).
    verified: tuple[str, ...] = ()
    assumed: tuple[str, ...] = ()
    citation: str = ""


@dataclass
class LoaderOptions:
    manifest: Path | None = None           # CSV that overrides filename parsing
    column_map: dict[str, str] = field(default_factory=dict)  # canonical -> dataset column/field
    max_records: int | None = None         # for quick smoke runs; recorded in result metadata
    filename_regex: str | None = None      # override the default naming pattern


class DatasetLoader(ABC):
    info: DatasetInfo

    def __init__(self, root: Path | str, options: LoaderOptions | None = None):
        self.root = Path(root)
        self.options = options or LoaderOptions()

    def require_root(self) -> None:
        if not self.root.exists():
            raise DatasetUnavailable(
                f"{self.info.name}: data directory {self.root} does not exist. Download the dataset "
                f"({self.info.source}) and place it there -- see docs/validation.md. "
                "Synthetic data is never substituted."
            )

    @abstractmethod
    def iter_records(self) -> Iterator[Record]:
        """Yield records one at a time (datasets can be tens of GB; never hold them all)."""

    def load(self) -> list[Record]:
        return list(self.iter_records())

    def _capped(self, it: Iterator[Record]) -> Iterator[Record]:
        n = self.options.max_records
        count = 0
        for rec in it:
            if n is not None and count >= n:
                return
            count += 1
            yield rec
        if count == 0:
            raise DatasetUnavailable(f"{self.info.name}: no recordings found under {self.root}")


# ---- helpers ---------------------------------------------------------------------------------

def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise DatasetUnavailable(f"manifest {path} not found")
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise DatasetUnavailable(f"manifest {path} is empty")
    return rows


def load_column_map(spec: str | None) -> dict[str, str]:
    """`--column-map` accepts inline JSON or a path to a JSON file."""
    if not spec:
        return {}
    p = Path(spec)
    text = p.read_text() if p.exists() else spec
    try:
        m = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DatasetUnavailable(f"--column-map is not valid JSON: {exc}") from exc
    if not isinstance(m, dict):
        raise DatasetUnavailable("--column-map must be a JSON object {canonical_name: column}")
    return {str(k): str(v) for k, v in m.items()}


def read_numeric_csv(path: Path, delimiter: str | None = None) -> tuple[list[str] | None, np.ndarray]:
    """Read a numeric CSV, keeping empty cells as NaN (never dropped, never zero-filled).

    numpy.genfromtxt skips blank lines, which silently shortens a single-column signal that has an
    empty cell; this reader keeps every row. Returns (header or None, 2-D float array [rows, cols]).
    """
    lines = path.read_text().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()  # trailing newline(s) only
    if not lines:
        raise DatasetUnavailable(f"{path}: empty file")
    first = lines[0]
    if delimiter is None:
        delimiter = ";" if first.count(";") > first.count(",") else ("\t" if "\t" in first and "," not in first else ",")
    cells = [c.strip().strip('"') for c in first.split(delimiter)]
    has_header = any(c and not _is_number(c) for c in cells)
    body = lines[1:] if has_header else lines
    n_cols = len(cells)
    data = np.full((len(body), n_cols), np.nan)
    for r, line in enumerate(body):
        for c, cell in enumerate(line.split(delimiter)[:n_cols]):
            cell = cell.strip().strip('"')
            if cell and cell.lower() not in ("nan", "na"):
                try:
                    data[r, c] = float(cell)
                except ValueError as exc:
                    raise DatasetUnavailable(f"{path}:{r + 1 + has_header}: non-numeric cell {cell!r}") from exc
    return (cells if has_header else None), data


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def find_one(patterns: list[str], header: list[str]) -> int | None:
    """Index of the single header matching any regex in `patterns` (case-insensitive)."""
    hits = [i for i, h in enumerate(header) if any(re.search(p, h, re.I) for p in patterns)]
    return hits[0] if len(hits) == 1 else None
