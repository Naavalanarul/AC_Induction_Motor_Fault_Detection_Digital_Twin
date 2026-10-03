"""runtime/worker.py — one motor's simulation + diagnostic + SADA loop.

Each chunk (0.1 s of simulated time):
    simulate -> read sensors -> diagnose/fuse -> SADA -> apply load/trip
    -> publish live frame (WebSocket fan-out) -> queue telemetry for the DB.
Commands (fault injection, overrides, sensor mode) arrive through the broker
and are applied at chunk boundaries, so the simulation state is never mutated
mid-step.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import welch

from app.core.logging import motor_id_var
from app.core.metrics import (
    DIAG_SECONDS,
    MOTOR_HEALTH_INDEX,
    SADA_TRIPS,
    SIM_LAG_SECONDS,
    SIM_TICK_SECONDS,
    SIM_TICKS,
)
from app.db.models import Alert, Diagnosis, SensorReading, SupervisoryAction
from app.diagnostics.engine import DiagnosticEngine
from app.diagnostics.features import CHANNELS, FEATURE_NAMES, N_FEATURES, scalogram
from app.diagnostics.health_index import compute_mhi, error_code
from app.diagnostics.mcsa import MCSAAnalyzer
from app.diagnostics.ml.classifier import MechanicalClassifier
from app.diagnostics.prognosis import estimate_time_to_threshold
from app.diagnostics.recommendations import get_recommendation
from app.diagnostics.rul_engine import RULEngine, RULResult
from app.diagnostics.schema import DiagFault, FusedDiagnosis
from app.runtime.broker import Broker
from app.runtime.writer import DBWriter
from app.sensors import SensorMode, SensorRegistry, SensorType
from app.sensors.base import SensorStatus
from app.simulation import faults as F
from app.simulation.params import MotorParams
from app.simulation.twin_state import MotorSimulator
from app.supervisory.sada import SadaState, SadaSupervisor

log = logging.getLogger(__name__)


@dataclass
class WorkerConfig:
    motor_id: int
    name: str
    params: MotorParams
    base_load_nm: float
    sensor_ids: dict[str, int]
    sensor_modes: dict[str, str] = field(default_factory=dict)
    active_faults: list[dict] = field(default_factory=list)  # {id, fault_type, severity, params}
    realtime_factor: float = 1.0
    stream_hz: float = 10.0
    persist_interval_s: float = 1.0
    use_ml: bool = True
    seed: int | None = 0


def _decimate(x: np.ndarray, n: int) -> list[float]:
    step = max(1, len(x) // n)
    return np.round(x[::step], 4).tolist()


def _npz(**arrays) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def sanitize_for_wire(val: object) -> object:
    if isinstance(val, float):
        return val if math.isfinite(val) else None
    if isinstance(val, (np.floating, np.integer)):
        f = float(val)
        return f if math.isfinite(f) else None
    if isinstance(val, dict):
        return {k: sanitize_for_wire(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [sanitize_for_wire(v) for v in val]
    return val


_classifier_cache: dict[bool, MechanicalClassifier] = {}


def shared_classifier(use_ml: bool) -> MechanicalClassifier:
    """The model is read-only at inference time, so all motors share one instance."""
    if use_ml not in _classifier_cache:
        _classifier_cache[use_ml] = MechanicalClassifier(use_ml=use_ml)
    return _classifier_cache[use_ml]


class MotorWorker:
    def __init__(self, cfg: WorkerConfig, broker: Broker, writer: DBWriter | None):
        self.cfg = cfg
        self.broker = broker
        self.writer = writer
        self.sim = MotorSimulator(cfg.params, seed=cfg.seed, base_load_nm=cfg.base_load_nm)
        modes = {SensorType(k): SensorMode(v) for k, v in cfg.sensor_modes.items()}
        self.registry = SensorRegistry(self.sim.state, modes, seed=cfg.seed)
        self.engine = DiagnosticEngine(cfg.params, self.sim.fs, classifier=shared_classifier(cfg.use_ml))
        self.sada = SadaSupervisor()
        self.fault_map: dict[int, int] = {}  # db fault id -> runtime fault id
        self.fault_meta: dict[int, dict] = {}
        for f in cfg.active_faults:
            self._inject(f)
        self.last_tick = time.monotonic()
        self.commands: asyncio.Queue = asyncio.Queue()
        self._chunk_idx = 0
        self._last_persist = -1e9
        self._last_fault = DiagFault.HEALTHY
        self._last_state: SadaState | None = None
        self._cur_buf: deque[np.ndarray] = deque(maxlen=20)   # 2 s of phase-a current
        self._vib_buf: deque[np.ndarray] = deque(maxlen=5)    # 0.5 s of vib-y
        self._ac_buf: deque[np.ndarray] = deque(maxlen=5)
        self._res_buf: deque[np.ndarray] = deque(maxlen=20)
        self._spectra: dict = {}
        self._scalogram: dict | None = None
        self._operator_ack = False
        self._spectra_dirty = self._scalogram_dirty = False
        self.severity_history: deque[tuple[float, float]] = deque(maxlen=120)
        self._last_mhi: float = 100.0
        self._last_error_code: str = "SYS-OK-A"
        self._last_zone: str = "A"
        self.rul_engine = RULEngine(nominal_life_hours=20000.0, shaft_speed_rpm=float(cfg.params.rated_speed or 1475.0))
        self._last_rul: RULResult | None = None

    # ------------------------------------------------------------------ commands
    def _inject(self, f: dict) -> None:
        af = F.inject(self.sim.faults, f["fault_type"], float(f["severity"]), f.get("params") or {})
        self.fault_map[int(f["id"])] = af.id
        self.fault_meta[int(f["id"])] = {"id": int(f["id"]), "fault_type": f["fault_type"],
                                         "severity": float(f["severity"]), "params": f.get("params") or {}}

    def _apply(self, cmd: dict) -> None:
        kind = cmd.get("cmd")
        if kind == "inject":
            self._inject(cmd)
        elif kind == "clear":
            rid = self.fault_map.pop(int(cmd["fault_id"]), None)
            self.fault_meta.pop(int(cmd["fault_id"]), None)
            if rid is not None:
                self.sim.faults.remove(rid)
        elif kind == "sensor_mode":
            self.registry.set_mode(SensorType(cmd["sensor_type"]), SensorMode(cmd["mode"]))
        elif kind == "base_load":
            self.sim.state.base_load_nm = float(cmd["value"])
        elif kind == "override":
            action = cmd["action"]
            ok = True
            if action == "ack":
                self.sada.acknowledge()
                self._operator_ack = True
            elif action == "reset":
                ok = self.sada.reset(forced_reason=cmd.get("force_reason"))
            elif action == "set_load":
                self.sada.set_manual_load(float(cmd["load"]))
            elif action == "release_load":
                self.sada.set_manual_load(None)
            log.info("operator override %s by %s -> %s", action, cmd.get("actor"), "ok" if ok else "refused")
        else:
            log.warning("unknown command %s", cmd)

    async def _command_listener(self) -> None:
        async with self.broker.subscribe(f"cmd:{self.cfg.motor_id}") as stream:
            async for cmd in stream:
                await self.commands.put(cmd)

    # ------------------------------------------------------------------ main loop
    async def run(self) -> None:
        motor_id_var.set(self.cfg.motor_id)
        listener = asyncio.create_task(self._command_listener())
        loop = asyncio.get_running_loop()
        wall0, sim0 = loop.time(), self.sim.state.t
        try:
            while True:
                while not self.commands.empty():
                    self._apply(self.commands.get_nowait())
                await self.tick()
                if self.cfg.realtime_factor > 0:
                    target = wall0 + (self.sim.state.t - sim0) / self.cfg.realtime_factor
                    lag = loop.time() - target
                    SIM_LAG_SECONDS.labels(str(self.cfg.motor_id)).set(max(0.0, lag))
                    if lag > 2.0:  # too far behind (e.g. after a pause): re-anchor instead of bursting
                        wall0, sim0 = loop.time(), self.sim.state.t
                    await asyncio.sleep(max(0.0, -lag))
                else:
                    await asyncio.sleep(0)
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener

    async def tick(self) -> dict:
        t0 = time.perf_counter()
        st = await asyncio.to_thread(self.sim.step)
        if st.nonfinite_fault:
            self.sada.trip("TRIP_SIM_NONFINITE")
            if self.writer is not None:
                self.writer.put(
                    Alert(
                        motor_id=self.cfg.motor_id,
                        severity="critical",
                        message="Simulation diverged to non-finite values (NaN/Inf): emergency trip TRIP_SIM_NONFINITE",
                    )
                )
        frames = await self.registry.read_all()
        SIM_TICK_SECONDS.observe(time.perf_counter() - t0)
        t1 = time.perf_counter()
        diag = await asyncio.to_thread(self.engine.process, st.t, frames, self.sim.chunk_s)
        DIAG_SECONDS.observe(time.perf_counter() - t1)
        if st.nonfinite_fault:
            diag = FusedDiagnosis(
                t=st.t,
                fault_type=DiagFault.UNKNOWN,
                confidence=1.0,
                severity=1.0,
                per_sensor_scores=diag.per_sensor_scores,
                secondary=[{"fault_type": "sim_nonfinite", "confidence": 1.0, "severity": 1.0, "sources": ["plant"]}],
                source=diag.source,
                schema_version=diag.schema_version,
            )
        # Check critical sensors
        critical_types = (SensorType.CURRENT, SensorType.VOLTAGE, SensorType.SPEED)
        critical_present = [frames[st] for st in critical_types if st in frames]
        if critical_present:
            critical_sensors_ok = all(
                getattr(f, "status", SensorStatus.OK) == SensorStatus.OK
                and getattr(f, "n", 1) > 0
                for f in critical_present
            )
        else:
            critical_sensors_ok = False if frames else True

        temp_f = frames.get(SensorType.TEMP)
        temp_val: float | None = None
        if temp_f is not None and getattr(temp_f, "status", None) == SensorStatus.OK:
            w_data = getattr(temp_f, "data", {}).get("winding")
            if w_data is not None and len(w_data) > 0:
                temp_val = float(w_data[-1])

        out = self.sada.update(
            diag,
            dt=self.sim.chunk_s,
            critical_sensors_ok=critical_sensors_ok,
            current_temp=temp_val,
        )
        if out.trip and out.reason_code == "TRIP_SENSOR_LOSS" and out.changed:
            if self.writer is not None:
                self.writer.put(
                    Alert(
                        motor_id=self.cfg.motor_id,
                        severity="critical",
                        message="Critical sensors unavailable exceeding grace period: emergency trip TRIP_SENSOR_LOSS",
                    ),
                    priority=True,
                )
        # --- SADA-trip override: don't persist "healthy" when channels are starved ---
        # After a trip, fault-sensitive channels (electrical, ML) mark themselves
        # unavailable because the motor is de-energised.  If only benign channels
        # (e.g. thermal) remain and they say HEALTHY, the fusion result is
        # misleading.  Override it to INDETERMINATE so the persisted diagnoses
        # table does not contradict the SADA panel.
        if (
            out.trip
            and diag.fault_type == DiagFault.HEALTHY
            and self.sada.fault not in (DiagFault.HEALTHY, DiagFault.UNKNOWN)
        ):
            override_meta = {
                "sada_latched_fault": self.sada.fault.value,
                "sada_latched_severity": round(out.smoothed_severity, 4),
                "reason": "channels_starved_during_trip",
                "fault_type": self.sada.fault.value,
                "confidence": round(diag.confidence, 4),
                "severity": round(out.smoothed_severity, 4),
                "sources": ["sada_latched"],
            }
            per_scores = {**diag.per_sensor_scores, "sada_override": override_meta}
            diag = FusedDiagnosis(
                t=diag.t,
                fault_type=DiagFault.INDETERMINATE,
                confidence=diag.confidence,
                severity=diag.severity,
                per_sensor_scores=per_scores,
                secondary=[override_meta] + diag.secondary,
                source=diag.source,
                schema_version=diag.schema_version,
            )
        # Rolling severity history (Phase 21)
        self.severity_history.append((st.t, out.smoothed_severity))

        # Health index & error codes (Phase 20)
        chan_statuses = {k.value: getattr(v, "status", "ok") for k, v in frames.items()}
        mhi, zone = compute_mhi(
            diag,
            out.state,
            chan_statuses,
            latched_severity=out.smoothed_severity,
        )
        err = error_code(diag.source.value, diag.fault_type.value, zone)
        self._last_mhi = mhi
        self._last_error_code = err
        self._last_zone = zone

        MOTOR_HEALTH_INDEX.labels(motor_id=str(self.cfg.motor_id), motor_name=self.cfg.name).set(mhi)

        st.load_cmd = out.load_cmd
        st.tripped = out.trip
        SIM_TICKS.labels(str(self.cfg.motor_id)).inc()
        self.last_tick = time.monotonic()
        self._chunk_idx += 1

        self._record(st, frames, diag, out, mhi, err)
        msg = self._build_message(st, frames, diag, out, mhi, err, zone)
        clean_msg = sanitize_for_wire(msg)
        assert isinstance(clean_msg, dict)
        every = max(1, round((1.0 / self.sim.chunk_s) / self.cfg.stream_hz))
        if self._chunk_idx % every == 0:
            # Spectra/scalogram change at 2 Hz / 1 Hz: send them only when updated (clients keep the
            # last ones) and encode each frame ONCE for all viewers.
            wire = dict(clean_msg)
            if not self._spectra_dirty:
                wire.pop("spectra", None)
            if not self._scalogram_dirty:
                wire.pop("scalogram", None)
            self._spectra_dirty = self._scalogram_dirty = False
            await self.broker.publish(
                f"motor:{self.cfg.motor_id}",
                json.dumps(wire, allow_nan=False, separators=(",", ":")),
            )
            await self.broker.set_latest(self.cfg.motor_id, clean_msg)
        return clean_msg

    # ------------------------------------------------------------------ persistence
    def _record(self, st, frames, diag, out, mhi: float, err: str) -> None:
        if self.writer is None:
            return
        mid = self.cfg.motor_id
        if out.changed or self._last_state is None:
            if out.trip:
                SADA_TRIPS.labels(str(mid)).inc()
            self.writer.put(
                SupervisoryAction(
                    motor_id=mid,
                    state=out.state.value,
                    load_cmd=out.load_cmd,
                    reason_code=out.reason_code,
                    trip=out.trip,
                    smoothed_severity=out.smoothed_severity,
                ),
                priority=True,
            )
            if self._last_state is not None:
                level = {"TRIP": "critical", "DERATE": "warning", "WATCH": "warning"}.get(out.state.value, "info")
                self.writer.put(
                    Alert(
                        motor_id=mid,
                        severity=level,
                        message=f"SADA {self._last_state.value} -> {out.state.value}: {out.reason_code}",
                    ),
                    priority=True,
                )
            self._last_state = out.state

        anomaly_onset = diag.fault_type not in (DiagFault.HEALTHY, DiagFault.UNKNOWN, DiagFault.INDETERMINATE) and diag.fault_type != self._last_fault
        if diag.fault_type not in (DiagFault.UNKNOWN, DiagFault.INDETERMINATE):
            self._last_fault = diag.fault_type
        if anomaly_onset:
            # Raw waveforms only on anomaly onset (too heavy to store continuously)
            vib = frames.get(SensorType.VIBRATION)
            cur = frames.get(SensorType.CURRENT)
            if vib is not None and vib.status == SensorStatus.OK and self._vib_buf:
                self.writer.put(SensorReading(
                    sensor_id=self.cfg.sensor_ids["vibration"], window_start=st.t - 0.5, window_end=st.t,
                    feature_vector_json={"event": "anomaly_onset", "fault_type": diag.fault_type.value},
                    raw_ref=_npz(y=np.concatenate(self._vib_buf).astype(np.float32), fs=vib.fs)))
            if cur is not None and cur.status == SensorStatus.OK:
                self.writer.put(SensorReading(
                    sensor_id=self.cfg.sensor_ids["current"], window_start=cur.t0, window_end=st.t,
                    feature_vector_json={"event": "anomaly_onset", "fault_type": diag.fault_type.value},
                    raw_ref=_npz(a=cur.data["a"].astype(np.float32), b=cur.data["b"].astype(np.float32),
                                 c=cur.data["c"].astype(np.float32), fs=cur.fs)))

        if st.t - self._last_persist < self.cfg.persist_interval_s:
            return
        self._last_persist = st.t
        self.writer.put(Diagnosis(motor_id=mid, fault_type=diag.fault_type.value, confidence=diag.confidence,
                                  severity_score=diag.severity, per_sensor_scores_json=diag.per_sensor_scores,
                                  health_index=mhi, error_code=err))
        for stype, feats in self._sensor_features(frames, diag).items():
            sid = self.cfg.sensor_ids.get(stype)
            if sid is not None and feats:
                self.writer.put(SensorReading(sensor_id=sid, window_start=st.t - self.cfg.persist_interval_s,
                                              window_end=st.t, feature_vector_json=feats))

    def _sensor_features(self, frames, diag) -> dict[str, dict]:
        out: dict[str, dict] = {}
        ps = diag.per_sensor_scores
        for stype, frame in frames.items():
            if frame.status != SensorStatus.OK or frame.n == 0:
                continue
            if stype in (SensorType.CURRENT, SensorType.VOLTAGE):
                d = {f"rms_{k}": round(float(np.sqrt(np.mean(v**2))), 4) for k, v in frame.data.items()}
                src = "electrical_residual" if stype == SensorType.CURRENT else "supply"
                d.update({k: v for k, v in ps.get(src, {}).get("details", {}).items() if k in ("FD", "FL", "vuf", "thd")})
                out[stype.value] = d
            elif stype == SensorType.SPEED:
                out["speed"] = {"rpm_mean": round(float(np.mean(frame.data["rpm"])), 2)}
            elif stype == SensorType.TEMP:
                out["temp"] = ps.get("thermal", {}).get("details", {}) or {"temp_c": float(frame.data["winding"][-1])}
        feats = self.engine.last_features
        if feats is not None:
            for ci, ch in enumerate(CHANNELS):
                key = "acoustic" if ch == "acoustic" else "vibration"
                block = {f"{ch}.{n}": round(float(feats[ci * N_FEATURES + j]), 5) for j, n in enumerate(FEATURE_NAMES)}
                out.setdefault(key, {}).update(block)
        return out

    # ------------------------------------------------------------------ UI payload
    def _update_spectra(self, st, frames) -> None:
        cur, vib, ac = frames.get(SensorType.CURRENT), frames.get(SensorType.VIBRATION), frames.get(SensorType.ACOUSTIC)
        if cur is not None and cur.status == SensorStatus.OK:
            self._cur_buf.append(cur.data["a"])
        if vib is not None and vib.status == SensorStatus.OK:
            self._vib_buf.append(vib.data["y"])
        if ac is not None and ac.status == SensorStatus.OK:
            self._ac_buf.append(ac.data["p"])
        res = self.engine.electrical.last_residual_abc
        if res is not None:
            self._res_buf.append(res[0])
        if self._chunk_idx % 5 == 0:
            spectra = {}
            if len(self._cur_buf) >= 10:
                x = np.concatenate(self._cur_buf)
                win = np.hanning(len(x))
                mag = np.abs(np.fft.rfft(x * win)) / (win.sum() / 2)
                f = np.fft.rfftfreq(len(x), 1 / self.sim.fs)
                m = f <= 150
                spectra["current_a"] = {"f": np.round(f[m], 2).tolist(),
                                        "db": np.round(20 * np.log10(mag[m] + 1e-6), 1).tolist()}
                try:
                    omega_m = float(np.mean(st.electrical.omega_m)) if st.electrical is not None else 154.3
                    analyzer = MCSAAnalyzer(fs=self.sim.fs, window="hann")
                    mcsa_res = analyzer.analyze(x, nominal_supply_freq=50.0, omega_m=omega_m, pole_pairs=self.cfg.params.pole_pairs)
                    spectra["mcsa"] = {
                        "fundamental_freq": mcsa_res.fundamental_freq,
                        "fundamental_mag_db": mcsa_res.fundamental_mag_db,
                        "slip": mcsa_res.slip,
                        "rotor_freq_hz": mcsa_res.rotor_freq_hz,
                        "brb_fault_detected": mcsa_res.brb_fault_detected,
                        "eccentricity_detected": mcsa_res.eccentricity_detected,
                        "worst_brb_sideband_db": mcsa_res.worst_brb_sideband_db,
                        "peaks": [
                            {
                                "freq_hz": p.freq_hz,
                                "magnitude_db": p.magnitude_db,
                                "label": p.label,
                                "harmonic_k": p.harmonic_k,
                            }
                            for p in mcsa_res.peaks
                        ],
                    }
                except Exception as exc:
                    log.debug("MCSA analysis non-fatal error: %s", exc)
            for key, buf, fs in (("vibration_y", self._vib_buf, st.vib_fs), ("acoustic", self._ac_buf, st.acoustic_fs)):
                if len(buf) >= 3:
                    f, p = welch(np.concatenate(buf), fs=fs, nperseg=512)
                    spectra[key] = {"f": np.round(f, 1).tolist(), "db": np.round(10 * np.log10(p + 1e-12), 1).tolist()}
            self._spectra = spectra
            self._spectra_dirty = True
        if self._chunk_idx % 10 == 0 and len(self._vib_buf) >= 3:
            self._scalogram = scalogram(np.concatenate(list(self._vib_buf)[-3:]), st.vib_fs, n_scales=24, max_points=128)
            self._scalogram_dirty = True

    def _build_message(self, st, frames, diag, out, mhi: float, err: str, zone: str) -> dict:
        self._update_spectra(st, frames)
        sensors = {}
        for stype, frame in frames.items():
            entry = {"status": frame.status.value, "mode": self.registry.mode_of(stype).value, "unit": frame.unit}
            if frame.status == SensorStatus.OK and frame.n:
                if stype in (SensorType.CURRENT, SensorType.VOLTAGE):
                    entry["wave"] = {k: _decimate(v, 100) for k, v in frame.data.items()}
                    entry["rms"] = {k: round(float(np.sqrt(np.mean(v**2))), 3) for k, v in frame.data.items()}
                elif stype == SensorType.VIBRATION:
                    entry["wave"] = {k: _decimate(v, 256) for k, v in frame.data.items()}
                    entry["rms"] = {k: round(float(np.sqrt(np.mean(v**2))), 4) for k, v in frame.data.items()}
                elif stype == SensorType.ACOUSTIC:
                    entry["wave"] = {"p": _decimate(frame.data["p"], 256)}
                    entry["rms"] = {"p": round(float(np.sqrt(np.mean(frame.data["p"] ** 2))), 5)}
                elif stype == SensorType.SPEED:
                    entry["value"] = round(float(np.mean(frame.data["rpm"])), 2)
                elif stype == SensorType.TEMP:
                    entry["value"] = round(float(frame.data["winding"][-1]), 2)
            sensors[stype.value] = entry
        chunk = st.electrical
        diag_dict = diag.to_dict()
        diag_dict["health_index"] = mhi
        diag_dict["error_code"] = err
        diag_dict["zone"] = zone

        thermal_lptn = None
        if getattr(st, "lptn", None) is not None:
            vib_rms = 1.0
            vib_frame = frames.get(SensorType.VIBRATION)
            if vib_frame is not None and vib_frame.status == SensorStatus.OK and "y" in vib_frame.data:
                vy = vib_frame.data["y"]
                if len(vy) > 0:
                    vib_rms = float(np.sqrt(np.mean(vy**2)))

            try:
                rul_res = self.rul_engine.compute_rul(
                    lptn_state=st.lptn,
                    vibration_rms_mms=vib_rms,
                    timestamp=st.t,
                )
                self._last_rul = rul_res
                insul_rul = rul_res.insulation.rul_hours
                bearing_rul = rul_res.bearing_de.rul_hours
                overall_rul = rul_res.overall_rul_hours
                limiting_factor = rul_res.limiting_factor
                bearing_health = rul_res.bearing_de.health_percent
                iso_zone = rul_res.bearing_de.iso_zone
            except Exception:
                insul_rul = round(st.lptn.rul_hours, 1)
                bearing_rul = 25000.0
                overall_rul = min(insul_rul, bearing_rul)
                limiting_factor = "insulation"
                bearing_health = 100.0
                iso_zone = "A"

            thermal_lptn = {
                "t_winding": round(st.lptn.t_winding, 2),
                "t_teeth": round(st.lptn.t_teeth, 2),
                "t_rotor": round(st.lptn.t_rotor, 2),
                "t_bearing": round(st.lptn.t_bearing, 2),
                "ambient": round(st.lptn.ambient, 2),
                "aging_acceleration": round(st.lptn.aging_acceleration, 3),
                "rul_hours": round(insul_rul, 1),
                "bearing_rul_hours": round(bearing_rul, 1),
                "overall_rul_hours": round(overall_rul, 1),
                "limiting_factor": limiting_factor,
                "bearing_health_percent": round(bearing_health, 1),
                "iso_zone": iso_zone,
            }

        return {
            "type": "frame",
            "motor_id": self.cfg.motor_id,
            "name": self.cfg.name,
            "t": round(st.t, 3),
            "health_index": mhi,
            "error_code": err,
            "zone": zone,
            "sensors": sensors,
            "spectra": self._spectra,
            "scalogram": self._scalogram,
            "residual": {"a": _decimate(self._res_buf[-1], 100)} if self._res_buf else None,
            "mechanics": {"torque_nm": round(float(np.mean(chunk.te)), 3),
                          "load_nm": round(float(np.mean(chunk.load_torque)), 3),
                          "rpm": round(float(np.mean(chunk.omega_m)) * 30 / math.pi, 2)},
            "thermal_lptn": thermal_lptn,
            "diagnosis": diag_dict,
            "supervisory": {**out.to_dict(), "base_load_nm": st.base_load_nm, "acknowledged": self.sada.acknowledged},
            "faults": list(self.fault_meta.values()),
            "ml_backend": self.engine.classifier.backend,
        }

    def get_prognosis(self, derate_thresh: float = 0.5, trip_thresh: float = 0.8) -> dict:
        return estimate_time_to_threshold(list(self.severity_history), derate_thresh, trip_thresh)

    def get_recommendation(self) -> dict:
        fault = self._last_fault.value if hasattr(self._last_fault, "value") else str(self._last_fault)
        return get_recommendation(self.cfg.motor_id, fault, self._last_zone, self._last_mhi)

    def get_mcsa(self) -> dict:
        if len(self._cur_buf) < 5:
            return {"status": "insufficient_data", "peaks": [], "brb_fault_detected": False}
        x = np.concatenate(self._cur_buf)
        omega_m = float(np.mean(self.sim.state.electrical.omega_m)) if self.sim.state.electrical is not None else 154.3
        analyzer = MCSAAnalyzer(fs=self.sim.fs, window="hann")
        res = analyzer.analyze(x, nominal_supply_freq=50.0, omega_m=omega_m, pole_pairs=self.cfg.params.pole_pairs)
        return {
            "status": "ok",
            "fundamental_freq": res.fundamental_freq,
            "fundamental_mag_db": res.fundamental_mag_db,
            "slip": res.slip,
            "rotor_freq_hz": res.rotor_freq_hz,
            "brb_fault_detected": res.brb_fault_detected,
            "eccentricity_detected": res.eccentricity_detected,
            "worst_brb_sideband_db": res.worst_brb_sideband_db,
            "peaks": [
                {
                    "freq_hz": p.freq_hz,
                    "magnitude_db": p.magnitude_db,
                    "label": p.label,
                    "harmonic_k": p.harmonic_k,
                    "expected_freq_hz": p.expected_freq_hz,
                    "deviation_hz": p.deviation_hz,
                }
                for p in res.peaks
            ],
            "brb_peaks": [
                {
                    "freq_hz": p.freq_hz,
                    "magnitude_db": p.magnitude_db,
                    "label": p.label,
                    "harmonic_k": p.harmonic_k,
                }
                for p in res.brb_peaks
            ],
            "ecc_peaks": [
                {
                    "freq_hz": p.freq_hz,
                    "magnitude_db": p.magnitude_db,
                    "label": p.label,
                }
                for p in res.ecc_peaks
            ],
            "freqs": np.round(res.freqs[res.freqs <= 150.0], 2).tolist(),
            "psd_db": np.round(res.psd_db[res.freqs <= 150.0], 2).tolist(),
        }

    def get_rul(self) -> dict:
        mid = self.cfg.motor_id
        if self._last_rul is not None:
            r = self._last_rul
            return {
                "motor_id": mid,
                "overall_rul_hours": r.overall_rul_hours,
                "overall_rul_years": round(r.overall_rul_hours / 8760.0, 2),
                "overall_health_percent": r.overall_health_percent,
                "limiting_factor": r.limiting_factor,
                "insulation": {
                    "winding_temp_c": r.insulation.winding_temp_c,
                    "hotspot_temp_c": r.insulation.hotspot_temp_c,
                    "aging_acceleration_factor": r.insulation.aging_acceleration_factor,
                    "nominal_life_hours": r.insulation.nominal_life_hours,
                    "rul_hours": r.insulation.rul_hours,
                    "rul_years": r.insulation.rul_years,
                    "health_percent": r.insulation.health_percent,
                    "temp_margin_c": r.insulation.temp_margin_c,
                },
                "bearing_de": {
                    "bearing_temp_c": r.bearing_de.bearing_temp_c,
                    "shaft_speed_rpm": r.bearing_de.shaft_speed_rpm,
                    "l10h_hours": r.bearing_de.l10h_hours,
                    "adjusted_l10h_hours": r.bearing_de.adjusted_l10h_hours,
                    "rul_hours": r.bearing_de.rul_hours,
                    "rul_years": r.bearing_de.rul_years,
                    "health_percent": r.bearing_de.health_percent,
                    "vibration_rms_mms": r.bearing_de.vibration_rms_mms,
                    "iso_zone": r.bearing_de.iso_zone,
                },
                "bearing_nde": {
                    "bearing_temp_c": r.bearing_nde.bearing_temp_c,
                    "shaft_speed_rpm": r.bearing_nde.shaft_speed_rpm,
                    "l10h_hours": r.bearing_nde.l10h_hours,
                    "adjusted_l10h_hours": r.bearing_nde.adjusted_l10h_hours,
                    "rul_hours": r.bearing_nde.rul_hours,
                    "rul_years": r.bearing_nde.rul_years,
                    "health_percent": r.bearing_nde.health_percent,
                    "vibration_rms_mms": r.bearing_nde.vibration_rms_mms,
                    "iso_zone": r.bearing_nde.iso_zone,
                },
            }
        return {
            "motor_id": mid,
            "overall_rul_hours": 20000.0,
            "overall_rul_years": 2.28,
            "overall_health_percent": 100.0,
            "limiting_factor": "insulation",
            "insulation": {
                "winding_temp_c": 45.0,
                "hotspot_temp_c": 50.0,
                "aging_acceleration_factor": 0.05,
                "nominal_life_hours": 20000.0,
                "rul_hours": 20000.0,
                "rul_years": 2.28,
                "health_percent": 100.0,
                "temp_margin_c": 105.0,
            },
            "bearing_de": {
                "bearing_temp_c": 35.0,
                "shaft_speed_rpm": float(self.cfg.params.rated_speed or 1475.0),
                "l10h_hours": 30000.0,
                "adjusted_l10h_hours": 30000.0,
                "rul_hours": 30000.0,
                "rul_years": 3.42,
                "health_percent": 100.0,
                "vibration_rms_mms": 0.8,
                "iso_zone": "A",
            },
            "bearing_nde": {
                "bearing_temp_c": 32.0,
                "shaft_speed_rpm": float(self.cfg.params.rated_speed or 1475.0),
                "l10h_hours": 35000.0,
                "adjusted_l10h_hours": 35000.0,
                "rul_hours": 35000.0,
                "rul_years": 4.0,
                "health_percent": 100.0,
                "vibration_rms_mms": 0.6,
                "iso_zone": "A",
            },
        }
