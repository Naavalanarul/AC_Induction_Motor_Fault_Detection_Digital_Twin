"""simulation/presets.py — Standard 5-motor fleet preset for industrial digital twin demonstration.

Derivation Procedure:
---------------------
Motors are designed from physical nameplate ratings using standard IEEE/IEC per-unit scaling laws:
1. Base electrical values:
   - V_phase = rated_voltage / sqrt(3)
   - Z_base  = V_phase / rated_current
   - L_base  = Z_base / (2 * pi * f_supply) with f_supply = 50.0 Hz
2. Per-unit parameters calibrated to typical industrial TEFC Class F squirrel-cage motors:
   - Magnetizing inductance: x_m = 2.5 p.u. -> Im = 0.40 * I_rated (typical 30% - 40% range)
   - Stator & rotor leakage: x_ls = 0.05 p.u., x_lr = 0.05 p.u. -> sigma approx 0.039 - 0.06
   - Stator & rotor resistance: r_s = 0.035 * (1500 / P_rated)^0.1 p.u., r_r = 0.030 * (1500 / P_rated)^0.1 p.u.
3. Dimensional parameters:
   - Lm = x_m * L_base
   - Ls = Lm + x_ls * L_base
   - Lr = Lm + x_lr * L_base
   - Rs = r_s * Z_base
   - Rr = r_r * Z_base
4. Thermal scaling:
   - Full-load rated losses: P_loss = 1.5 * (Rs + Rr) * I_rated^2 + 0.025 * P_rated
   - Thermal resistance R_th = 80.0 K / P_loss (yielding nominal 80 K temperature rise above ambient at full load)
   - Class F insulation limits: warn = 120 °C, trip = 145 °C (IEC 60034-1)
"""

from __future__ import annotations

import dataclasses

from app.simulation.params import DEFAULT_MOTOR, MotorParams

PRESET_MOTORS: list[dict] = [
    {
        "name": "New Install — Line 3 Pump",
        "base_load_nm": 8.0,
        "params": dataclasses.asdict(DEFAULT_MOTOR),
        "fault": {
            "fault_type": "bearing_outer",
            "severity": 0.35,
            "params": {},
        },
    },
    {
        "name": "Aging Belt Drive — Bay 2",
        "base_load_nm": 28.0,
        "params": dataclasses.asdict(MotorParams(
            Rs=0.5865,
            Rr=0.5027,
            Ls=0.15485,
            Lr=0.15485,
            Lm=0.15182,
            J=0.065,
            pole_pairs=2,
            rated_power=5500.0,
            rated_voltage=380.0,
            rated_current=11.5,
            rated_speed=1460.0,
            rated_torque=36.0,
            t_ambient=25.0,
            insulation_class="F",
            warn_c=120.0,
            trip_c=145.0,
        )),
        "fault": {
            "fault_type": "bearing_outer",
            "severity": 0.25,
            "params": {},
        },
    },
    {
        "name": "Conveyor Motor — Line 7",
        "base_load_nm": 55.0,
        "params": dataclasses.asdict(MotorParams(
            Rs=0.2861,
            Rr=0.2453,
            Ls=0.08095,
            Lr=0.08095,
            Lm=0.07936,
            J=0.18,
            pole_pairs=2,
            rated_power=11000.0,
            rated_voltage=380.0,
            rated_current=22.0,
            rated_speed=1465.0,
            rated_torque=71.7,
            t_ambient=25.0,
            insulation_class="F",
            warn_c=120.0,
            trip_c=145.0,
        )),
        "fault": {
            "fault_type": "misalignment",
            "severity": 0.45,
            "params": {},
        },
    },
    {
        "name": "Compressor Motor — Utility",
        "base_load_nm": 180.0,
        "params": dataclasses.asdict(MotorParams(
            Rs=0.0785,
            Rr=0.0673,
            Ls=0.02508,
            Lr=0.02508,
            Lm=0.02459,
            J=0.85,
            pole_pairs=2,
            rated_power=37000.0,
            rated_voltage=380.0,
            rated_current=71.0,
            rated_speed=1475.0,
            rated_torque=239.5,
            t_ambient=25.0,
            insulation_class="F",
            warn_c=120.0,
            trip_c=145.0,
        )),
        "fault": {
            "fault_type": "broken_rotor_bar",
            "severity": 0.65,
            "params": {"count": 4},
        },
    },
    {
        "name": "Legacy Fan Motor — Roof Unit",
        "base_load_nm": 380.0,
        "params": dataclasses.asdict(MotorParams(
            Rs=0.0366,
            Rr=0.0314,
            Ls=0.01254,
            Lr=0.01254,
            Lm=0.01229,
            J=2.4,
            pole_pairs=2,
            rated_power=75000.0,
            rated_voltage=380.0,
            rated_current=142.0,
            rated_speed=1480.0,
            rated_torque=483.9,
            t_ambient=25.0,
            insulation_class="F",
            warn_c=120.0,
            trip_c=145.0,
        )),
        "fault": {
            "fault_type": "interturn_short",
            "severity": 0.88,
            "params": {"phase": "a"},
        },
    },
]
