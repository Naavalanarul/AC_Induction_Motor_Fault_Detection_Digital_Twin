"""tests/api/test_p1_8_ws_lifecycle.py — P1-8 WebSocket auth, token lifecycle and revocation regression tests."""

from __future__ import annotations

import time

import jwt
import pytest
from sqlalchemy import update
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.core.security import create_token, revoke_token
from app.db.models import User
from app.db.session import session_factory


def test_p1_8_refresh_token_rotation_and_revocation(client):
    """P1-8: Refresh tokens rotate on use; re-using a used refresh token fails with 401."""
    login_res = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    assert login_res.status_code == 200
    data = login_res.json()
    first_refresh = data["refresh_token"]

    # 1. First refresh succeeds and rotates token
    ref_res1 = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert ref_res1.status_code == 200
    second_refresh = ref_res1.json()["refresh_token"]
    assert second_refresh != first_refresh

    # 2. Re-using the first refresh token must fail with 401 (already revoked)
    ref_res2 = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert ref_res2.status_code == 401


def test_p1_8_logout_revokes_token(client):
    """P1-8: Logging out revokes the access and refresh tokens immediately."""
    login_res = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-pass-123"})
    assert login_res.status_code == 200
    tokens = login_res.json()

    # Access endpoint works with access token
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200

    # Logout
    logout_res = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=headers,
    )
    assert logout_res.status_code == 200

    # Accessing endpoint after logout is rejected with 401
    me_after = client.get("/api/v1/auth/me", headers=headers)
    assert me_after.status_code == 401

    # Refresh after logout is rejected with 401
    ref_after = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ref_after.status_code == 401


def test_p1_8_ws_closes_when_user_deactivated(client, tokens):
    """P1-8: Open WebSocket stream closes with 4401 when the user account is deactivated."""
    client.app.state.ws_reval_interval_s = 0.1

    with client.websocket_connect(
        "/api/v1/ws/motors/1/stream",
        subprotocols=["bearer", tokens["viewer"]],
    ) as ws:
        m = ws.receive_json()
        assert m["type"] == "frame"

        # Deactivate user viewer1 in DB
        with session_factory()() as db:
            db.execute(update(User).where(User.username == "viewer1").values(is_active=False))
            db.commit()

        # The stream loop re-validates, detects deactivated user, and closes with 4401
        with pytest.raises(WebSocketDisconnect) as exc:
            for _ in range(25):
                time.sleep(0.05)
                ws.receive_json()
        assert exc.value.code == 4401

        # Restore viewer account
        with session_factory()() as db:
            db.execute(update(User).where(User.username == "viewer1").values(is_active=True))
            db.commit()


def test_p1_8_ws_closes_when_token_revoked(client):
    """P1-8: Open WebSocket stream closes with 4401 when token is revoked during active streaming."""
    client.app.state.ws_reval_interval_s = 0.1

    # Create dedicated valid token for viewer1
    tok = create_token("viewer1", "viewer", "access")

    with client.websocket_connect(
        "/api/v1/ws/motors/1/stream",
        subprotocols=["bearer", tok],
    ) as ws:
        m = ws.receive_json()
        assert m["type"] == "frame"

        # Revoke the token
        payload = jwt.decode(tok, get_settings().jwt_secret, algorithms=["HS256"])
        revoke_token(payload["jti"])

        # Stream loop detects revocation and closes with 4401
        with pytest.raises(WebSocketDisconnect) as exc:
            for _ in range(25):
                time.sleep(0.05)
                ws.receive_json()
        assert exc.value.code == 4401
