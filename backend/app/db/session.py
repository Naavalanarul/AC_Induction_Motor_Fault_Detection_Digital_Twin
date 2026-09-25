"""db/session.py — engine + session factory with connection pooling."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def make_engine(url: str) -> Engine:
    s = get_settings()
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool
        eng = create_engine(url, **kwargs)

        @event.listens_for(eng, "connect")
        def _fk(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return eng
    return create_engine(url, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow, pool_pre_ping=True,
                         pool_recycle=1800)


def init_engine(url: str | None = None) -> Engine:
    global _engine, _factory
    _engine = make_engine(url or get_settings().database_url)
    _factory = sessionmaker(_engine, expire_on_commit=False)
    _register_pool_metrics(_engine)
    return _engine


def _register_pool_metrics(engine: Engine) -> None:
    from app.core.metrics import DB_POOL_CAPACITY, DB_POOL_CHECKED_OUT

    pool = engine.pool
    DB_POOL_CHECKED_OUT.set_function(lambda: float(getattr(pool, "checkedout", lambda: 0)()))
    s = get_settings()
    DB_POOL_CAPACITY.set(s.db_pool_size + s.db_max_overflow)


def get_engine() -> Engine:
    return _engine if _engine is not None else init_engine()


def session_factory() -> sessionmaker[Session]:
    if _factory is None:
        init_engine()
    assert _factory is not None
    return _factory


def get_db() -> Iterator[Session]:
    with session_factory()() as db:
        yield db


def ping() -> bool:
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False
