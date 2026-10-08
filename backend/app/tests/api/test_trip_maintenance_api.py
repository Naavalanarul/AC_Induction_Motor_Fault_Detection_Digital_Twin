"""End-to-end version of the bug-2 repro: inject a fault that trips the motor, then read the
endpoints the Maintenance tab uses."""

from app.tests.api.conftest import wait_for


def test_maintenance_endpoints_after_trip(client, auth):
    h = auth("operator")
    r = client.post("/api/v1/motors/1/faults", json={"fault_type": "bearing_outer", "severity": 0.9}, headers=h)
    assert r.status_code == 201
    fid = r.json()["id"]

    def tripped_state():
        st = client.get("/api/v1/motors/1", headers=h).json().get("state") or {}
        sup = st.get("supervisory") or {}
        return st if sup.get("trip") and sup.get("latched_fault") else None

    st = wait_for(tripped_state, timeout=60)
    assert st, "motor did not trip"
    latched = st["supervisory"]["latched_severity"]
    assert st["supervisory"]["latched_fault"] == "bearing_outer"

    # let the smoothed severity decay well below the latch (the original failure mode)
    assert wait_for(lambda: (client.get("/api/v1/motors/1", headers=h).json()["state"]["supervisory"]
                             ["smoothed_severity"] < 0.3), timeout=60)

    prog = client.get("/api/v1/motors/1/prognosis", headers=h).json()
    assert abs(prog["current_severity"] - latched) < 0.02, prog
    assert prog["trend"] != "decreasing"

    rec = client.get("/api/v1/motors/1/recommendation", headers=h).json()
    assert rec["fault_type"] == "bearing_outer", rec

    diag = client.get("/api/v1/motors/1", headers=h).json()["state"]["diagnosis"]
    if diag["fault_type"] != "bearing_outer":
        assert diag["fault_type"] == "indeterminate"
        assert diag["per_sensor_scores"]["sada_override"]["sada_latched_fault"] == "bearing_outer"

    # clearing the fault does not restart the motor; an operator reset does
    client.delete(f"/api/v1/motors/1/faults/{fid}", headers=h)
    assert client.get("/api/v1/motors/1", headers=h).json()["state"]["supervisory"]["trip"] is True

    def reset_ok():
        return client.post("/api/v1/motors/1/supervisory/override", json={"action": "reset"},
                           headers=h).status_code == 200

    assert wait_for(reset_ok, timeout=60)
    assert wait_for(lambda: not client.get("/api/v1/motors/1", headers=h).json()["state"]["supervisory"]["trip"],
                    timeout=30)
