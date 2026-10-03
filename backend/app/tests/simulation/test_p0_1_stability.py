from __future__ import annotations

import asyncio
import json
import math

import numpy as np
import pytest

from app.diagnostics.schema import DiagFault
from app.simulation.params import DEFAULT_MOTOR, MotorParams, validate_motor_params
from app.supervisory.sada import SadaState
from app.tests._harness import make, run


def test_default_motor_passes_validation():
    ok, msg = validate_motor_params(DEFAULT_MOTOR)
    assert ok is True, f"DEFAULT_MOTOR failed validation: {msg}"


@pytest.mark.parametrize(
    "name, override_dict",
    [
        ("Ls=Lr=1mH, Lm=0.99mH", {"Ls": 1e-3, "Lr": 1e-3, "Lm": 0.99e-3}),
        ("Rs=500", {"Rs": 500.0}),
        ("J=1e-6", {"J": 1e-6}),
        ("Lm=0.178038, Ls=Lr=0.178039", {"Ls": 0.178039, "Lr": 0.178039, "Lm": 0.178038}),
        ("rated_voltage=1", {"rated_voltage": 1.0}),
    ],
)
def test_validate_motor_params_rejects_unstable(name, override_dict):
    """P0-1: Direct validation rejects unstable or physically absurd parameter sets."""
    base_kwargs = {
        "Rs": DEFAULT_MOTOR.Rs,
        "Rr": DEFAULT_MOTOR.Rr,
        "Ls": DEFAULT_MOTOR.Ls,
        "Lr": DEFAULT_MOTOR.Lr,
        "Lm": DEFAULT_MOTOR.Lm,
        "J": DEFAULT_MOTOR.J,
        "pole_pairs": DEFAULT_MOTOR.pole_pairs,
        "rated_power": DEFAULT_MOTOR.rated_power,
        "rated_voltage": DEFAULT_MOTOR.rated_voltage,
        "rated_current": DEFAULT_MOTOR.rated_current,
        "rated_speed": DEFAULT_MOTOR.rated_speed,
        "rated_torque": DEFAULT_MOTOR.rated_torque,
    }
    base_kwargs.update(override_dict)
    p = MotorParams(**base_kwargs)
    ok, msg = validate_motor_params(p)
    assert ok is False, f"Expected {name} to fail validation, but it passed: {msg}"


def test_p0_1_monkeypatched_nan_triggers_trip_and_no_nan_wire(monkeypatch):
    """P0-1: A monkeypatched NaN chunk triggers a trip, alert, and no literal NaN on wire."""
    async def main():
        w = make(DEFAULT_MOTOR, load=8.0)
        # Run 1 tick healthy first
        frame0 = await w.tick()
        assert frame0["supervisory"]["state"] in ("NORMAL", "WATCH")

        # Monkeypatch plant.simulate to return a chunk with NaNs
        real_simulate = w.sim.plant.simulate

        def fake_simulate(n, load_torque, *args, **kwargs):
            chunk = real_simulate(n, load_torque, *args, **kwargs)
            chunk.omega_m[:] = float("nan")
            chunk.i_abc[:] = float("nan")
            chunk.has_nonfinite = True
            return chunk

        monkeypatch.setattr(w.sim.plant, "simulate", fake_simulate)

        # Next tick encounters NaN
        frame1 = await w.tick()
        assert frame1 is not None

        # Verify SADA enters TRIP with TRIP_SIM_NONFINITE
        assert frame1["supervisory"]["state"] == SadaState.TRIP.value
        assert frame1["supervisory"]["trip"] is True
        assert frame1["supervisory"]["reason_code"] == "TRIP_SIM_NONFINITE"
        assert frame1["diagnosis"]["fault_type"] == DiagFault.UNKNOWN.value

        # Verify frame is JSON-serializable without allow_nan=False error (no NaNs present)
        wire_json = json.dumps(frame1, allow_nan=False)
        assert "NaN" not in wire_json
        assert "Infinity" not in wire_json

        # Parse back to verify validity
        parsed = json.loads(wire_json)
        assert parsed["supervisory"]["state"] == "TRIP"

    asyncio.run(main())


def test_p0_1_random_valid_params_never_yield_nonfinite():
    """P0-1: Sweep of randomized valid-looking motor params never yields a non-finite frame."""
    async def main():
        rng = np.random.default_rng(42)
        for _ in range(5):
            rs = float(DEFAULT_MOTOR.Rs * rng.uniform(0.95, 1.05))
            rr = float(DEFAULT_MOTOR.Rr * rng.uniform(0.95, 1.05))
            ls = float(DEFAULT_MOTOR.Ls * rng.uniform(0.98, 1.02))
            lr = float(DEFAULT_MOTOR.Lr * rng.uniform(0.98, 1.02))
            lm = float(math.sqrt(ls * lr * (1.0 - rng.uniform(0.06, 0.07))))
            j = float(DEFAULT_MOTOR.J * rng.uniform(0.95, 1.1))

            p = MotorParams(
                Rs=rs,
                Rr=rr,
                Ls=ls,
                Lr=lr,
                Lm=lm,
                J=j,
                pole_pairs=2,
                rated_power=DEFAULT_MOTOR.rated_power,
                rated_voltage=DEFAULT_MOTOR.rated_voltage,
                rated_current=DEFAULT_MOTOR.rated_current,
                rated_speed=DEFAULT_MOTOR.rated_speed,
                rated_torque=DEFAULT_MOTOR.rated_torque,
            )
            ok, msg = validate_motor_params(p)
            if not ok:
                continue

            worker = make(p, load=8.0, seed=1)
            last_frame = await run(worker, seconds=0.5)
            assert last_frame is not None
            raw_json = json.dumps(last_frame, allow_nan=False)
            assert "NaN" not in raw_json

    asyncio.run(main())
