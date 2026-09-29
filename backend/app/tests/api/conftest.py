"""API test fixtures.

By default the app runs against a temporary SQLite file. Set TEST_DATABASE_URL
(e.g. mysql+pymysql://dt:dtpw@127.0.0.1:3306/digital_twin_test) to run the same
contract tests against a real MySQL; the schema is then created with
`alembic upgrade head`, exactly as in production.
"""

import os
import time

import pytest
from fastapi.testclient import TestClient

ADMIN = ("admin", "admin-pass-123")


def _configure_env(tmp_path_factory):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        os.environ["DATABASE_URL"] = url
        os.environ["AUTO_CREATE_SCHEMA"] = "false"
    else:
        db = tmp_path_factory.mktemp("db") / "test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db}"
        os.environ["AUTO_CREATE_SCHEMA"] = "true"
    os.environ.update({
        "APP_ENV": "test", "JWT_SECRET": "test-secret-" + "x" * 32, "ADMIN_USERNAME": ADMIN[0],
        "ADMIN_PASSWORD": ADMIN[1], "REALTIME_FACTOR": "4.0", "PERSIST_INTERVAL_S": "0.5", "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING", "SEED_DEMO_MOTOR": "true", "SEED_DEFAULT_FAULTS": "false", "LOGIN_RATE_PER_MIN": "1000", "FAULT_RATE_PER_MIN": "1000", "USE_ML": os.environ.get("TEST_USE_ML", "false"),
    })
    return url


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    url = _configure_env(tmp_path_factory)
    from app.config import get_settings

    get_settings.cache_clear()
    if url:
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    from app.main import create_app

    with TestClient(create_app(get_settings())) as c:
        yield c
    get_settings.cache_clear()


def login(client, username, password):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def tokens(client):
    admin = login(client, *ADMIN)["access_token"]
    h = {"Authorization": f"Bearer {admin}"}
    out = {"admin": admin}
    for role in ("operator", "viewer"):
        client.post("/api/v1/users", json={"username": f"{role}1", "password": "password-123", "role": role}, headers=h)
        out[role] = login(client, f"{role}1", "password-123")["access_token"]
    return out


@pytest.fixture
def auth(tokens):
    return lambda role: {"Authorization": f"Bearer {tokens[role]}"}


def wait_for(fn, timeout=20.0, interval=0.2):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    return last
