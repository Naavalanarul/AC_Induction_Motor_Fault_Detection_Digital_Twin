from app.tests.api.conftest import ADMIN


def test_login_and_me(client, auth):
    r = client.get("/api/v1/auth/me", headers=auth("operator"))
    assert r.json() == {"username": "operator1", "role": "operator"}


def test_bad_credentials(client):
    r = client.post("/api/v1/auth/login", json={"username": ADMIN[0], "password": "nope"})
    assert r.status_code == 401


def test_every_endpoint_requires_auth(client):
    for method, path in [("get", "/api/v1/motors"), ("get", "/api/v1/motors/1"), ("get", "/api/v1/motors/1/diagnoses"),
                         ("post", "/api/v1/motors/1/faults"), ("get", "/api/v1/users")]:
        assert getattr(client, method)(path).status_code == 401, path


def test_rbac(client, auth):
    fault = {"fault_type": "unbalance", "severity": 0.2}
    assert client.post("/api/v1/motors/1/faults", json=fault, headers=auth("viewer")).status_code == 403
    assert client.get("/api/v1/users", headers=auth("operator")).status_code == 403
    assert client.patch("/api/v1/motors/1/sensors/1", json={"mode": "hardware"}, headers=auth("operator")).status_code == 403
    assert client.get("/api/v1/users", headers=auth("admin")).status_code == 200


def test_refresh_flow_and_token_type_enforced(client):
    r = client.post("/api/v1/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]}).json()
    # a refresh token must not work as an access token
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r['refresh_token']}"}).status_code == 401
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": r["refresh_token"]})
    assert r2.status_code == 200 and r2.json()["access_token"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": r["access_token"]}).status_code == 401


def test_tampered_token_rejected(client, tokens):
    bad = tokens["admin"][:-4] + "abcd"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_login_rate_limited(client, monkeypatch):
    from app.api.routes import auth as auth_routes

    class S:
        login_rate_per_min = 3

    monkeypatch.setattr(auth_routes, "get_settings", lambda: S)
    codes = [client.post("/api/v1/auth/login", json={"username": "x", "password": "y"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and 429 in codes[3:]
