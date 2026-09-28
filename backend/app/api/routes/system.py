"""api/routes/system.py — System health, database connectivity status, and MySQL configuration."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text
from sqlalchemy.engine import create_engine
from sqlalchemy.engine.url import make_url

from app.api.deps import Principal, current_principal
from app.config import get_settings
from app.db.session import get_engine, init_engine

router = APIRouter(prefix="/system", tags=["system"])


class DbStatusOut(BaseModel):
    connected: bool
    engine: str
    dialect: str
    database: str
    user: str
    host: str
    port: int | None = None
    latency_ms: float | None = None
    tables: list[str] = Field(default_factory=list)
    pool: dict[str, Any] | None = None
    error: str | None = None


class DbTestIn(BaseModel):
    password: str
    user: str = "dt"
    host: str = "localhost"
    port: int = 3306
    database: str = "digital_twin"
    apply: bool = False


class DbTestOut(BaseModel):
    success: bool
    message: str
    latency_ms: float | None = None
    applied: bool = False


@router.get("/db-status", response_model=DbStatusOut)
def get_db_status(_: Principal = Depends(current_principal)) -> DbStatusOut:
    """Inspect active database connection status, dialect, latency, and schema tables."""
    engine = get_engine()
    settings = get_settings()

    try:
        url = make_url(settings.database_url)
        dialect_name = url.get_backend_name()
        engine_repr = f"{url.drivername}"
        db_name = url.database or "default"
        db_user = url.username or ("sqlite_local" if dialect_name == "sqlite" else "anonymous")
        db_host = url.host or ("local_file" if dialect_name == "sqlite" else "localhost")
        db_port = url.port or (3306 if "mysql" in dialect_name else None)
    except Exception as exc:  # noqa: BLE001
        return DbStatusOut(
            connected=False,
            engine="unknown",
            dialect="unknown",
            database="unknown",
            user="unknown",
            host="unknown",
            error=f"Invalid database URL configuration: {exc}",
        )

    t0 = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency = round((time.perf_counter() - t0) * 1000, 2)
        connected = True
        err_msg = None
    except Exception as exc:  # noqa: BLE001
        latency = None
        connected = False
        err_msg = str(exc)

    tables: list[str] = []
    if connected:
        try:
            insp = inspect(engine)
            tables = sorted(insp.get_table_names())
        except Exception:  # noqa: BLE001
            tables = []

    pool_info: dict[str, Any] | None = None
    if dialect_name != "sqlite":
        pool = engine.pool
        pool_info = {
            "size": getattr(pool, "size", lambda: settings.db_pool_size)(),
            "checked_out": getattr(pool, "checkedout", lambda: 0)(),
        }

    return DbStatusOut(
        connected=connected,
        engine=engine_repr,
        dialect=dialect_name,
        database=db_name,
        user=db_user,
        host=db_host,
        port=db_port,
        latency_ms=latency,
        tables=tables,
        pool=pool_info,
        error=err_msg,
    )


@router.post("/db-test", response_model=DbTestOut)
def test_mysql_connection(
    payload: DbTestIn,
    p: Principal = Depends(current_principal),
) -> DbTestOut:
    """Test connecting to MySQL with the specified credentials, and optionally apply them to runtime."""
    if payload.apply and p.role not in ("operator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Applying new database credentials requires operator or admin privileges.",
        )

    # Construct MySQL SQLAlchemy URL with pymysql driver
    mysql_url = f"mysql+pymysql://{payload.user}:{payload.password}@{payload.host}:{payload.port}/{payload.database}"

    t0 = time.perf_counter()
    try:
        test_engine = create_engine(
            mysql_url,
            connect_args={"connect_timeout": 3},
            pool_pre_ping=True,
        )
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency = round((time.perf_counter() - t0) * 1000, 2)
        test_engine.dispose()
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)
        # Simplify common driver error strings for better UI display
        if "Can't connect to MySQL server" in err_msg or "Connection refused" in err_msg:
            readable = f"Cannot reach MySQL server at {payload.host}:{payload.port} (Connection refused). Is the MySQL container/service running?"
        elif "Access denied for user" in err_msg:
            readable = f"Access denied for user '{payload.user}' on {payload.host}. Please verify password."
        elif "Unknown database" in err_msg:
            readable = f"Database '{payload.database}' does not exist on MySQL server."
        else:
            readable = f"Connection failed: {err_msg}"
        return DbTestOut(
            success=False,
            message=readable,
            latency_ms=None,
            applied=False,
        )

    applied = False
    if payload.apply:
        settings = get_settings()
        settings.database_url = mysql_url
        init_engine(mysql_url)
        applied = True

    return DbTestOut(
        success=True,
        message=f"Successfully connected to MySQL database '{payload.database}' on {payload.host}:{payload.port} (Ping: {latency} ms)."
        + (" Active database updated." if applied else ""),
        latency_ms=latency,
        applied=applied,
    )
