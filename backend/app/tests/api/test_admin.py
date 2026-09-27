"""tests/api/test_admin.py — Admin route tests."""


def test_admin_seed_presets_endpoint_rbac(client, auth):
    """Assert POST /api/v1/admin/seed-presets requires admin role and operates idempotently."""
    # Viewer role -> 403 Forbidden
    resp = client.post("/api/v1/admin/seed-presets", headers=auth("viewer"))
    assert resp.status_code == 403

    # Operator role -> 403 Forbidden
    resp_op = client.post("/api/v1/admin/seed-presets", headers=auth("operator"))
    assert resp_op.status_code == 403

    # Admin role -> 200 OK
    resp_admin = client.post("/api/v1/admin/seed-presets", headers=auth("admin"))
    assert resp_admin.status_code == 200
    data = resp_admin.json()
    assert "created" in data
    assert "skipped" in data

    # Second call as admin -> idempotent
    resp_admin2 = client.post("/api/v1/admin/seed-presets", headers=auth("admin"))
    assert resp_admin2.status_code == 200
    data2 = resp_admin2.json()
    assert len(data2["created"]) == 0
    assert len(data2["skipped"]) == 5
