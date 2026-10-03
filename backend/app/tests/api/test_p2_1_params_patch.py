"""tests/api/test_p2_1_params_patch.py

Verifies P2-1 audit fixes:
1. Admin PATCH /motors/{id}/params updates params_json, rated parameters,
   and writes an audit row.
2. Non-admin roles (operator, viewer) get 403 Forbidden.
3. Unstable or unphysical parameters (rejected by P0-1 validator) return 422.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import SupervisoryAction
from app.db.session import session_factory


def test_admin_patch_motor_params(client: TestClient, tokens):
    """Admin can update motor parameters; updates DB, creates audit row."""
    admin_tok = tokens["admin"]
    res = client.post(
        "/api/v1/motors",
        json={"name": "P2-1 Test Motor Admin", "base_load_nm": 8.0},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert res.status_code == 201, res.text
    motor_id = res.json()["id"]

    # Valid updated params
    valid_params = {
        "Rs": 1.45,
        "Rr": 1.40,
        "Ls": 0.178,
        "Lr": 0.178,
        "Lm": 0.172,
        "J": 0.0131,
        "pole_pairs": 2,
        "rated_power": 1500.0,
        "rated_voltage": 380.0,
        "rated_current": 4.8,
        "rated_speed": 1475.0,
        "rated_torque": 10.0,
        "t_ambient": 25.0,
        "insulation_class": "F",
        "warn_c": 110.0,
        "trip_c": 130.0,
    }

    patch_res = client.patch(
        f"/api/v1/motors/{motor_id}/params",
        json=valid_params,
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert patch_res.status_code == 200, patch_res.text
    updated = patch_res.json()
    assert updated["params_json"]["Rs"] == 1.45
    assert updated["params_json"]["rated_current"] == 4.8

    # Verify audit row created
    with session_factory()() as session:
        audit = session.scalar(
            select(SupervisoryAction).where(
                SupervisoryAction.motor_id == motor_id,
                SupervisoryAction.state == "CONFIG_UPDATE",
            )
        )
        assert audit is not None
        assert audit.actor == "admin"


def test_operator_cannot_patch_params(client: TestClient, tokens):
    """Operator receives 403 Forbidden when attempting to patch parameters."""
    admin_tok = tokens["admin"]
    op_tok = tokens["operator"]
    # Create motor as admin
    res = client.post(
        "/api/v1/motors",
        json={"name": "P2-1 Test Motor Operator", "base_load_nm": 8.0},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert res.status_code == 201
    motor_id = res.json()["id"]

    patch_res = client.patch(
        f"/api/v1/motors/{motor_id}/params",
        json={"Rs": 1.5, "Rr": 1.5, "Ls": 0.2, "Lr": 0.2, "Lm": 0.19, "J": 0.01,
              "pole_pairs": 2, "rated_power": 1500, "rated_voltage": 380,
              "rated_current": 4.7, "rated_speed": 1470, "rated_torque": 10.0},
        headers={"Authorization": f"Bearer {op_tok}"},
    )
    assert patch_res.status_code == 403


def test_unstable_params_rejected_with_422(client: TestClient, tokens):
    """Unstable parameters (e.g. tiny sigma or RK4 eigenvalue explosion) return 422."""
    admin_tok = tokens["admin"]
    # Create motor as admin
    res = client.post(
        "/api/v1/motors",
        json={"name": "P2-1 Test Motor Unstable", "base_load_nm": 8.0},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert res.status_code == 201
    motor_id = res.json()["id"]

    # Unphysical sigma (~1e-6)
    bad_params = {
        "Rs": 1.4,
        "Rr": 1.4,
        "Ls": 0.178039,
        "Lr": 0.178039,
        "Lm": 0.178038,
        "J": 0.0131,
        "pole_pairs": 2,
        "rated_power": 1500.0,
        "rated_voltage": 380.0,
        "rated_current": 4.7,
        "rated_speed": 1470.0,
        "rated_torque": 10.0,
    }
    patch_res = client.patch(
        f"/api/v1/motors/{motor_id}/params",
        json=bad_params,
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert patch_res.status_code == 422
    assert "numerical stability" in patch_res.text or "sigma" in patch_res.text or "invalid" in patch_res.text.lower()
