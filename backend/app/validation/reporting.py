"""Result files for the paper: reports/validation/<dataset>/<experiment>/{metrics.csv, table.tex,
confusion.png, *.png, meta.json}. Every meta.json records dataset name/version, split definition,
seeds, git commit and which twin channels were evaluated."""

from __future__ import annotations

import csv
import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

# Fixed, CVD-validated palette (categorical slots 1-3, sequential blue ramp) and chart ink.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
SEQ_BLUE = ["#fcfcfb", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e1e0d9"


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL, cwd=Path(__file__).parent).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def git_dirty() -> bool:
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL,
                                      cwd=Path(__file__).parent)
        return bool(out.strip())
    except Exception:  # noqa: BLE001
        return False


def _fmt(v) -> str:
    if isinstance(v, float):
        return "nan" if math.isnan(v) else f"{v:.4f}"
    return str(v)


def mean_std(rows: list[dict], keys: list[str], by: list[str]) -> list[dict]:
    """Aggregate per-seed rows into mean +/- std rows grouped by `by` columns."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(tuple(r.get(b) for b in by), []).append(r)
    out = []
    for key, rs in groups.items():
        row = dict(zip(by, key, strict=True))
        row["n_seeds"] = len(rs)
        for k in keys:
            vals = np.array([r[k] for r in rs if isinstance(r.get(k), (int, float))], dtype=float)
            vals = vals[np.isfinite(vals)]
            row[f"{k}_mean"] = float(vals.mean()) if len(vals) else float("nan")
            row[f"{k}_std"] = float(vals.std()) if len(vals) else float("nan")
        out.append(row)
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else _fmt(v) if isinstance(v, float) else v)
                        for k, v in r.items()})


def write_latex(path: Path, rows: list[dict], cols: list[str], caption: str, label: str) -> None:
    def esc(s: str) -> str:
        return str(s).replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")

    lines = [r"\begin{table}[t]", r"\centering", r"\small", r"\begin{tabular}{" + "l" * len(cols) + "}",
             r"\toprule", " & ".join(esc(c) for c in cols) + r" \\", r"\midrule"]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if c.endswith("_mean") and isinstance(v, float):
                sd = r.get(c[:-5] + "_std", float("nan"))
                cells.append(f"{v:.3f} $\\pm$ {sd:.3f}" if not math.isnan(v) else "--")
            else:
                cells.append(esc(_fmt(v)) if v != "" else "--")
        lines.append(" & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", f"\\caption{{{esc(caption)}}}", f"\\label{{{label}}}", r"\end{table}"]
    path.write_text("\n".join(lines) + "\n")


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "axes.edgecolor": INK2,
                         "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
                         "axes.grid": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})
    return plt


def confusion_png(path: Path, matrix, classes: list[str], title: str) -> None:
    from matplotlib.colors import ListedColormap

    plt = _plt()
    m = np.asarray(matrix, dtype=float)
    norm = m / np.maximum(m.sum(1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(1.1 + 0.62 * len(classes), 0.9 + 0.55 * len(classes)))
    ax.imshow(norm, cmap=ListedColormap(SEQ_BLUE), vmin=0, vmax=1)
    for i in range(len(classes)):
        for j in range(len(classes)):
            ax.text(j, i, f"{int(m[i, j])}\n{norm[i, j]:.0%}", ha="center", va="center", fontsize=7,
                    color="#ffffff" if norm[i, j] > 0.55 else INK)
    short = [c.replace("_", " ") for c in classes]
    ax.set_xticks(range(len(classes)), short, rotation=35, ha="right")
    ax.set_yticks(range(len(classes)), short)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(title, color=INK, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def lines_png(path: Path, x, series: dict[str, tuple[list, list]], xlabel: str, ylabel: str, title: str,
              hline: tuple[str, float] | None = None) -> None:
    """Up to 3 series (mean, std) vs x, direct-labelled, plus an optional reference line."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    for (name, (mu, sd)), color in zip(series.items(), SERIES, strict=False):
        mu_a, sd_a = np.asarray(mu, float), np.asarray(sd, float)
        ax.plot(x, mu_a, color=color, lw=2, marker="o", ms=4, label=name)
        ax.fill_between(x, mu_a - sd_a, mu_a + sd_a, color=color, alpha=0.15, lw=0)
    if hline:
        ax.axhline(hline[1], color=INK2, lw=1, ls="--")
        ax.text(x[-1], hline[1], f" {hline[0]}", color=INK2, va="bottom", ha="right", fontsize=8)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title, color=INK, fontsize=9)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def bars_png(path: Path, names: list[str], values: list[float], xlabel: str, title: str) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.2, 0.6 + 0.24 * len(names)))
    y = np.arange(len(names))[::-1]
    ax.barh(y, values, color=SERIES[0], height=0.7)
    ax.set_yticks(y, names, fontsize=7)
    ax.set_xlabel(xlabel)
    ax.set_title(title, color=INK, fontsize=9)
    ax.grid(axis="x", color=GRID, lw=0.6)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


class ExperimentWriter:
    def __init__(self, root: Path, dataset: str, experiment: str, meta: dict):
        self.dir = root / dataset / experiment
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = {
            "dataset": dataset, "experiment": experiment, "git_commit": git_commit(),
            "git_dirty": git_dirty(), "created_utc": datetime.now(UTC).isoformat(timespec="seconds"), **meta,
        }

    def finish(self, rows: list[dict], table_cols: list[str], caption: str, summary_rows: list[dict] | None = None):
        write_csv(self.dir / "metrics.csv", rows)
        write_latex(self.dir / "table.tex", summary_rows if summary_rows is not None else rows, table_cols, caption,
                    f"tab:{self.meta['dataset']}-{self.meta['experiment']}")
        (self.dir / "meta.json").write_text(json.dumps(self.meta, indent=2, default=str))
        print_table(f"{self.meta['dataset']} / {self.meta['experiment']}", summary_rows or rows, table_cols)
        return self.dir


def print_table(title: str, rows: list[dict], cols: list[str]) -> None:
    def cell(r, c):
        v = r.get(c, "")
        if c.endswith("_mean") and isinstance(v, float):
            return f"{v:.3f}±{r.get(c[:-5] + '_std', float('nan')):.3f}"
        return _fmt(v)

    widths = [max(len(c), *(len(cell(r, c)) for r in rows)) if rows else len(c) for c in cols]
    print(f"\n== {title}")
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=True)))
    for r in rows:
        print("  ".join(cell(r, c).ljust(w) for c, w in zip(cols, widths, strict=True)))
