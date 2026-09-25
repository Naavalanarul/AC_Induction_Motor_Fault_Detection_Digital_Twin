from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.db.session import ping

router = APIRouter(tags=["ops"])


@router.get("/healthz")
def healthz():
    """Liveness: the process is up and serving."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request):
    """Readiness: DB reachable and simulation workers ticking."""
    rt = request.app.state.runtime
    db_ok = ping()
    workers_ok = rt.manager.healthy()
    body = {"db": db_ok, "workers": workers_ok, "detail": rt.manager.health(), "ml_backend": rt.ml_backend()}
    return JSONResponse(body, status_code=200 if db_ok and workers_ok else 503)


@router.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
