"""Simulator calibration to a real motor from its HEALTHY training recordings (experiment 6).

What is fitted, and how:
  * Rs, Rr, Lls = Llr, Lm -- steady-state T-equivalent circuit fitted (log-space least squares) to
    the measured fundamental impedance Z = V1 / I1 (magnitude and phase) at each recording's
    operating point (supply frequency + slip estimated from the current). Needs measured voltage.
  * rated voltage / current / torque -- from the measured fundamentals at the highest load, so the
    simulator draws the measured current at the recorded load levels.
  * J -- not identifiable from steady-state data; scaled with rated torque (heuristic, flagged).
  * sensor noise -- current: RMS of the 1.0-2.4 kHz band after removing harmonics of f; vibration:
    healthy load-zone RMS at > 5 kHz (heuristic).
  * fault severity-to-amplitude gains -- per class with training recordings, the ratio of the real
    median fault indicator to the simulator's at nominal severity 0.6 (clipped to [0.2, 3]).
Current-only datasets (LIMAN-C) cannot fit the circuit: only noise and gains are calibrated and
the result says so.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from app.simulation.params import DEFAULT_MOTOR, MotorParams
from app.validation.preprocessing import ELEC_FS, TWIN_VIB_FS, Prepared


@dataclass
class CalibrationResult:
    params: MotorParams
    noise_current_a: float
    noise_vib: float
    severity_gain: dict[str, float] = field(default_factory=dict)
    fitted_circuit: bool = False
    impedance_rel_error_default: float | None = None
    impedance_rel_error_fitted: float | None = None
    n_recordings: int = 0
    notes: list[str] = field(default_factory=list)

    def describe(self) -> dict:
        d = dataclasses.asdict(self)
        d["params"] = dataclasses.asdict(self.params)
        return d


def phasor(x: np.ndarray, f: float, fs: float = ELEC_FS) -> complex:
    t = np.arange(len(x)) / fs
    return complex(2 * np.dot(x - np.mean(x), np.exp(-2j * math.pi * f * t)) / len(x))


def circuit_impedance(rs, rr, ll, lm, f, s):
    w = 2 * math.pi * f
    zr = rr / max(s, 1e-4) + 1j * w * ll
    zm = 1j * w * lm
    return rs + 1j * w * ll + zm * zr / (zm + zr)


def circuit_torque(rs, rr, ll, lm, f, s, v_phase_rms, pole_pairs):
    w = 2 * math.pi * f
    z = circuit_impedance(rs, rr, ll, lm, f, s)
    i1 = v_phase_rms / z
    zr = rr / max(s, 1e-4) + 1j * w * ll
    zm = 1j * w * lm
    i2 = i1 * zm / (zm + zr)
    return 3 * abs(i2) ** 2 * rr / max(s, 1e-4) / (w / pole_pairs)


def _operating_points(prep: list[Prepared]):
    pts = []
    for p in prep:
        if not {"ia", "va"} <= set(p.elec) or p.slip is None:
            continue
        n = int(2 * ELEC_FS)
        ia, va = p.elec["ia"][:n], p.elec["va"][:n]
        i_ph, v_ph = phasor(ia, p.supply_freq_hz), phasor(va, p.supply_freq_hz)
        if abs(i_ph) < 1e-6:
            continue
        pts.append((v_ph / i_ph, p.supply_freq_hz, p.slip, abs(v_ph) / math.sqrt(2), abs(i_ph) / math.sqrt(2),
                    p.record.load_pct))
    return pts


def current_noise(p: Prepared) -> float:
    x = p.elec["ia"] - np.mean(p.elec["ia"])
    n = len(x)
    spec = np.fft.rfft(x * np.hanning(n)) / (np.hanning(n).sum() / 2)
    f = np.fft.rfftfreq(n, 1 / ELEC_FS)
    band = (f > 1000) & (f < 2400)
    for k in range(1, 60):
        band &= np.abs(f - k * p.supply_freq_hz) > 3
    # amplitude-spectrum floor -> white-noise sigma (per-bin amplitude ~ 2 sigma / sqrt(n * ENBW))
    floor = float(np.median(np.abs(spec[band]))) if band.any() else 0.0
    return floor * math.sqrt(n * 1.5) / 2


def fit(prep_healthy: list[Prepared], base: MotorParams = DEFAULT_MOTOR) -> CalibrationResult:
    notes: list[str] = []
    pts = _operating_points(prep_healthy)
    noise_i = float(np.median([current_noise(p) for p in prep_healthy if "ia" in p.elec])) if prep_healthy else 0.02
    vib_noise = [float(np.std(_highpass(p.vib["vib_y"], 5000.0))) for p in prep_healthy if "vib_y" in p.vib]
    noise_v = float(np.median(vib_noise)) if vib_noise else 0.02
    if not vib_noise:
        notes.append("no vibration: vibration noise kept at the twin default")
    if len(pts) < 2:
        notes.append("equivalent circuit NOT fitted (needs >= 2 healthy recordings with voltage); "
                     "only noise levels calibrated, motor parameters left at the twin default")
        return CalibrationResult(base, noise_i, noise_v, fitted_circuit=False, n_recordings=len(prep_healthy), notes=notes)

    z_meas = np.array([pt[0] for pt in pts])
    # start from the default motor scaled to the measured impedance level
    z0 = np.array([abs(circuit_impedance(base.Rs, base.Rr, base.Ls - base.Lm, base.Lm, pt[1], pt[2])) for pt in pts])
    k = float(np.median(np.abs(z_meas) / z0))
    x0 = np.log([base.Rs * k, base.Rr * k, (base.Ls - base.Lm) * k, base.Lm * k])

    def resid(lx):
        rs, rr, ll, lm = np.exp(lx)
        zm = np.array([circuit_impedance(rs, rr, ll, lm, pt[1], pt[2]) for pt in pts])
        r = (zm - z_meas) / np.abs(z_meas)
        return np.r_[r.real, r.imag]

    def rel_err(lx):
        r = resid(lx)
        return float(np.sqrt(np.mean(r[: len(pts)] ** 2 + r[len(pts):] ** 2)))

    err0 = rel_err(np.log([base.Rs, base.Rr, base.Ls - base.Lm, base.Lm]))
    sol = least_squares(resid, x0, bounds=(x0 - np.log(50), x0 + np.log(50)))
    rs, rr, ll, lm = np.exp(sol.x)
    pp = int(prep_healthy[0].record.meta.get("pole_pairs", base.pole_pairs))
    # nameplate from the highest-load operating point
    top = max(pts, key=lambda pt: (pt[5] or 0.0))
    v_rms, i_rms, f_top, s_top, load_top = top[3], top[4], top[1], top[2], (top[5] or 100.0)
    t_top = circuit_torque(rs, rr, ll, lm, f_top, s_top, v_rms, pp)
    rated_torque = max(0.1, t_top / max(load_top / 100.0, 0.1))
    params = dataclasses.replace(
        base, Rs=rs, Rr=rr, Ls=lm + ll, Lr=lm + ll, Lm=lm, pole_pairs=pp,
        rated_voltage=v_rms * math.sqrt(3) * (50.0 / f_top), rated_current=i_rms / max(load_top / 100.0, 0.1) ** 0.5,
        rated_torque=rated_torque, J=base.J * rated_torque / base.rated_torque,
        rated_power=rated_torque * 2 * math.pi * f_top * (1 - s_top) / pp,
        rated_speed=60 * f_top * (1 - s_top) / pp,
    )
    notes.append("J scaled with rated torque (not identifiable from steady-state data)")
    if any(p.slip_source != "speed" for p in prep_healthy):
        notes.append("operating-point slip estimated from the current spectrum or load (no encoder)")
    return CalibrationResult(params, noise_i, noise_v, fitted_circuit=True, impedance_rel_error_default=err0,
                             impedance_rel_error_fitted=rel_err(sol.x), n_recordings=len(pts), notes=notes)


def _highpass(x: np.ndarray, fc: float) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, fc, btype="high", fs=TWIN_VIB_FS, output="sos")
    return sosfiltfilt(sos, x)


# ---- severity gains -------------------------------------------------------------------------

INDICATORS = {  # class -> (view, feature name)
    "broken_rotor_bar": ("current", "brb_lsb_db"),
    "interturn_short": ("current", "neg_seq_ratio"),
    "bearing": ("vibration", "vib_y.rms"),
    "unbalance": ("vibration", "vib_y.order_1x"),
    "misalignment": ("vibration", "vib_y.order_2x"),
    "eccentricity": ("current", "ecc_lsb_db"),
}


def indicator(table, label: str) -> float | None:
    from app.validation import features as FT

    if label not in INDICATORS:
        return None
    view, name = INDICATORS[label]
    if not table.has(view):
        return None
    names = FT.feature_names(view, table.axes)
    if name not in names:
        return None
    m = table.y[view] == label
    if not m.any():
        return None
    v = table.X[view][m, names.index(name)]
    v = 10 ** (v / 20) if name.endswith("_db") else v  # dB -> linear amplitude ratio
    return float(np.median(v))


def severity_gains(real_train, sim_nominal) -> dict[str, float]:
    gains = {}
    for lab in INDICATORS:
        r, s = indicator(real_train, lab), indicator(sim_nominal, lab)
        if r is not None and s is not None and s > 0:
            gains[lab] = float(np.clip(r / s, 0.2, 3.0))
    return gains
