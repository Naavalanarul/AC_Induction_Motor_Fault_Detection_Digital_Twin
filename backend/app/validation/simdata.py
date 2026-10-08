"""Simulator-backed records in the common `Record` schema.

Simulated records deliberately go through the SAME pre-processing as real ones: no encoder speed
is attached by default (real datasets have none), so slip is estimated from the current spectrum
for both. Sensor noise is added at the twin's sensor levels (current 0.02 A, voltage 0.5 V,
vibration 0.02 m/s^2) unless overridden by calibration.

Domain randomisation (experiment 7) draws, per simulated run (documented ranges):
    Rs, Rr            x U(0.8, 1.2)        Lm (magnetising)      x U(0.9, 1.1)
    leakage Ls-Lm, Lr-Lm  x U(0.8, 1.2)    J                     x U(0.7, 1.3)
    current noise     x U(0.5, 3.0)        vibration noise       x U(0.5, 3.0)
    load              U(0, 110) % of rated torque
    supply imbalance  VUF U(0, 2) %        supply frequency      the target's +/- 2 %
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

import numpy as np

from app.simulation import faults as F
from app.simulation.params import DEFAULT_MOTOR, MotorParams
from app.simulation.twin_state import MotorSimulator
from app.validation.labels import BEARING, HEALTHY
from app.validation.preprocessing import ELEC_FS
from app.validation.records import Record

# coarse evaluation label -> injectable fault(s) of the simulator
SIM_FAULTS: dict[str, list[str]] = {
    HEALTHY: [],
    "broken_rotor_bar": ["broken_rotor_bar"],
    "interturn_short": ["interturn_short"],
    "eccentricity": ["eccentricity"],
    BEARING: ["bearing_inner", "bearing_outer", "bearing_ball"],
    "bearing_inner": ["bearing_inner"],
    "bearing_outer": ["bearing_outer"],
    "bearing_ball": ["bearing_ball"],
    "unbalance": ["unbalance"],
    "misalignment": ["misalignment"],
}


@dataclass
class SimConfig:
    params: MotorParams = DEFAULT_MOTOR
    supply_freq_hz: float = 50.0
    seconds: float = 4.0
    noise_current_a: float = 0.02
    noise_voltage_v: float = 0.5
    noise_vib: float = 0.02
    severity_range: tuple[float, float] = (0.2, 1.0)
    load_range_pct: tuple[float, float] = (20.0, 100.0)
    severity_gain: dict[str, float] = field(default_factory=dict)  # calibration: injected = gain * nominal
    randomise: bool = False
    label: str = "default"

    def describe(self) -> dict:
        d = dataclasses.asdict(self)
        d["params"] = dataclasses.asdict(self.params)
        return d


def _randomised(cfg: SimConfig, rng: np.random.Generator) -> tuple[MotorParams, float, float, float, float]:
    p = cfg.params
    lm = p.Lm * rng.uniform(0.9, 1.1)
    lls, llr = (p.Ls - p.Lm) * rng.uniform(0.8, 1.2), (p.Lr - p.Lm) * rng.uniform(0.8, 1.2)
    params = dataclasses.replace(p, Rs=p.Rs * rng.uniform(0.8, 1.2), Rr=p.Rr * rng.uniform(0.8, 1.2),
                                 Lm=lm, Ls=lm + lls, Lr=lm + llr, J=p.J * rng.uniform(0.7, 1.3))
    return (params, cfg.noise_current_a * rng.uniform(0.5, 3.0), cfg.noise_vib * rng.uniform(0.5, 3.0),
            rng.uniform(0.0, 2.0), cfg.supply_freq_hz * rng.uniform(0.98, 1.02))


def simulate_record(label: str, severity: float, load_pct: float, seed: int, cfg: SimConfig,
                    fault_name: str | None = None) -> Record:
    rng = np.random.default_rng(seed)
    params, n_i, n_v = cfg.params, cfg.noise_current_a, cfg.noise_vib
    vuf_pct, f_s = 0.0, cfg.supply_freq_hz
    if cfg.randomise:
        params, n_i, n_v, vuf_pct, f_s = _randomised(cfg, rng)
        load_pct = float(rng.uniform(0.0, 110.0))
    sim = MotorSimulator(params, seed=seed, base_load_nm=params.rated_torque * load_pct / 100.0)
    sim.plant.supply_freq = f_s
    sim.plant.v_peak *= f_s / 50.0  # V/f: VFD-fed and 60 Hz supplies keep the flux constant
    sim.vib.noise_rms = n_v
    if vuf_pct > 0:
        F.inject(sim.faults, "voltage_anomaly", min(1.0, vuf_pct / 10.0), {"type": "imbalance"})
    sim.plant.warm_start(sim.state.base_load_nm, seconds=1.0)
    injected = None
    if label != HEALTHY:
        choices = SIM_FAULTS[label]
        fault_name = fault_name or choices[int(rng.integers(len(choices)))]
        injected = float(min(1.0, severity * cfg.severity_gain.get(label, 1.0)))
        params_f: dict[str, object] = {"phase": "abc"[int(rng.integers(3))]} if fault_name == "interturn_short" else {}
        if fault_name == "broken_rotor_bar":
            params_f = {"count": max(1, round(injected * 8))}
        F.inject(sim.faults, fault_name, injected, params_f)
    cur, volt, vib = [], [], []
    for _ in range(int(round(cfg.seconds / sim.chunk_s))):
        st = sim.step()
        assert st.electrical is not None
        cur.append(st.electrical.i_abc)
        volt.append(st.electrical.u_abc)
        vib.append(st.vibration)
    i = np.hstack(cur) + rng.normal(0, n_i, size=(3, sum(c.shape[1] for c in cur)))
    u = np.hstack(volt) + rng.normal(0, cfg.noise_voltage_v, size=i.shape)
    v = np.hstack(vib)
    signals = {"ia": i[0], "ib": i[1], "ic": i[2], "va": u[0], "vb": u[1], "vc": u[2],
               "vib_x": v[0], "vib_y": v[1], "vib_z": v[2]}
    rid = f"sim-{cfg.label}-{seed}"
    return Record(
        signals=signals, fs=ELEC_FS, label=fault_name if fault_name and label == BEARING else label,
        load_pct=load_pct, motor_group=f"sim-{cfg.label}" + (f"-{seed}" if cfg.randomise else ""),
        source_file=rid, severity=injected if injected is not None else 0.0, raw_label=fault_name or HEALTHY,
        dataset="sim", recording_id=rid, supply_freq_hz=f_s,
        fs_by_signal={"vib_x": sim.state.vib_fs, "vib_y": sim.state.vib_fs, "vib_z": sim.state.vib_fs},
        meta={"pole_pairs": params.pole_pairs, "nominal_severity": severity, "vuf_pct": vuf_pct,
              "randomised": cfg.randomise, "true_rpm": _rpm(st)},
    )


def _rpm(st) -> float:
    return float(np.mean(st.electrical.omega_m)) * 30 / math.pi if st.electrical is not None else float("nan")


def generate(labels: list[str], runs_per_class: int, cfg: SimConfig, seed: int = 0):
    """Yield simulated records: `runs_per_class` independent runs (= groups) per label."""
    rng = np.random.default_rng(10_000 + seed)
    for li, label in enumerate(labels):
        for r in range(runs_per_class):
            sev = float(rng.uniform(*cfg.severity_range)) if label != HEALTHY else 0.0
            load = float(rng.uniform(*cfg.load_range_pct))
            yield simulate_record(label, sev, load, seed * 1_000_003 + li * 10_007 + r, cfg)
