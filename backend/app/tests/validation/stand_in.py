"""Tiny stand-in files in each dataset's on-disk format, for tests only.

These are NOT the real datasets and are never used outside the test suite: they let the loaders,
splits and protocols be exercised end to end without committing (or downloading) real data.
Signals come from the twin's simulator so classes are separable.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.validation.preprocessing import resample
from app.validation.simdata import SimConfig, simulate_record

CFG = SimConfig(seconds=3.0)


def _sim(label, seed, sev=0.7, load=80.0, cfg=CFG):
    return simulate_record(label, sev, load, seed, cfg)


def write_bruinsma(root: Path, runs: dict[str, int], seconds: float = 3.0) -> None:
    """VIB_/CUR_ folders per measurement; one CSV per channel; each column one segment."""
    seed = 0
    for fault, n in runs.items():
        for k in range(n):
            seed += 1
            rec = _sim("healthy" if fault == "healthy" else {"bearing": "bearing", "brb": "broken_rotor_bar",
                                                                "misalignment": "misalignment"}[fault], seed,
                       cfg=SimConfig(seconds=seconds))
            sev = 0 if fault == "healthy" else k + 1
            motor = "M2" if k % 2 == 0 else "M4"
            base = f"{motor}_{1500 + 10 * k}_{fault}_S{sev}"
            cur = root / f"CUR_{base}"
            vib = root / f"VIB_{base}"
            cur.mkdir(parents=True)
            vib.mkdir(parents=True)
            for ch, name in enumerate(("ia", "ib", "ic", "va", "vb", "vc"), start=1):
                x = resample(rec.signals[name], rec.fs, 20_000.0)
                np.savetxt(cur / f"CUR_{base}_{ch}.csv", x[:, None], delimiter=",", fmt="%.6g")
            for ch, name in enumerate(("vib_x", "vib_y", "vib_z"), start=1):
                x = resample(rec.signals[name], rec.fs_of(name), 20_000.0) / 9.80665
                np.savetxt(vib / f"VIB_{base}_{ch}.csv", x[:, None], delimiter=",", fmt="%.6g")


def write_liman_c(root: Path, per_class: int = 2, with_nan: bool = True) -> None:
    seed = 100
    for cond, label in (("healthy", "healthy"), ("rotor_bar", "broken_rotor_bar")):
        for k in range(per_class):
            seed += 1
            rec = _sim(label, seed, load=60.0, cfg=SimConfig(seconds=4.0))  # 16 384 samples at 4 096 Hz
            d = root / cond / "load_60"
            d.mkdir(parents=True, exist_ok=True)
            for ph, name in zip("abc", ("ia", "ib", "ic"), strict=True):
                x = resample(rec.signals[name], rec.fs, 4096.0)[:16_384]
                lines = [f"{v:.6g}" for v in x]
                if with_nan and k == 0 and ph == "a":
                    lines[10] = ""  # an empty cell, as in the published files
                (d / f"rec{k}_{ph}.csv").write_text("current\n" + "\n".join(lines) + "\n")


def write_estogu(root: Path) -> None:
    for i, (machine, label) in enumerate((("N", "healthy"), ("RB3", "broken_rotor_bar"), ("SW", "interturn_short"))):
        rec = _sim(label, 200 + i)
        d = root / "With_Driver" / machine
        d.mkdir(parents=True, exist_ok=True)
        n = len(rec.signals["ia"])
        t = np.arange(n) / rec.fs
        cols = [t, rec.signals["ia"], rec.signals["ib"], rec.signals["ic"],
                rec.signals["va"], rec.signals["vb"], rec.signals["vc"]]
        header = "time,Ia,Ib,Ic,Va,Vb,Vc"
        np.savetxt(d / f"{machine}100455.csv", np.column_stack(cols), delimiter=",", header=header, comments="",
                   fmt="%.6g")


def write_usp(root: Path) -> None:
    from scipy.io import savemat

    root.mkdir(parents=True, exist_ok=True)
    for i, cond in enumerate(("rs", "r2b")):
        reps = []
        for r in range(2):
            rec = _sim("healthy" if cond == "rs" else "broken_rotor_bar", 300 + 10 * i + r, sev=0.5)
            reps.append({"Ia": resample(rec.signals["ia"], rec.fs, 50_000.0)[:, None],
                         "Ib": resample(rec.signals["ib"], rec.fs, 50_000.0)[:, None],
                         "Ic": resample(rec.signals["ic"], rec.fs, 50_000.0)[:, None],
                         "Va": resample(rec.signals["va"], rec.fs, 50_000.0)[:, None],
                         "Vb": resample(rec.signals["vb"], rec.fs, 50_000.0)[:, None],
                         "Vc": resample(rec.signals["vc"], rec.fs, 50_000.0)[:, None],
                         "Vib_acpi": resample(rec.signals["vib_y"], rec.fs_of("vib_y"), 7_600.0)[:, None]})
        arr = np.empty((1, 2), dtype=object)
        for r, rep in enumerate(reps):
            arr[0, r] = rep
        savemat(root / f"struct_{cond}_R1.mat", {cond: {"torque20": arr}})
