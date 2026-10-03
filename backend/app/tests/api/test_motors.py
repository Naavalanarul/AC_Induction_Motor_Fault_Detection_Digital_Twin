import uuid

from app.tests.api.conftest import wait_for


def state(client, auth):
    return client.get("/api/v1/motors/1", headers=auth("viewer")).json().get("state")


def test_health_endpoints(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    r = wait_for(lambda: (x := client.get("/readyz")).status_code == 200 and x)
    assert r and r.json()["db"] is True and r.json()["workers"] is True
    m = client.get("/metrics").text
    assert "dt_sim_ticks_total" in m and "dt_http_request_seconds" in m


def test_request_id_propagated(client):
    r = client.get("/healthz", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


def test_motor_listing_and_live_state(client, auth):
    motors = client.get("/api/v1/motors", headers=auth("viewer")).json()
    assert motors[0]["name"] == "Demo Motor 1"
    st = wait_for(lambda: state(client, auth))
    assert {"diagnosis", "supervisory", "faults", "mechanics"} <= set(st)
    assert st["diagnosis"]["schema_version"] == "1.0"


def test_create_motor_validation(client, auth):
    bad = {"name": "bad", "params": {"Rs": 1, "Rr": 1, "Ls": 0.1, "Lr": 0.1, "Lm": 0.2, "J": 0.01, "pole_pairs": 2,
                                     "rated_power": 1, "rated_voltage": 1, "rated_current": 1, "rated_speed": 1,
                                     "rated_torque": 1}}
    assert client.post("/api/v1/motors", json=bad, headers=auth("admin")).status_code == 422
    assert client.post("/api/v1/motors", json={"name": "Demo Motor 1"}, headers=auth("admin")).status_code == 409


def test_fault_injection_validation(client, auth):
    h = auth("operator")
    for body in ({"fault_type": "unbalance", "severity": 1.5}, {"fault_type": "nope", "severity": 0.5},
                 {"fault_type": "interturn_short", "severity": 0.5, "params": {"phase": "x"}},
                 {"fault_type": "unbalance", "severity": 0.5, "params": {"phase": "a"}}):
        assert client.post("/api/v1/motors/1/faults", json=body, headers=h).status_code == 422, body
    assert client.post("/api/v1/motors/999/faults", json={"fault_type": "unbalance", "severity": 0.1},
                       headers=h).status_code == 404


def test_fault_injection_is_idempotent_and_clearable(client, auth):
    h = {**auth("operator"), "Idempotency-Key": uuid.uuid4().hex}
    body = {"fault_type": "misalignment", "severity": 0.3}
    r1 = client.post("/api/v1/motors/1/faults", json=body, headers=h)
    r2 = client.post("/api/v1/motors/1/faults", json=body, headers=h)
    assert r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"]
    fid = r1.json()["id"]
    assert wait_for(lambda: any(f["id"] == fid for f in (state(client, auth) or {}).get("faults", [])))
    d1 = client.delete(f"/api/v1/motors/1/faults/{fid}", headers=auth("operator"))
    d2 = client.delete(f"/api/v1/motors/1/faults/{fid}", headers=auth("operator"))
    assert d1.status_code == d2.status_code == 200 and d1.json()["end_ts"] == d2.json()["end_ts"]
    assert wait_for(lambda: all(f["id"] != fid for f in state(client, auth)["faults"]))
    active = client.get("/api/v1/motors/1/faults?active=true", headers=auth("viewer")).json()
    assert all(f["id"] != fid for f in active)


def test_sensor_mode_switch(client, auth):
    sensors = client.get("/api/v1/motors/1/sensors", headers=auth("viewer")).json()
    assert {s["type"] for s in sensors} == {"current", "vibration", "acoustic", "temp", "speed", "voltage"}
    ac = next(s for s in sensors if s["type"] == "acoustic")
    # Must reject without confirmation
    r_bad = client.patch(f"/api/v1/motors/1/sensors/{ac['id']}", json={"mode": "hardware"}, headers=auth("admin"))
    assert r_bad.status_code == 400
    # Must succeed with confirmation
    r = client.patch(
        f"/api/v1/motors/1/sensors/{ac['id']}",
        json={"mode": "hardware", "confirm_hardware": True},
        headers=auth("admin"),
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "hardware"
    assert wait_for(lambda: state_sensor(client, auth, "acoustic") == "stale")
    client.patch(f"/api/v1/motors/1/sensors/{ac['id']}", json={"mode": "simulated"}, headers=auth("admin"))
    assert wait_for(lambda: state_sensor(client, auth, "acoustic") == "ok")


def state_sensor(client, auth, name):
    with client.websocket_connect(f"/api/v1/ws/motors/1/stream?token={auth('viewer')['Authorization'][7:]}") as ws:
        msg = ws.receive_json()
        msg = ws.receive_json()
    return msg["sensors"][name]["status"]


def test_supervisory_override(client, auth):
    h = auth("operator")
    r = client.post("/api/v1/motors/1/supervisory/override", json={"action": "set_load", "load": 0.4}, headers=h)
    assert r.status_code == 200 and r.json()["reason_code"] == "MANUAL_SET_LOAD" and r.json()["actor"] == "operator1"
    assert wait_for(lambda: state(client, auth)["supervisory"]["load_cmd"] == 0.4)
    client.post("/api/v1/motors/1/supervisory/override", json={"action": "release_load"}, headers=h)
    assert wait_for(lambda: not state(client, auth)["supervisory"]["manual_override"])
    assert client.post("/api/v1/motors/1/supervisory/override", json={"action": "set_load"},
                       headers=h).status_code == 422
    assert client.post("/api/v1/motors/1/supervisory/override", json={"action": "ack"},
                       headers=auth("viewer")).status_code == 403


def test_diagnoses_pagination_and_filter(client, auth):
    page = wait_for(lambda: (p := client.get("/api/v1/motors/1/diagnoses?limit=2",
                                             headers=auth("viewer")).json())["total"] >= 3 and p)
    assert len(page["items"]) == 2 and page["limit"] == 2
    ts = [i["ts"] for i in page["items"]]
    assert ts == sorted(ts, reverse=True)
    f = client.get("/api/v1/motors/1/diagnoses?fault_type=healthy&limit=5", headers=auth("viewer")).json()
    assert all(i["fault_type"] == "healthy" for i in f["items"])
    assert client.get("/api/v1/motors/1/diagnoses?fault_type=bogus", headers=auth("viewer")).status_code == 422


def test_history_contains_faults_and_supervisory(client, auth):
    events = client.get("/api/v1/motors/1/history", headers=auth("viewer")).json()
    kinds = {e["kind"] for e in events}
    assert {"fault_injected", "supervisory"} <= kinds


def test_create_motor_starts_a_streaming_worker(client, auth):
    r = client.post("/api/v1/motors", json={"name": "Second Motor", "base_load_nm": 4.0}, headers=auth("admin"))
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert client.post("/api/v1/motors", json={"name": "x"}, headers=auth("operator")).status_code == 403
    st = wait_for(lambda: client.get(f"/api/v1/motors/{mid}", headers=auth("viewer")).json().get("state"))
    assert st and st["supervisory"]["base_load_nm"] == 4.0
    assert len(client.get(f"/api/v1/motors/{mid}/sensors", headers=auth("viewer")).json()) == 6


def test_transient_solve_endpoint(client, auth):
    r = client.post(
        "/api/v1/motors/1/simulation/transient-solve",
        json={"duration_s": 0.5, "load_torque_nm": 8.0, "brb_delta": 0.2},
        headers=auth("viewer"),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["motor_id"] == 1
    assert "rpm" in d and len(d["rpm"]) > 0
    assert "ia" in d and len(d["ia"]) > 0
    assert "te" in d and len(d["te"]) > 0
    assert d["steady_state_rpm"] > 1400.0


def test_mcsa_endpoint(client, auth):
    r = client.get("/api/v1/motors/1/mcsa", headers=auth("viewer"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert "status" in d
    assert "peaks" in d


def test_rul_endpoint(client, auth):
    r = client.get("/api/v1/motors/1/rul", headers=auth("viewer"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["motor_id"] == 1
    assert "overall_rul_hours" in d
    assert "overall_health_percent" in d
    assert "limiting_factor" in d
    assert "insulation" in d
    assert "bearing_de" in d
    assert "bearing_nde" in d
    assert d["insulation"]["rul_hours"] > 0
    assert d["bearing_de"]["rul_hours"] > 0


