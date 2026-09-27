"""tests/api/test_prognosis_api.py — API route tests for prognosis and recommendations."""


def test_prognosis_and_recommendation_endpoints(client, auth):
    # Verify auth required
    assert client.get("/api/v1/motors/1/prognosis").status_code == 401
    assert client.get("/api/v1/motors/1/recommendation").status_code == 401

    # Viewer role can access
    r_prog = client.get("/api/v1/motors/1/prognosis", headers=auth("viewer"))
    assert r_prog.status_code == 200
    prog = r_prog.json()
    assert "current_severity" in prog
    assert "trend" in prog
    assert "sample_count" in prog

    r_rec = client.get("/api/v1/motors/1/recommendation", headers=auth("viewer"))
    assert r_rec.status_code == 200
    rec = r_rec.json()
    assert rec["motor_id"] == 1
    assert "zone" in rec
    assert "urgency" in rec
    assert "checklist" in rec

    # 404 for non-existent motor
    assert client.get("/api/v1/motors/99999/prognosis", headers=auth("viewer")).status_code == 404
    assert client.get("/api/v1/motors/99999/recommendation", headers=auth("viewer")).status_code == 404
