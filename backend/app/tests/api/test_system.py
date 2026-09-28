"""tests/api/test_system.py — Tests for database status and MySQL password testing endpoints."""

from __future__ import annotations


def test_db_status_unauthorized(client):
    r = client.get("/api/v1/system/db-status")
    assert r.status_code == 401


def test_db_status_authenticated(client, auth):
    r = client.get("/api/v1/system/db-status", headers=auth("viewer"))
    assert r.status_code == 200
    body = r.json()
    assert "connected" in body
    assert body["connected"] is True
    assert "dialect" in body
    assert "engine" in body
    assert "tables" in body
    assert isinstance(body["tables"], list)
    assert body["latency_ms"] is not None
    assert body["latency_ms"] >= 0


def test_db_test_unauthorized(client):
    r = client.post("/api/v1/system/db-test", json={"password": "secret", "apply": False})
    assert r.status_code == 401


def test_db_test_unreachable_mysql(client, auth):
    # Testing an unreachable MySQL port should gracefully return success=False without raising a 500
    r = client.post(
        "/api/v1/system/db-test",
        json={
            "password": "wrongpassword",
            "host": "127.0.0.1",
            "port": 54321,
            "user": "dt",
            "database": "digital_twin",
            "apply": False,
        },
        headers=auth("operator"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert "Cannot reach MySQL server" in body["message"] or "failed" in body["message"].lower()
    assert body["latency_ms"] is None


def test_db_test_apply_forbidden_for_viewer(client, auth):
    # Viewer role cannot apply new credentials to runtime
    r = client.post(
        "/api/v1/system/db-test",
        json={"password": "secret", "apply": True},
        headers=auth("viewer"),
    )
    assert r.status_code == 403
