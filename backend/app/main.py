"""main.py — FastAPI application factory, lifespan (startup/graceful shutdown), middleware.

Run with:  uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.routes import auth, health, motors, ws
from app.config import Settings, get_settings
from app.core.logging import configure_logging, request_id_var
from app.core.metrics import HTTP_REQUESTS
from app.core.security import hash_password
from app.db.models import Base, Motor, RoleEnum, User
from app.db.session import init_engine, session_factory
from app.runtime.broker import make_broker
from app.runtime.manager import WorkerManager
from app.runtime.retention import retention_loop
from app.runtime.worker import shared_classifier
from app.runtime.writer import DBWriter
from app.simulation.params import DEFAULT_MOTOR

log = logging.getLogger("app")
API_PREFIX = "/api/v1"


@dataclasses.dataclass
class Runtime:
    settings: Settings
    broker: object
    writer: DBWriter
    manager: WorkerManager
    tasks: list

    def ml_backend(self) -> str:
        return shared_classifier(self.settings.use_ml).backend


def bootstrap(settings: Settings) -> None:
    with session_factory()() as db:
        if settings.admin_username and settings.admin_password:
            if not db.scalar(select(User).where(User.username == settings.admin_username)):
                db.add(User(username=settings.admin_username, password_hash=hash_password(settings.admin_password),
                            role=RoleEnum.admin))
                log.info("bootstrapped admin user '%s'", settings.admin_username)
        db.commit()
        if settings.seed_demo_motor and not db.scalar(select(Motor.id).limit(1)):
            motors.create_motor_row(db, "Demo Motor 1", dataclasses.asdict(DEFAULT_MOTOR), 8.0)
            log.info("seeded demo motor")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level, settings.log_json)
        engine = init_engine(settings.database_url)
        if settings.auto_create_schema:
            Base.metadata.create_all(engine)
        await asyncio.to_thread(bootstrap, settings)
        broker = make_broker(settings.redis_url)
        writer = DBWriter()
        writer.start()
        manager = WorkerManager(settings, broker, writer)
        tasks = [asyncio.create_task(retention_loop(settings.retention_days, settings.retention_interval_s))]
        if settings.run_simulation:
            await manager.start_all_from_db()
        app.state.runtime = Runtime(settings, broker, writer, manager, tasks)
        log.info("startup complete (env=%s)", settings.app_env)
        try:
            yield
        finally:
            # Graceful shutdown: stop new WS connections + simulation loops, flush pending writes.
            log.info("shutting down")
            await manager.stop_all()
            for t in tasks:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            await writer.flush()
            await broker.close()
            engine.dispose()
            log.info("shutdown complete")

    app = FastAPI(title="AC Induction Motor Digital Twin", version="1.0.0", lifespan=lifespan,
                  docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:  # noqa: BLE001
            log.exception("unhandled error")
            response = JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500)
        finally:
            dt = time.perf_counter() - t0
            route = request.scope.get("route")
            HTTP_REQUESTS.labels(request.method, getattr(route, "path", "unmatched"), str(status_code)).observe(dt)
            log.info("request", extra={"method": request.method, "path": request.url.path, "status": status_code,
                                       "duration_ms": round(dt * 1000, 1)})
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    app.include_router(health.router)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(motors.router, prefix=API_PREFIX)
    app.include_router(ws.router, prefix=API_PREFIX)
    return app
