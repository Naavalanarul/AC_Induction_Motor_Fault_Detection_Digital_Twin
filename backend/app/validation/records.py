"""Common record schema shared by every loader and by the simulator-backed generator."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Canonical signal names. Loaders map their native channel names onto these.
CURRENT = ("ia", "ib", "ic")
VOLTAGE = ("va", "vb", "vc")
VIBRATION = ("vib_x", "vib_y", "vib_z")
SPEED = "speed"


@dataclass
class Record:
    """One recording (never a window): the unit of grouping for every split.

    signals: canonical name -> 1-D array. Missing channels are simply absent.
    fs: sampling frequency [Hz] of the signals, unless overridden per signal in `fs_by_signal`
        (e.g. the USP set samples vibration and electrical channels at different rates).
    label: the twin's DiagFault value, "bearing" (bearing fault of unspecified race/element),
        or "out_of_scope" (no twin equivalent; healthy-vs-anomaly evaluation only).
    motor_group: physical motor / rig identifier. LIMAN-C draws every class from a different
        motor, so splits must be grouped on this, never on windows.
    """

    signals: dict[str, np.ndarray]
    fs: float
    label: str
    load_pct: float | None
    motor_group: str
    source_file: str
    severity: float | None = None
    raw_label: str = ""
    dataset: str = ""
    recording_id: str = ""
    supply_freq_hz: float | None = None
    fs_by_signal: dict[str, float] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def fs_of(self, name: str) -> float:
        return self.fs_by_signal.get(name, self.fs)

    def has(self, *names: str) -> bool:
        return all(n in self.signals for n in names)

    @property
    def group_key(self) -> str:
        """Key used for grouped splitting: the recording itself (windows never leave it)."""
        return f"{self.dataset}:{self.recording_id or self.source_file}"
