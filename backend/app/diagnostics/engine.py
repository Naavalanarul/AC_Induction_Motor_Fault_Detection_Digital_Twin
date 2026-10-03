"""diagnostics/engine.py

Runs every diagnostic channel on each block of sensor frames and fuses them.
Each channel is isolated: an exception in one produces an `available=False`
verdict for that channel only, so the electrical path, thermal check and the
supervisory loop keep working if, e.g., the ML model breaks.
"""

from __future__ import annotations

import logging
import math
from collections import deque

import numpy as np

from app.diagnostics.electrical import ElectricalResidualDiagnostic, estimate_grid_frequency
from app.diagnostics.features import HOP_S, WINDOW_S, window_features
from app.diagnostics.fusion import fuse
from app.diagnostics.ml.classifier import MechanicalClassifier
from app.diagnostics.ml.dataset import SEQ_LEN
from app.diagnostics.protection import ProtectionDiagnostic
from app.diagnostics.schema import ChannelVerdict, DiagFault, DiagSource, FusedDiagnosis
from app.diagnostics.supply import SupplyDiagnostic
from app.diagnostics.thermal import ThermalDiagnostic
from app.sensors.base import SensorFrame, SensorStatus, SensorType
from app.simulation.params import INSULATION_LIMITS, MotorParams

log = logging.getLogger(__name__)


def _unavailable(source: DiagSource, reason: str) -> ChannelVerdict:
    return ChannelVerdict(source, DiagFault.UNKNOWN, 0.0, 0.0, False, {"reason": reason})


class DiagnosticEngine:
    def __init__(self, params: MotorParams, elec_fs: float, supply_freq: float = 50.0,
                 classifier: MechanicalClassifier | None = None):
        self.params = params
        self.supply_freq = supply_freq
        self.electrical = ElectricalResidualDiagnostic(params, elec_fs)
        self.classifier = classifier or MechanicalClassifier()
        insul = getattr(params, "insulation_class", "F").upper()
        limits = INSULATION_LIMITS.get(insul, INSULATION_LIMITS["F"])
        warn_c = getattr(params, "warn_c", None) or limits["warn_c"]
        trip_c = getattr(params, "trip_c", None) or limits["trip_c"]
        self.thermal = ThermalDiagnostic(warn_c=warn_c, trip_c=trip_c)
        self.supply = SupplyDiagnostic(params.rated_voltage * math.sqrt(2) / math.sqrt(3))
        self.protection = ProtectionDiagnostic(params)
        self._vib: deque[np.ndarray] = deque()
        self._ac: deque[np.ndarray] = deque()
        self._since_hop = 0.0
        self._seq: deque[np.ndarray] = deque(maxlen=SEQ_LEN)
        self.last_features: np.ndarray | None = None
        self.last: dict[DiagSource, ChannelVerdict] = {}

    @staticmethod
    def _ok(frame: SensorFrame | None) -> bool:
        return frame is not None and frame.status == SensorStatus.OK and frame.n > 0

    def _shaft_hz(self, frames) -> float | None:
        sp = frames.get(SensorType.SPEED)
        if not self._ok(sp):
            return None
        return float(np.mean(sp.data["rpm"])) / 60.0

    def _run_electrical(self, frames) -> ChannelVerdict:
        cur, volt, sp = frames.get(SensorType.CURRENT), frames.get(SensorType.VOLTAGE), frames.get(SensorType.SPEED)
        if not (self._ok(cur) and self._ok(volt) and self._ok(sp)):
            self.electrical.reset()
            return _unavailable(DiagSource.ELECTRICAL_RESIDUAL, "current/voltage/speed not available")
        i = np.vstack([cur.data[c] for c in "abc"])
        u = np.vstack([volt.data[c] for c in "abc"])
        n = i.shape[1]
        rpm = sp.data["rpm"]
        # upsample encoder speed to the current sample grid
        t_sp = sp.t0 + np.arange(len(rpm)) / sp.fs
        t_i = cur.t0 + np.arange(n) / cur.fs
        w = np.interp(t_i, t_sp, rpm) * math.pi / 30.0
        tf = frames.get(SensorType.TEMP)
        temp_c = float(tf.data["winding"][-1]) if self._ok(tf) else None
        return self.electrical.update(i, u, w, supply_freq=self.supply_freq, temp_c=temp_c)

    def _run_mechanical(self, frames, dt: float) -> ChannelVerdict | None:
        vib, ac = frames.get(SensorType.VIBRATION), frames.get(SensorType.ACOUSTIC)
        shaft = self._shaft_hz(frames)
        if not (self._ok(vib) and self._ok(ac)) or shaft is None:
            self._vib.clear()
            self._ac.clear()
            self._seq.clear()
            return _unavailable(DiagSource.ML_CLASSIFIER, "vibration/acoustic/speed not available")
        self._vib.append(np.vstack([vib.data[c] for c in "xyz"]))
        self._ac.append(ac.data["p"])
        need = int(WINDOW_S * vib.fs)
        while sum(b.shape[1] for b in self._vib) - self._vib[0].shape[1] >= need:
            self._vib.popleft()
            self._ac.popleft()
        self._since_hop += dt
        if self._since_hop + 1e-9 < HOP_S:
            return None  # keep previous verdict until next hop
        self._since_hop = 0.0
        v = np.hstack(self._vib)
        a = np.concatenate(self._ac)
        if v.shape[1] < need or shaft < 2.0:
            return _unavailable(DiagSource.ML_CLASSIFIER, "warming up / motor stopped")
        feats = window_features(v[:, -need:], a[-int(WINDOW_S * ac.fs):], vib.fs, ac.fs, shaft)
        self.last_features = feats
        self._seq.append(feats)
        if len(self._seq) < SEQ_LEN:
            return _unavailable(DiagSource.ML_CLASSIFIER, "filling sequence")
        return self.classifier.classify(np.stack(self._seq))

    def _run_thermal(self, frames, t: float) -> ChannelVerdict:
        tf = frames.get(SensorType.TEMP)
        if not self._ok(tf):
            return _unavailable(DiagSource.THERMAL, "temperature not available")
        return self.thermal.update(t, float(tf.data["winding"][-1]))

    def _run_supply(self, frames) -> ChannelVerdict:
        v = frames.get(SensorType.VOLTAGE)
        if not self._ok(v):
            return _unavailable(DiagSource.SUPPLY, "voltage not available")
        u_mat = np.vstack([v.data[c] for c in "abc"])
        f_grid = estimate_grid_frequency(u_mat, v.fs, default_freq=self.supply_freq)
        return self.supply.analyze(u_mat, v.fs, f_grid)

    def _run_protection(self, frames, t: float, dt: float) -> ChannelVerdict:
        cur = frames.get(SensorType.CURRENT)
        sp = frames.get(SensorType.SPEED)
        if not self._ok(cur):
            return _unavailable(DiagSource.PROTECTION, "current not available")
        i_abc = np.vstack([cur.data[c] for c in "abc"])
        rpm = float(np.mean(sp.data["rpm"])) if self._ok(sp) else float(self.params.rated_speed)
        return self.protection.update(t, i_abc, rpm, dt)

    def process(self, t: float, frames: dict[SensorType, SensorFrame], dt: float) -> FusedDiagnosis:
        runners = [
            (DiagSource.ELECTRICAL_RESIDUAL, lambda: self._run_electrical(frames)),
            (DiagSource.ML_CLASSIFIER, lambda: self._run_mechanical(frames, dt)),
            (DiagSource.THERMAL, lambda: self._run_thermal(frames, t)),
            (DiagSource.SUPPLY, lambda: self._run_supply(frames)),
            (DiagSource.PROTECTION, lambda: self._run_protection(frames, t, dt)),
        ]
        for source, fn in runners:
            try:
                verdict = fn()
            except Exception as exc:  # noqa: BLE001 - isolate channel failures
                log.exception("diagnostic channel %s failed", source.value)
                verdict = _unavailable(source, f"error: {type(exc).__name__}")
            if verdict is not None:
                self.last[source] = verdict
        return fuse(t, list(self.last.values()))
