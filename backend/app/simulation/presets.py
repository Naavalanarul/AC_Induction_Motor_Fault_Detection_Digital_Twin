"""simulation/presets.py — Standard 5-motor fleet preset for industrial digital twin demonstration.

Scaled from DEFAULT_MOTOR (1.5 kW) using standard induction-motor scaling laws
(higher rated power -> lower per-unit resistance and inductance, higher inertia).
"""

from __future__ import annotations

import dataclasses

from app.simulation.params import DEFAULT_MOTOR, MotorParams

PRESET_MOTORS: list[dict] = [
    {
        "name": "New Install — Line 3 Pump",
        "base_load_nm": 8.0,
        "params": dataclasses.asdict(DEFAULT_MOTOR),
        "fault": None,
    },
    {
        "name": "Aging Belt Drive — Bay 2",
        "base_load_nm": 28.0,
        "params": dataclasses.asdict(MotorParams(
            Rs=0.38,
            Rr=0.35,
            Ls=0.0485,
            Lr=0.0485,
            Lm=0.0468,
            J=0.065,
            pole_pairs=2,
            rated_power=5500.0,
            rated_voltage=380.0,
            rated_current=11.5,
            rated_speed=1460.0,
            rated_torque=36.0,
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
            Rs=0.19,
            Rr=0.17,
            Ls=0.0242,
            Lr=0.0242,
            Lm=0.0233,
            J=0.18,
            pole_pairs=2,
            rated_power=11000.0,
            rated_voltage=380.0,
            rated_current=22.0,
            rated_speed=1465.0,
            rated_torque=72.0,
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
            Rs=0.055,
            Rr=0.048,
            Ls=0.0072,
            Lr=0.0072,
            Lm=0.00695,
            J=0.85,
            pole_pairs=2,
            rated_power=37000.0,
            rated_voltage=380.0,
            rated_current=71.0,
            rated_speed=1475.0,
            rated_torque=240.0,
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
            Rs=0.025,
            Rr=0.022,
            Ls=0.0035,
            Lr=0.0035,
            Lm=0.00338,
            J=2.4,
            pole_pairs=2,
            rated_power=75000.0,
            rated_voltage=380.0,
            rated_current=142.0,
            rated_speed=1480.0,
            rated_torque=484.0,
        )),
        "fault": {
            "fault_type": "interturn_short",
            "severity": 0.88,
            "params": {"phase": "a"},
        },
    },
]
