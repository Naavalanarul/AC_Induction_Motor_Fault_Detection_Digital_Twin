"""WebSocket live stream. The token is validated during the handshake, before
the socket is accepted or subscribed to any broker channel."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.api.deps import principal_from_token
from app.core.metrics import WS_CONNECTIONS
from app.core.security import role_allows
from app.db.models import Motor
from app.db.session import session_factory

router = APIRouter()
log = logging.getLogger(__name__)


def _token_from(ws: WebSocket) -> str | None:
    tok = ws.query_params.get("token")
    if tok:
        return tok
    # Alternative: Sec-WebSocket-Protocol: bearer, <token>
    protos = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    if len(protos) == 2 and protos[0] == "bearer":
        return protos[1]
    return None


@router.websocket("/ws/motors/{motor_id}/stream")
async def stream(ws: WebSocket, motor_id: int):
    rt = ws.app.state.runtime
    token = _token_from(ws)
    if token is None:
        await ws.close(code=4401, reason="missing token")
        return
    try:
        with session_factory()() as db:
            p = principal_from_token(token, db)
            exists = db.get(Motor, motor_id) is not None
    except HTTPException:
        await ws.close(code=4401, reason="invalid token")
        return
    if not role_allows(p.role, "viewer"):
        await ws.close(code=4403, reason="forbidden")
        return
    if not exists:
        await ws.close(code=4404, reason="motor not found")
        return
    if not rt.manager.accepting:
        await ws.close(code=1012, reason="server restarting")
        return

    subprotocol = "bearer" if "bearer" in ws.headers.get("sec-websocket-protocol", "") else None
    await ws.accept(subprotocol=subprotocol)
    WS_CONNECTIONS.inc()
    try:
        latest = await rt.broker.get_latest(motor_id)
        if latest:
            await ws.send_json(latest)
        async with rt.broker.subscribe(f"motor:{motor_id}") as events:
            recv = asyncio.create_task(ws.receive_text())  # detects client disconnect
            it = events.__aiter__()
            while True:
                nxt = asyncio.create_task(it.__anext__())
                done, _ = await asyncio.wait({nxt, recv}, return_when=asyncio.FIRST_COMPLETED)
                if recv in done:
                    nxt.cancel()
                    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                        await nxt
                    recv.result()  # raises WebSocketDisconnect on close
                    recv = asyncio.create_task(ws.receive_text())  # ignore client chatter (e.g. pings)
                    continue
                await ws.send_json(nxt.result())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        WS_CONNECTIONS.dec()
        with contextlib.suppress(Exception):
            recv.cancel()
