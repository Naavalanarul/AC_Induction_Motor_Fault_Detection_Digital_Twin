from __future__ import annotations

import pytest

from app.simulation.params import DEFAULT_MOTOR


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
def test_p0_1_api_rejects_unstable_params(client, auth, name, override_dict):
    """P0-1: Each unstable or physically invalid param set must return HTTP 422 from POST /motors."""
    base_params = {
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
    base_params.update(override_dict)
    body = {"name": f"test-{name}", "params": base_params}
    resp = client.post("/api/v1/motors", json=body, headers=auth("admin"))
    assert resp.status_code == 422, f"Expected 422 for {name}, got {resp.status_code}: {resp.text}"
