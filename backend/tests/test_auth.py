PWD = "un-mot-de-passe-solide"


def setup(client, user="admin", pwd=PWD):
    return client.post("/api/auth/setup", json={"username": user, "password": pwd})


def test_status_before_setup(client):
    assert client.get("/api/auth/status").json() == {"setup_required": True, "authenticated": False, "setup_token_required": False}


def test_setup_creates_admin_and_logs_in(client):
    r = setup(client)
    assert r.status_code == 201
    assert "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=strict" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json() == {"username": "admin"}
    assert client.get("/api/auth/status").json() == {"setup_required": False, "authenticated": True, "setup_token_required": False}


def test_setup_rejects_short_password(client):
    assert setup(client, pwd="court").status_code == 422


def test_setup_only_once(client):
    assert setup(client).status_code == 201
    assert setup(client, user="autre").status_code == 409


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_login_logout(client):
    setup(client)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": PWD}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_login_wrong_password_and_unknown_user(client):
    setup(client)
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "faux"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "inconnu", "password": PWD}).status_code == 401


def test_login_throttled_after_failures(client):
    setup(client)
    client.post("/api/auth/logout")
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "faux"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": PWD})
    assert r.status_code == 429


def test_tampered_cookie_rejected(client):
    setup(client)
    client.cookies.set("kaji_session", "pas.un.jwt")
    assert client.get("/api/auth/me").status_code == 401
