"""tests/static_analysis/test_api.py

Validates static diagnosis API endpoints:
- Auth & Role gating (operator vs viewer)
- Idempotency key handling
- Paged analyses history and detail
- Static trend calculation
- Database persistence and migration upgrade/downgrade
"""

import uuid

from alembic import command
from alembic.config import Config


def sample_payload() -> dict:
    return {
        "motor_id": 1,
        "v_a": 380.0,
        "v_b": 380.0,
        "v_c": 380.0,
        "voltage_basis": "line_line",
        "value_basis": "rms",
        "i_a": 4.7,
        "i_b": 4.7,
        "i_c": 4.7,
        "speed_rpm": 1474.0,
        "supply_freq_hz": 50.0,
        "winding_temp_c": 75.0,
    }


def test_auth_and_role_access(client, auth):
    payload = sample_payload()

    # 1. Unauthenticated -> 401
    r_unauth = client.post("/api/v1/static/diagnose", json=payload)
    assert r_unauth.status_code == 401

    # 2. Viewer role -> 403 Forbidden for running diagnosis
    r_viewer = client.post("/api/v1/static/diagnose", json=payload, headers=auth("viewer"))
    assert r_viewer.status_code == 403

    # 3. Operator role -> 200 OK
    r_operator = client.post("/api/v1/static/diagnose", json=payload, headers=auth("operator"))
    assert r_operator.status_code == 200
    data = r_operator.json()
    assert data["fault_type"] == "healthy"
    assert "health_index" in data
    assert "error_code" in data
    assert "recommendation" in data
    assert "derived" in data


def test_idempotency_and_persistence(client, auth):
    payload = sample_payload()
    idem_key = uuid.uuid4().hex
    h = {**auth("operator"), "Idempotency-Key": idem_key}

    # First call
    r1 = client.post("/api/v1/static/diagnose", json=payload, headers=h)
    assert r1.status_code == 200

    # Second call with same idempotency key
    r2 = client.post("/api/v1/static/diagnose", json=payload, headers=h)
    assert r2.status_code == 200
    assert r1.json() == r2.json()

    # Viewer can list analyses
    list_r = client.get("/api/v1/static/analyses?motor_id=1", headers=auth("viewer"))
    assert list_r.status_code == 200
    items = list_r.json()["items"]
    assert len(items) >= 1
    first_id = items[0]["id"]

    # Viewer can read specific analysis
    detail_r = client.get(f"/api/v1/static/analyses/{first_id}", headers=auth("viewer"))
    assert detail_r.status_code == 200
    detail = detail_r.json()
    assert detail["id"] == first_id
    assert detail["user"].startswith("operator")
    assert detail["result"]["fault_type"] == "healthy"


def test_static_trend_endpoint(client, auth):
    r = client.get("/api/v1/static/trend?motor_id=1", headers=auth("viewer"))
    assert r.status_code == 200
    data = r.json()
    assert data["motor_id"] == 1
    assert "is_sparse_snapshot" in data


def test_alembic_migration_roundtrip(tmp_path, monkeypatch):
    from app.config import get_settings

    db_file = tmp_path / "migration_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    get_settings.cache_clear()

    cfg = Config("alembic.ini")
    # Upgrade to head should succeed on fresh database
    command.upgrade(cfg, "head")
    # Downgrade back to 0002
    command.downgrade(cfg, "20260927_0002")
    # Upgrade back to head
    command.upgrade(cfg, "head")
    get_settings.cache_clear()
