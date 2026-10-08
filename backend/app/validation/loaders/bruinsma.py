"""Bruinsma et al. (2024), "Motor current and vibration monitoring dataset for various faults in an
E-motor-driven centrifugal pump", Data in Brief 52, 109987. Data: NLN-EMP on 4TU.ResearchData
(doi 10.4121/2b61183e-c14f-4131-829b-cc4822c369d0), licence CC0.

Verified from the publisher's metadata (search snapshot 2026-10; re-check the landing page):
  * 20 kHz sampling for all channels; 2 rigs ("Motor 2", "Motor 4"), one at three speeds;
  * electrical: 6 channels per measurement -- channels 1-3 phase currents [A], 4-6 phase voltages [V],
    measured after the variable-frequency drive; CSV files split in 15 s columns;
  * vibration: 5 single-axis accelerometers [g]; CSV files split in 12 s columns (240 000 rows);
  * one folder per measurement; the base name encodes measurement method, motor number, speed,
    fault and severity, and each file is that base name followed by the channel number.
Assumed (checked at load time, overridable):
  * the exact token spelling of the base name -- parsed by `parse_measurement_name`; when that is
    ambiguous the loader stops and asks for a manifest (--manifest) instead of guessing;
  * which accelerometer is the twin's x/y/z axis -- default channels 1/2/3, override with
    --column-map '{"vib_x": "3", "vib_y": "1", "vib_z": "2"}'.
The speed in the name is the VFD SETPOINT, not a measured speed: it is kept as
`speed_setpoint_rpm` and never used as an encoder value (slip is estimated from the current).
Vibration and electrical files are separate acquisitions (different column lengths): they are
paired by measurement condition and segment index and are NOT time-synchronous.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.validation.labels import BRUINSMA, HEALTHY, map_label, normalise_token
from app.validation.loaders.base import DatasetInfo, DatasetLoader, DatasetUnavailable, read_manifest
from app.validation.records import Record

FS = 20_000.0
G = 9.80665
VIB_TOKENS = {"vib", "vibration", "vibrations", "acc", "accel", "acceleration"}
ELEC_TOKENS = {"cur", "curr", "current", "currents", "elec", "electric", "electrical", "mcsa", "cv", "iv", "emc"}


@dataclass(frozen=True)
class Measurement:
    method: str        # "vibration" | "electrical"
    motor: str
    speed_rpm: float | None
    fault: str         # raw fault token(s)
    severity: float

    @property
    def condition(self) -> tuple:
        return (self.motor, self.speed_rpm, normalise_token(self.fault), self.severity)


def parse_measurement_name(name: str) -> Measurement:
    """Parse a measurement base name into its parts. Raises ValueError when ambiguous."""
    tokens = [t for t in re.split(r"[_\-\s.]+", name) if t]
    method = motor = None
    speed = None
    severity = None
    rest: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in VIB_TOKENS:
            method = "vibration"
        elif low in ELEC_TOKENS:
            method = "electrical"
        elif m := re.fullmatch(r"(?:m|motor|em|emp)(\d)", low):
            motor = f"motor{m.group(1)}"
        elif m := re.fullmatch(r"(\d{3,4})(?:rpm)?", low):
            speed = float(m.group(1))
        elif m := re.fullmatch(r"(?:s|sev|severity|l|lvl|level)(\d+)", low):
            severity = float(m.group(1))
        else:
            rest.append(tok)
    if method is None or motor is None or not rest:
        raise ValueError(f"cannot parse measurement name {name!r} (method={method}, motor={motor}, fault={rest})")
    fault = "".join(rest)
    if severity is None:
        severity = 0.0 if map_label(BRUINSMA, fault, "bruinsma") == HEALTHY else 1.0
    return Measurement(method, motor, speed, fault, severity)


class BruinsmaLoader(DatasetLoader):
    info = DatasetInfo(
        name="bruinsma",
        title="NLN-EMP: Motor current and vibration monitoring dataset, E-motor-driven centrifugal pump",
        source="https://data.4tu.nl/datasets/2b61183e-c14f-4131-829b-cc4822c369d0",
        licence="CC0 1.0 (per the dataset's citation file; verify on the landing page)",
        version="v4 (2024-08-05) expected; the folder name is recorded as found",
        signals=("ia", "ib", "ic", "va", "vb", "vc", "vib_x", "vib_y", "vib_z"),
        notes="VFD-fed pumps; no speed or temperature channel; vibration not synchronous with current.",
        verified=("fs=20 kHz", "elec ch1-3 current, ch4-6 voltage", "vib 5 ch in g", "2 rigs", "CSV columns 12/15 s"),
        assumed=("measurement-name token spelling", "accelerometer -> x/y/z mapping"),
        citation="Bruinsma, Geertsma, Loendersloot, Tinga, Data in Brief 52 (2024) 109987, doi:10.1016/j.dib.2023.109987",
    )

    def _measurement_folders(self) -> list[tuple[Path, Measurement]]:
        out = []
        if self.options.manifest:
            for row in read_manifest(self.options.manifest):
                try:
                    m = Measurement(row["method"], row["motor"],
                                    float(row["speed_rpm"]) if row.get("speed_rpm") else None,
                                    row["fault"], float(row.get("severity") or 0.0))
                except KeyError as exc:
                    raise DatasetUnavailable(f"bruinsma manifest needs columns folder,method,motor,speed_rpm,fault,severity: {exc}") from exc
                out.append((self.root / row["folder"], m))
            return out
        dirs = sorted({p.parent for p in self.root.rglob("*.csv")})
        bad = []
        for d in dirs:
            try:
                out.append((d, parse_measurement_name(d.name)))
            except (ValueError, KeyError) as exc:
                bad.append(f"{d.name}: {exc}")
        if bad:
            raise DatasetUnavailable(
                "bruinsma: could not parse these measurement folder names -- write a manifest CSV "
                "(columns folder,method,motor,speed_rpm,fault,severity) and pass --manifest:\n  " + "\n  ".join(bad[:10])
            )
        return out

    @staticmethod
    def _channel_files(folder: Path) -> dict[int, Path]:
        files = {}
        for f in folder.glob("*.csv"):
            m = re.search(r"(\d+)$", f.stem)
            if m:
                files[int(m.group(1))] = f
        return files

    @staticmethod
    def _read_column(path: Path, col: int) -> np.ndarray:
        data = np.genfromtxt(path, delimiter=",", usecols=(col,), dtype=np.float64,
                             missing_values=("", "nan", "NaN"), filling_values=np.nan)
        return np.atleast_1d(data)

    @staticmethod
    def _n_columns(path: Path) -> int:
        with path.open() as fh:
            return len(fh.readline().split(","))

    def iter_records(self) -> Iterator[Record]:
        self.require_root()
        by_condition: dict[tuple, dict[str, tuple[Path, Measurement]]] = defaultdict(dict)
        for folder, m in self._measurement_folders():
            by_condition[m.condition][m.method] = (folder, m)
        vib_map = {k: int(self.options.column_map.get(k, d)) for k, d in (("vib_x", "1"), ("vib_y", "2"), ("vib_z", "3"))}

        def gen():
            for cond in sorted(by_condition, key=str):
                parts = by_condition[cond]
                any_m = next(iter(parts.values()))[1]
                label = map_label(BRUINSMA, any_m.fault, "bruinsma")
                files = {method: self._channel_files(folder) for method, (folder, _) in parts.items()}
                n_seg = min(self._n_columns(next(iter(f.values()))) for f in files.values() if f)
                for seg in range(n_seg):
                    signals: dict[str, np.ndarray] = {}
                    elec = files.get("electrical", {})
                    if elec:
                        missing = [c for c in range(1, 7) if c not in elec]
                        if missing:
                            raise DatasetUnavailable(f"bruinsma {parts['electrical'][0]}: missing channels {missing}")
                        for i, name in enumerate(("ia", "ib", "ic", "va", "vb", "vc"), start=1):
                            signals[name] = self._read_column(elec[i], seg)
                    vib = files.get("vibration", {})
                    for name, ch in vib_map.items():
                        if ch in vib:
                            signals[name] = self._read_column(vib[ch], seg) * G  # g -> m/s^2
                    rec_id = f"{any_m.motor}_{any_m.speed_rpm}_{normalise_token(any_m.fault)}_s{any_m.severity:g}"
                    yield Record(
                        signals=signals, fs=FS, label=label, load_pct=None, motor_group=any_m.motor,
                        source_file=f"{rec_id}#seg{seg}", severity=any_m.severity if label != HEALTHY else 0.0,
                        raw_label=any_m.fault, dataset="bruinsma", recording_id=rec_id,
                        meta={"speed_setpoint_rpm": any_m.speed_rpm, "segment": seg, "vib_axis_map": vib_map,
                              "synchronous": False, "supply": "VFD"},
                    )

        return self._capped(gen())
