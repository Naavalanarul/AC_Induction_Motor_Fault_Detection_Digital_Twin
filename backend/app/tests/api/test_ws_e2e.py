import pytest
from starlette.websockets import WebSocketDisconnect

from app.tests.api.conftest import wait_for


def test_ws_rejects_missing_and_bad_token(client):
    for url in ("/api/v1/ws/motors/1/stream", "/api/v1/ws/motors/1/stream?token=garbage"):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(url) as ws:
                ws.receive_json()
        assert exc.value.code == 4401


def test_ws_unknown_motor(client, tokens):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/v1/ws/motors/999/stream?token={tokens['viewer']}") as ws:
            ws.receive_json()
    assert exc.value.code == 4404


def test_ws_stream_schema(client, tokens):
    with client.websocket_connect(f"/api/v1/ws/motors/1/stream?token={tokens['viewer']}") as ws:
        msgs = [ws.receive_json() for _ in range(3)]
    m = msgs[-1]
    assert m["type"] == "frame" and m["motor_id"] == 1
    assert set(m["sensors"]) == {"current", "vibration", "acoustic", "temp", "speed", "voltage"}
    assert {"fault_type", "confidence", "severity", "per_sensor_scores"} <= set(m["diagnosis"])
    assert {"state", "load_cmd", "reason_code", "trip"} <= set(m["supervisory"])
    assert msgs[-1]["t"] > msgs[0]["t"]


def test_ws_subprotocol_token(client, tokens):
    with client.websocket_connect("/api/v1/ws/motors/1/stream", subprotocols=["bearer", tokens["viewer"]]) as ws:
        assert ws.receive_json()["type"] == "frame"


def test_inject_fault_see_diagnosis_and_sada_derate(client, auth, tokens):
    """End-to-end: inject fault -> diagnosis appears in live stream -> SADA leaves NORMAL."""
    r = client.post("/api/v1/motors/1/faults", json={"fault_type": "interturn_short", "severity": 0.6,
                                                     "params": {"phase": "b"}}, headers=auth("operator"))
    fid = r.json()["id"]

    def seen():
        with client.websocket_connect(f"/api/v1/ws/motors/1/stream?token={tokens['viewer']}") as ws:
            m = ws.receive_json()
        ok = m["diagnosis"]["fault_type"] == "interturn_short" and m["supervisory"]["state"] in ("WATCH", "DERATE", "TRIP")
        return ok and m

    m = wait_for(seen, timeout=30)
    assert m, "fault not diagnosed / SADA did not react"
    assert m["diagnosis"]["per_sensor_scores"]["electrical_residual"]["details"]["FL_phase"] == "b"
    client.delete(f"/api/v1/motors/1/faults/{fid}", headers=auth("operator"))
    # alerts were recorded for the SADA transition
    alerts = wait_for(lambda: client.get("/api/v1/motors/1/alerts", headers=auth("viewer")).json())
    assert any("SADA" in a["message"] for a in alerts)
    # operator resets once healthy again (trip may or may not have happened)
    def reset_ok():
        return client.post("/api/v1/motors/1/supervisory/override", json={"action": "reset"},
                           headers=auth("operator")).status_code == 200
    assert wait_for(reset_ok, timeout=40)
