import os
import stat
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import audit
from app.config import get_settings
from app.db import get_engine, secure_sqlite_file
from app.main import app
from app.models import AuditLog, UserSession
from app.security import client_ip, create_session_token, throttle

PWD = "un-mot-de-passe-solide"
NEW = "un-autre-mot-de-passe-solide"


def setup(client, pwd=PWD):
    r = client.post("/api/auth/setup", json={"username": "admin", "password": pwd})
    assert r.status_code == 201
    return client.cookies.get("kaji_session")


def second_client():
    c = TestClient(app)
    return c


def db():
    return Session(get_engine())


# ---------- sessions révocables ----------

def test_logout_revokes_the_token_server_side(client):
    old = setup(client)
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set("kaji_session", old)                          # le jeton copié avant la déconnexion
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/status").json()["authenticated"] is False
    with db() as s:
        assert s.scalars(select(UserSession)).all() == []


def test_each_login_has_its_own_session_and_logout_only_ends_that_one(client):
    setup(client)
    other = second_client()
    assert other.post("/api/auth/login", json={"username": "admin", "password": PWD}).status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert other.get("/api/auth/me").status_code == 200              # l'autre navigateur reste connecté


def test_logout_all_revokes_every_session(client):
    setup(client)
    other = second_client()
    other.post("/api/auth/login", json={"username": "admin", "password": PWD})
    assert client.post("/api/auth/logout-all").status_code == 204
    assert client.get("/api/auth/me").status_code == 401 and other.get("/api/auth/me").status_code == 401
    assert "logout-all" in [e["action"] for e in _audit_after_relogin(client)]


def _audit_after_relogin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": PWD})
    return client.get("/api/audit").json()


def test_token_with_a_valid_signature_but_no_session_row_is_refused(client):
    setup(client)
    key = get_settings().kaji_secret_key
    client.cookies.set("kaji_session", create_session_token(key, 1, 12, "jamais-ouverte"))
    assert client.get("/api/auth/me").status_code == 401


def test_legacy_token_without_jti_is_refused(client):
    import jwt
    from app.security import _signing_key
    setup(client)
    now = datetime.now(timezone.utc)
    legacy = jwt.encode({"sub": "1", "iat": now, "exp": now + timedelta(hours=1)}, _signing_key(get_settings().kaji_secret_key), algorithm="HS256")
    client.cookies.set("kaji_session", legacy)
    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_row_is_refused_and_cleaned_at_next_login(client):
    setup(client)
    with db() as s:
        row = s.scalars(select(UserSession)).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    assert client.get("/api/auth/me").status_code == 401
    client.post("/api/auth/login", json={"username": "admin", "password": PWD})
    with db() as s:
        assert len(s.scalars(select(UserSession)).all()) == 1          # l'expirée a disparu, la nouvelle existe


def test_session_of_another_user_id_is_refused(client):
    setup(client)
    with db() as s:
        row = s.scalars(select(UserSession)).one()
        row.user_id = 999
        s.commit()
    assert client.get("/api/auth/me").status_code == 401


# ---------- changement de mot de passe ----------

def test_password_change_requires_auth_and_current_password(client):
    assert client.post("/api/auth/password", json={"current_password": PWD, "new_password": NEW}).status_code == 401
    setup(client)
    r = client.post("/api/auth/password", json={"current_password": "faux", "new_password": NEW})
    assert r.status_code == 401 and "faux" not in r.text and NEW not in r.text
    assert client.post("/api/auth/login", json={"username": "admin", "password": NEW}).status_code == 401   # inchangé


def test_password_change_works_revokes_other_sessions_and_keeps_current(client):
    setup(client)
    other = second_client()
    other.post("/api/auth/login", json={"username": "admin", "password": PWD})
    r = client.post("/api/auth/password", json={"current_password": PWD, "new_password": NEW})
    assert r.status_code == 200 and client.get("/api/auth/me").status_code == 200       # la courante est renouvelée
    assert other.get("/api/auth/me").status_code == 401                                   # les autres sont coupées
    fresh = second_client()
    assert fresh.post("/api/auth/login", json={"username": "admin", "password": PWD}).status_code == 401
    assert fresh.post("/api/auth/login", json={"username": "admin", "password": NEW}).status_code == 200


def test_password_change_rules(client):
    setup(client)
    assert client.post("/api/auth/password", json={"current_password": PWD, "new_password": "court"}).status_code == 422
    assert client.post("/api/auth/password", json={"current_password": PWD, "new_password": PWD}).status_code == 422
    r = client.post("/api/auth/password", json={"current_password": PWD, "new_password": "COURT-ECHO"})
    assert r.status_code == 422 and "COURT-ECHO" not in r.text and PWD not in r.text


def test_password_change_is_throttled_and_audited_without_secrets(client):
    setup(client)
    for _ in range(5):
        assert client.post("/api/auth/password", json={"current_password": "faux", "new_password": NEW}).status_code == 401
    assert client.post("/api/auth/password", json={"current_password": PWD, "new_password": NEW}).status_code == 429
    throttle.reset()
    client.post("/api/auth/password", json={"current_password": PWD, "new_password": NEW})
    log = client.get("/api/audit").text
    assert "password-change" in log and PWD not in log and NEW not in log and "faux" not in log


# ---------- IP du client ----------

def req(headers=None, host="10.0.0.9"):
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
                    "client": (host, 1234), "method": "GET", "path": "/"})


def test_client_ip_ignores_forwarded_header_unless_proxy_is_trusted():
    spoof = {"X-Forwarded-For": "1.2.3.4"}
    assert client_ip(req(spoof), trust_proxy=False) == "10.0.0.9"                         # falsifiable : ignoré par défaut
    assert client_ip(req(spoof), trust_proxy=True) == "1.2.3.4"
    assert client_ip(req({"X-Forwarded-For": "6.6.6.6, 1.2.3.4"}), trust_proxy=True) == "1.2.3.4"   # la dernière : celle du proxy
    assert client_ip(req({"X-Forwarded-For": "pas-une-ip"}), trust_proxy=True) == "10.0.0.9"
    assert client_ip(req(), trust_proxy=True) == "10.0.0.9"


def test_login_throttle_cannot_be_dodged_by_a_spoofed_header_by_default(client):
    setup(client)
    client.post("/api/auth/logout")
    for i in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "faux"}, headers={"X-Forwarded-For": f"9.9.9.{i}"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": PWD}, headers={"X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 429


# ---------- fichier SQLite ----------

def test_sqlite_file_is_created_600_and_tightened_if_it_was_644(tmp_path):
    new = tmp_path / "sub" / "neuve.db"
    secure_sqlite_file(f"sqlite:///{new}")
    assert stat.S_IMODE(os.stat(new).st_mode) == 0o600
    old = tmp_path / "ancienne.db"
    old.write_bytes(b"")
    os.chmod(old, 0o644)
    secure_sqlite_file(f"sqlite:///{old}")
    assert stat.S_IMODE(os.stat(old).st_mode) == 0o600


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///:memory:", "postgresql://u@h/db"])
def test_secure_sqlite_file_ignores_memory_and_other_databases(url):
    secure_sqlite_file(url)                                                                # ne doit ni échouer ni créer de fichier


# ---------- purge de l'audit ----------

def test_audit_purge_removes_only_old_entries_and_zero_keeps_everything(client):
    now = datetime.now(timezone.utc)
    with db() as s:
        for days in (400, 366, 10, 0):
            s.add(AuditLog(ts=now - timedelta(days=days), username="a", action="x", target=str(days), status="started"))
        s.commit()
        assert audit.purge_old(s, 0) == 0 and len(s.scalars(select(AuditLog)).all()) == 4
        assert audit.purge_old(s, 365) == 2
        assert sorted(a.target for a in s.scalars(select(AuditLog)).all()) == ["0", "10"]


# ---------- en-têtes ----------

def test_security_headers_on_api_responses(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
    setup(client)
    assert client.get("/api/auth/me").headers["cache-control"] == "no-store"


def test_validation_error_responses_also_carry_the_headers(client):
    r = client.post("/api/auth/setup", json={"username": "x"})
    assert r.status_code == 422 and r.headers["x-content-type-options"] == "nosniff"
