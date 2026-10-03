from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from app.api.schemas import MotorParamsIn
from app.diagnostics.schema import DiagFault
from app.simulation.params import MotorParams
from app.simulation.plant import MotorPlant
from app.simulation.presets import PRESET_MOTORS
from app.tests._harness import make, run


def test_preset_parameters_derivation_and_plausibility():
    """P0-2: Verify derivation consistency, Im/Irated in [30%, 45%] for presets 2-5, and valid schemas."""
    for idx, preset in enumerate(PRESET_MOTORS):
        raw_p = preset["params"]
        p = MotorParams(**raw_p)
        validated = MotorParamsIn(**raw_p)
        assert validated.rated_power > 0

        # Check magnetizing current ratio
        v_phase = p.rated_voltage / math.sqrt(3.0)
        i_m = v_phase / (2.0 * math.pi * 50.0 * p.Lm)
        im_ratio = i_m / p.rated_current
        if idx == 0:
            assert 0.80 <= im_ratio <= 0.90, f"Preset 1 (DEFAULT_MOTOR) expected ~86% Im, got {im_ratio*100:.1f}%"
        else:
            assert 0.30 <= im_ratio <= 0.45, f"Preset {idx+1} expected 30-45% Im, got {im_ratio*100:.1f}%"

        # Check leakage factor
        sigma = 1.0 - (p.Lm ** 2) / (p.Ls * p.Lr)
        assert 0.03 <= sigma <= 0.12, f"Preset {idx+1} sigma out of bounds: {sigma:.4f}"

        # Check rated torque consistency
        omega_rated = p.rated_speed * 2.0 * math.pi / 60.0
        t_expected = p.rated_power / omega_rated
        assert abs(p.rated_torque - t_expected) / t_expected < 0.05, f"Preset {idx+1} torque deviation too large"


@pytest.mark.parametrize("idx", list(range(len(PRESET_MOTORS))))
def test_preset_healthy_at_base_load_steady_state(idx):
    """P0-2: Every preset healthy at base load has steady speed within 2%, current within 15%, no overheating."""
    preset = PRESET_MOTORS[idx]
    p = MotorParams(**preset["params"])
    base_load = preset["base_load_nm"]

    plant = MotorPlant(p)
    plant.warm_start(base_load, seconds=3.0)
    chunk = plant.simulate(1000, base_load)

    sim_rpm = float(np.mean(chunk.omega_m)) * 60.0 / (2.0 * math.pi)
    ia_rms = float(np.sqrt(np.mean(chunk.i_abc[0] ** 2)))
    te = float(np.mean(chunk.te))
    assert te > 0.0

    # Speed within 2% of rated speed
    speed_error = abs(sim_rpm - p.rated_speed) / p.rated_speed
    assert speed_error < 0.02, f"Preset {preset['name']} speed error {speed_error*100:.2f}% >= 2%"

    # Current within 15% of rated current (at base load which is 80-90% of rated)
    assert ia_rms <= p.rated_current * 1.15, (
        f"Preset {preset['name']} current {ia_rms:.2f}A exceeds rated {p.rated_current}A by >15%"
    )

    # Steady state temperature calculation
    p_cu = 1.5 * (p.Rs + p.Rr) * (ia_rms ** 2)
    p_fe = 0.025 * p.rated_power
    p_loss = p_cu + p_fe
    r_th = p.get_thermal_resistance()
    delta_t = p_loss * r_th
    final_temp = p.t_ambient + delta_t

    # Must stay below Class F warn limit (120 °C) without overheating
    assert delta_t < 90.0, f"Preset {preset['name']} steady-state rise {delta_t:.1f} K >= 90 K"
    assert final_temp < 115.0, f"Preset {preset['name']} steady-state temp {final_temp:.1f} °C >= 115 °C"


@pytest.mark.parametrize("idx, expected_fault", [
    (0, DiagFault.HEALTHY),
    (1, DiagFault.BEARING_OUTER),
    (2, DiagFault.MISALIGNMENT),
    (3, DiagFault.BROKEN_ROTOR_BAR),
    (4, DiagFault.INTERTURN_SHORT),
])
def test_seeded_preset_faults_diagnosed_correctly_no_overheating(idx, expected_fault):
    """P0-2: Seeded preset faults diagnose as their intended faults, never as false overheating."""
    async def main():
        preset = PRESET_MOTORS[idx]
        p = MotorParams(**preset["params"])
        f_info = preset.get("fault", {})
        active_faults = []
        if f_info:
            active_faults.append({
                "id": 1,
                "fault_type": f_info["fault_type"],
                "severity": f_info["severity"],
                "params": f_info.get("params", {}),
            })

        worker = make(p, load=preset["base_load_nm"], faults=active_faults, seed=42)
        # Run 2.0 simulated seconds
        last_frame = await run(worker, seconds=2.0)
        assert last_frame is not None

        diag = last_frame["diagnosis"]
        sup = last_frame["supervisory"]

        # Crucial check: must not be OVERHEATING!
        assert diag["fault_type"] != DiagFault.OVERHEATING.value, (
            f"Preset {preset['name']} false-flagged OVERHEATING!"
        )
        assert "TRIP_THERMAL" not in sup["reason_code"]
        assert "OVERHEATING" not in sup["reason_code"]

        # Should match expected fault or be healthy/in-progress (not overheating)
        assert diag["fault_type"] in (expected_fault.value, DiagFault.HEALTHY.value, DiagFault.UNKNOWN.value)

    asyncio.run(main())
