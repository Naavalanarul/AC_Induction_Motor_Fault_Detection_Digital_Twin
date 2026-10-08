"""Treml, Flauzino, Suetake, Maciejewski (2020), "Experimental database for detecting and diagnosing
rotor broken bar in a three-phase induction motor", IEEE DataPort, doi 10.21227/fmnm-bn95
(University of Sao Paulo, Sao Carlos). Download needs a (free) IEEE DataPort login; open access.

Verified from the publisher's page / the MathWorks example that uses it (search snapshot 2026-10):
  * .zip of .mat files named struct_<cond>_R1.mat with cond in rs (healthy), r1b..r4b (1-4
    adjacent broken bars); 10 repetitions per condition;
  * loads 0.5..4.0 N*m (torque05..torque40 -> 12.5..100 % of 4 N*m);
  * electrical fields Ia Ib Ic Va Vb Vc sampled at 50 kHz; vibration fields Vib_acpi (radial,
    drive side), Vib_carc, Vib_acpe, Vib_axial, Vib_base sampled at 7.6 kHz (different lengths).
Assumed (validated at load time):
  * the exact struct nesting -- the loader walks the .mat tree and takes every node that carries
    Ia/Ib/Ic, reading the torque level and repetition index from the path;
  * twin axis mapping: vib_y <- Vib_acpi (radial, load side), vib_x <- Vib_carc, vib_z <- Vib_axial
    (override with --column-map).
Note: a user comment on the DataPort page reports that the healthy torque05 experiment 9 has
noise-only currents; records whose current RMS is below 5 % of the median are flagged in meta.
MATLAB v7.3 (HDF5) files need h5py, which is not a dependency: the loader stops with a message.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import numpy as np

from app.validation.labels import USP_BRB, USP_BRB_SEVERITY, map_label
from app.validation.loaders.base import DatasetInfo, DatasetLoader, DatasetUnavailable
from app.validation.records import Record

FS_ELEC = 50_000.0
FS_VIB = 7_600.0
FULL_LOAD_NM = 4.0
ELEC = {"ia": "Ia", "ib": "Ib", "ic": "Ic", "va": "Va", "vb": "Vb", "vc": "Vc"}
VIB_DEFAULT = {"vib_y": "Vib_acpi", "vib_x": "Vib_carc", "vib_z": "Vib_axial"}


def _walk(node, path=()):
    """Yield (path, mapping) for every struct-like node exposing fields."""
    names = getattr(getattr(node, "dtype", None), "names", None)
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            if not k.startswith("__"):
                yield from _walk(v, path + (k,))
    elif names:
        for idx in np.ndindex(node.shape):
            item = node[idx]
            mapping = {n: item[n] for n in names}
            p = path + (str(idx[-1] if idx else 0),)
            yield p, mapping
            for k, v in mapping.items():
                yield from _walk(v, p + (k,))
    elif isinstance(node, np.ndarray) and node.dtype == object:
        for idx in np.ndindex(node.shape):
            yield from _walk(node[idx], path + (str(idx[-1] if idx else 0),))


def _arr(v) -> np.ndarray:
    a = np.asarray(v)
    while a.dtype == object and a.size == 1:
        a = np.asarray(a.item())
    return np.asarray(a, dtype=np.float64).ravel()


class UspBrbLoader(DatasetLoader):
    info = DatasetInfo(
        name="usp_brb",
        title="Experimental database for detecting and diagnosing rotor broken bar in a three-phase induction motor",
        source="https://ieee-dataport.org/open-access/experimental-database-detecting-and-diagnosing-rotor-broken-bar-three-phase-induction",
        licence="IEEE DataPort open access (login required); verify terms on the page",
        version="2020-09-16",
        signals=("ia", "ib", "ic", "va", "vb", "vc", "vib_x", "vib_y", "vib_z"),
        notes="0-4 adjacent broken bars, 8 load levels, 10 repetitions; grid-fed 60 Hz assumed (Brazil) -- estimated from data.",
        verified=("struct_<cond>_R1.mat names", "fields Ia..Vc, Vib_*", "fs 50 kHz / 7.6 kHz", "torque05..40"),
        assumed=("struct nesting", "vibration axis mapping"),
        citation="Treml et al., IEEE DataPort (2020), doi:10.21227/fmnm-bn95",
    )

    def iter_records(self) -> Iterator[Record]:
        self.require_root()
        try:
            from scipy.io import loadmat
        except ImportError as exc:  # pragma: no cover - scipy is a hard dependency
            raise DatasetUnavailable("scipy is required to read .mat files") from exc
        files = sorted(self.root.rglob("struct_*.mat"))
        if not files:
            raise DatasetUnavailable(f"usp_brb: no struct_*.mat files under {self.root} (download needs an IEEE DataPort login)")
        vib_map = {k: self.options.column_map.get(k, v) for k, v in VIB_DEFAULT.items()}

        def gen():
            for f in files:
                m = re.match(r"struct_(rs|r[1-4]b)_", f.name, re.I)
                if not m:
                    raise DatasetUnavailable(f"usp_brb: unexpected file name {f.name}")
                cond = m.group(1).lower()
                try:
                    mat = loadmat(f, squeeze_me=False, struct_as_record=True)
                except NotImplementedError as exc:
                    raise DatasetUnavailable(f"usp_brb {f.name}: MATLAB v7.3 file; install h5py and convert") from exc
                found = 0
                rows = []
                for path, node in _walk(mat):
                    if not all(k in node for k in ("Ia", "Ib", "Ic")):
                        continue
                    torque_tok = next((p for p in path if re.fullmatch(r"torque\d{2}", str(p), re.I)), None)
                    if torque_tok is None:
                        raise DatasetUnavailable(f"usp_brb {f.name}: cannot find torqueXX level in path {path}")
                    torque = int(torque_tok[-2:]) / 10.0
                    rep = path[-1] if path and str(path[-1]).isdigit() else str(found)
                    signals = {canon: _arr(node[field]) for canon, field in ELEC.items() if field in node}
                    for canon, field in vib_map.items():
                        if field in node:
                            signals[canon] = _arr(node[field])
                    rows.append((torque, rep, signals))
                    found += 1
                if not found:
                    raise DatasetUnavailable(f"usp_brb {f.name}: no node with fields Ia/Ib/Ic -- unexpected .mat layout")
                med = np.median([np.sqrt(np.nanmean(s["ia"] ** 2)) for _, _, s in rows])
                for torque, rep, signals in rows:
                    rid = f"{cond}_t{int(torque * 10):02d}_rep{rep}"
                    i_rms = float(np.sqrt(np.nanmean(signals["ia"] ** 2)))
                    yield Record(
                        signals=signals, fs=FS_ELEC, label=map_label(USP_BRB, cond, "usp_brb"),
                        load_pct=100.0 * torque / FULL_LOAD_NM, motor_group=f"usp_{cond}",
                        source_file=f"{f.name}:{rid}", severity=USP_BRB_SEVERITY[cond], raw_label=cond,
                        dataset="usp_brb", recording_id=rid,
                        fs_by_signal={k: FS_VIB for k in vib_map},
                        meta={"torque_nm": torque, "current_noise_only": i_rms < 0.05 * med, "vib_axis_map": vib_map},
                    )

        return self._capped(gen())
