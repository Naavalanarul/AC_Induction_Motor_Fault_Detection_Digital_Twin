"""simulation/twin_state.py

`MotorTwinState` is the single ground-truth object updated every tick. All
simulated sensors read from it, which is what keeps signals consistent across
channels. `MotorSimulator` advances it chunk by chunk.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.simulation.faults import FaultState
from app.simulation.mechanical_signals import (
    ACOUSTIC_FS,
    VIB_FS,
    AcousticGenerator,
    ThermalModel,
    VibrationGenerator,
    interp_shaft,
)
from app.simulation.params import DEFAULT_MOTOR, MotorParams
from app.simulation.plant import MotorPlant, PlantChunk
from app.simulation.thermal_lptn import FourNodeThermalLPTN, LPTNState


@dataclass
class MotorTwinState:
    """Latest ground truth for one motor (overwritten every chunk)."""

    params: MotorParams
    faults: FaultState
    t: float = 0.0
    electrical: PlantChunk | None = None
    vibration: np.ndarray = field(default_factory=lambda: np.zeros((3, 0)))
    vib_fs: float = VIB_FS
    acoustic: np.ndarray = field(default_factory=lambda: np.zeros(0))
    acoustic_fs: float = ACOUSTIC_FS
    temperature_c: float = 25.0
    lptn: LPTNState | None = None
    load_cmd: float = 1.0          # supervisory load command (fraction of base load)
    base_load_nm: float = 8.0      # process load demand [N*m]
    tripped: bool = False


class MotorSimulator:
    """Advances plant + mechanical/acoustic/thermal generators in fixed chunks."""

    def __init__(
        self,
        params: MotorParams = DEFAULT_MOTOR,
        seed: int | None = 0,
        fs: float = 5000.0,
        chunk_s: float = 0.1,
        base_load_nm: float = 8.0,
        thermal_tau_s: float = 180.0,
    ):
        self.faults = FaultState()
        self.state = MotorTwinState(params=params, faults=self.faults, base_load_nm=base_load_nm)
        self.plant = MotorPlant(params, self.faults, fs=fs)
        self.vib = VibrationGenerator(seed=None if seed is None else seed + 1)
        self.ac = AcousticGenerator(seed=None if seed is None else seed + 2)
        self.thermal = ThermalModel(tau_s=thermal_tau_s)
        self.lptn = FourNodeThermalLPTN(t_ambient=25.0)
        self.fs = fs
        self.chunk_s = chunk_s
        self.n_elec = int(round(fs * chunk_s))
        self.n_vib = int(round(VIB_FS * chunk_s))
        self.n_ac = int(round(ACOUSTIC_FS * chunk_s))

    def step(self) -> MotorTwinState:
        st = self.state
        self.plant.voltage_scale = 0.0 if st.tripped else 1.0
        load = st.base_load_nm * st.load_cmd * (0.0 if st.tripped else 1.0)
        t0 = self.plant.t
        chunk = self.plant.simulate(self.n_elec, load)
        # Extend with the pre-chunk point so interpolation covers [t0, t0+chunk]
        t_e = np.concatenate([[t0], chunk.t])
        th_prev = st.electrical.theta_m[-1] if st.electrical is not None else 0.0
        w_prev = st.electrical.omega_m[-1] if st.electrical is not None else 0.0
        th_e = np.concatenate([[th_prev], chunk.theta_m])
        w_e = np.concatenate([[w_prev], chunk.omega_m])
        load_frac = min(1.5, max(0.0, float(np.mean(chunk.te)) / st.params.rated_torque))

        _, th_v, w_v = interp_shaft(t_e, th_e, w_e, t0, self.n_vib, VIB_FS)
        vib = self.vib.generate(th_v, w_v, chunk.supply_freq, load_frac, self.faults)
        _, th_a, w_a = interp_shaft(t_e, th_e, w_e, t0, self.n_ac, ACOUSTIC_FS)
        ac = self.ac.generate(th_a, w_a, chunk.supply_freq, load_frac, self.faults)

        # 4-Node Lumped Parameter Thermal Network (LPTN) & Arrhenius RUL calculation
        p_cu_s = 0.55 * chunk.copper_loss_w
        p_cu_r = 0.45 * chunk.copper_loss_w
        p_fe = 0.025 * st.params.rated_power if not st.tripped else 0.0
        p_fric = 0.005 * st.params.rated_power + self.faults.bearing_friction_torque * abs(float(np.mean(chunk.omega_m)))
        lptn_state = self.lptn.step(
            dt=self.chunk_s,
            p_copper_s=p_cu_s,
            p_iron=p_fe,
            p_copper_r=p_cu_r,
            p_friction=p_fric,
            itsc_extra_w=chunk.fault_heat_w,
        )
        self.thermal.step(self.chunk_s, chunk.copper_loss_w + chunk.fault_heat_w)

        st.t = self.plant.t
        st.electrical = chunk
        st.vibration = vib
        st.acoustic = ac
        st.temperature_c = lptn_state.t_winding
        st.lptn = lptn_state
        return st
