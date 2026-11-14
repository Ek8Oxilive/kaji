"""Jeton Proxmox PERSONNEL de chaque utilisateur de Kaji (lot #440, option A du cadrage).

Le faux Proxmox authentifie chaque jeton (`Authorization: PVEAPIToken=…`) et note QUI appelle : on vérifie donc que l'action d'Alice part avec le jeton d'Alice et celle de Bob
avec le jeton partagé, que rien ne fuit, et que les garde-fous (privilèges séparés, expiration, `root@pam`, jeton partagé, jeton refusé, clé changée) tiennent.
"""
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import deps, tokenkey
from app.config import get_settings
from app.crypto import encrypt
from app.db import get_engine
from app.deps import (EXPIRED_DETAIL, KEY_DETAIL, NO_TOKEN_DETAIL, REFUSED_DETAIL, get_base_client_factory, personal_factory)
from app.main import app
from app.models import AdminUser, AuditLog, Connection, UserToken
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
KEY = "cle-separee-des-jetons-personnels-0123456789abcdef"
SHARED = ("kaji@pve", "kaji", "secret-partage-0001")
ALICE = ("alice@pve", "perso", "secret-alice-0002")
BOB = ("bob@pve", "perso", "secret-bob-00003")
DAYS = lambda n: datetime.now(timezone.utc) + timedelta(days=n)       # noqa: E731


class FakePve:
    """Faux Proxmox strict : seuls les jetons connus passent ; chaque appel est noté avec l'identité authentifiée."""

    def __init__(self):
        self.known = {f"{u}!{t}": s for u, t, s in (SHARED, ALICE, BOB)}
        self.calls: list[tuple[str, str]] = []                          # (identité, chemin)
        self.info: dict[str, dict | int] = {}                           # identité -> réponse de /access/users/../token/.. (dict) ou code d'erreur (int)
        self.revoked: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        ident, _, secret = auth.removeprefix("PVEAPIToken=").partition("=")
        path = request.url.path.removeprefix("/api2/json")
        if self.known.get(ident) != secret or ident in self.revoked:
            self.calls.append(("REFUSÉ:" + ident, path))
            return httpx.Response(401, json={"data": None})
        self.calls.append((ident, path))
        if path == "/version":
            return httpx.Response(200, json={"data": {"version": "9.1"}})
        if path.startswith("/access/users/") and "/token/" in path:
            what = self.info.get(ident, {"privsep": 1, "expire": int(DAYS(30).timestamp())})
            return httpx.Response(what, json={"data": None}) if isinstance(what, int) else httpx.Response(200, json={"data": what})
        if path == "/nodes":
            return httpx.Response(200, json={"data": [{"node": "n1", "status": "online"}]})
        return httpx.Response(404, json={"data": None})


@pytest.fixture
def pve():
    return FakePve()


@pytest.fixture
def env(client, pve, monkeypatch):
    """Un administrateur connecté, une connexion enregistrée, la clé séparée configurée, le faux Proxmox branché sur la fabrique de base."""
    s = get_settings()
    monkeypatch.setattr(s, "kaji_token_key", KEY)
    monkeypatch.setattr(s, "kaji_token_key_file", "")
    monkeypatch.setattr(s, "kaji_token_key_previous", "")
    monkeypatch.setattr(s, "kaji_require_user_token", False)
    monkeypatch.setattr(s, "kaji_user_token_max_days", 90)
    app.dependency_overrides[get_base_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(pve.handler)))
    client.post("/api/auth/setup", json={"username": "alice", "password": PWD})
    with Session(get_engine()) as db:
        db.add(Connection(name="lab", host="10.0.0.5", port=8006, user=SHARED[0], token_id=SHARED[1], token_secret_enc=encrypt(s.kaji_secret_key, SHARED[2]), verify_ssl=False))
        db.commit()
    yield client
    app.dependency_overrides.pop(get_base_client_factory, None)


def login(name: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": name, "password": PWD})
    assert r.status_code == 200, r.text
    return c


def make_user(admin: TestClient, name: str, role: str = "operator") -> TestClient:
    assert admin.post("/api/kaji-users", json={"username": name, "password": PWD, "role": role}).status_code == 201
    return login(name)


def body(identity=ALICE, **extra) -> dict:
    u, t, s = identity
    return {"pve_user": u, "token_id": t, "secret": s, **extra}


def put(c: TestClient, identity=ALICE, conn=1, **extra):
    return c.put(f"/api/me/proxmox-tokens/{conn}", json=body(identity, **extra))


def rows() -> list[UserToken]:
    with Session(get_engine()) as db:
        return list(db.scalars(select(UserToken)))


def audit_text() -> str:
    with Session(get_engine()) as db:
        return json.dumps([(a.action, a.target, a.status, a.detail) for a in db.scalars(select(AuditLog))])


# ------------------------------------------------------------------ enregistrement

def test_a_valid_token_is_registered_checked_by_proxmox_and_never_returned(env, pve):
    r = put(env)
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["state"], v["pve_user"], v["token_id"], v["verified"], v["privsep"]) == ("ok", "alice@pve", "perso", True, True) and 29 <= v["days_left"] <= 30
    assert ALICE[2] not in r.text and "secret" not in v and "secret_enc" not in v
    assert ("alice@pve!perso", "/version") in pve.calls and ("alice@pve!perso", "/access/users/alice@pve/token/perso") in pve.calls     # contrôlé AVEC le jeton lui-même
    (row,) = rows()
    assert row.secret_enc != ALICE[2] and ALICE[2] not in row.secret_enc and tokenkey.decrypt(row.secret_enc, [KEY]) == ALICE[2]
    audit = audit_text()
    assert "user-token-set" in audit and "alice@pve!perso" in audit and ALICE[2] not in audit and KEY not in audit
    listing = env.get("/api/me/proxmox-tokens").json()
    assert listing["enabled"] and not listing["required"] and listing["max_days"] == 90 and listing["connections"][0]["state"] == "ok" and ALICE[2] not in json.dumps(listing)


def test_without_the_separate_key_the_feature_is_off_and_registration_is_refused(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "kaji_token_key", "")
    listing = env.get("/api/me/proxmox-tokens").json()
    assert listing["enabled"] is False and "KAJI_TOKEN_KEY" in listing["problem"]
    r = put(env)
    assert r.status_code == 409 and "KAJI_TOKEN_KEY" in r.text and rows() == []
    monkeypatch.setattr(get_settings(), "kaji_token_key", get_settings().kaji_secret_key)         # la même clé que les données : refusée aussi
    assert put(env).status_code == 409 and rows() == []


@pytest.mark.parametrize("extra,identity,needle", [
    ({}, ("root@pam", "x", "secret-root-0000"), "root@pam"),
    ({}, SHARED, "PARTAGÉ"),
    ({"privsep": False}, ALICE, "privilèges séparés"),
])
def test_forbidden_tokens_are_refused_and_audited_without_secret(env, pve, extra, identity, needle):
    r = put(env, identity, **extra)
    assert r.status_code == 422 and needle in r.json()["detail"] and rows() == []
    assert identity[2] not in r.text and identity[2] not in audit_text() and "error" in audit_text()
    assert not any(c[0].startswith("root@pam") for c in pve.calls)                                    # jamais même essayé chez Proxmox


def test_proxmox_saying_the_token_has_no_privilege_separation_or_no_expiry_is_trusted_over_the_declaration(env, pve):
    pve.info["alice@pve!perso"] = {"privsep": 0, "expire": int(DAYS(30).timestamp())}
    r = put(env)                                                    # l'utilisateur déclare privsep=true (défaut), Proxmox dit 0
    assert r.status_code == 422 and "PAS les privilèges séparés" in r.text and rows() == []
    pve.info["alice@pve!perso"] = {"privsep": 1, "expire": 0}
    r = put(env, expires_at=str(date.today() + timedelta(days=10)))                    # une date déclarée ne remplace pas l'absence d'expiration chez Proxmox
    assert r.status_code == 422 and "pas de date d'expiration" in r.text and rows() == []


def test_expiry_rules_proxmox_date_declared_date_maximum_and_past(env, pve):
    pve.info["alice@pve!perso"] = {"privsep": 1, "expire": int(DAYS(200).timestamp())}
    assert put(env).status_code == 422 and "au plus 90 jours" in put(env).text
    pve.info["alice@pve!perso"] = {"privsep": 1, "expire": int(DAYS(-1).timestamp())}
    assert put(env).status_code == 422 and rows() == []
    pve.info["alice@pve!perso"] = {"privsep": 1, "expire": int(DAYS(60).timestamp())}
    r = put(env, expires_at=str(date.today() + timedelta(days=5)))                      # une date déclarée plus proche l'emporte
    assert r.status_code == 200 and r.json()["days_left"] <= 5


def test_when_proxmox_does_not_describe_the_token_a_declared_date_is_required_and_the_result_is_marked_unverified(env, pve):
    pve.info["alice@pve!perso"] = 403
    r = put(env)
    assert r.status_code == 422 and "indique sa date d'expiration" in r.text and rows() == []
    r = put(env, expires_at=str(date.today() + timedelta(days=30)))
    assert r.status_code == 200 and r.json()["verified"] is False
    assert put(env, expires_at=str(date.today() + timedelta(days=500))).status_code == 422
    assert put(env, expires_at=str(date.today() - timedelta(days=1))).status_code == 422


def test_garbled_proxmox_answers_never_count_as_verified(env, pve):
    for odd in ({"privsep": True, "expire": 5}, {"privsep": "oui", "expire": "demain"}, {}, {"privsep": 1}):
        pve.info["alice@pve!perso"] = odd
        r = put(env, expires_at=str(date.today() + timedelta(days=10)))
        assert r.status_code == 200 and r.json()["verified"] is False, odd


def test_a_token_proxmox_rejects_is_refused_without_echoing_what_was_typed(env, pve):
    r = env.put("/api/me/proxmox-tokens/1", json=body(("alice@pve", "perso", "mauvais-secret-9999")))
    assert r.status_code == 422 and "refuse ce jeton" in r.text and "mauvais-secret-9999" not in r.text + audit_text() and rows() == []


@pytest.mark.parametrize("payload", [
    {"pve_user": "pas-de-realm", "token_id": "perso", "secret": "secret-ok-12345"}, {"pve_user": "a@b", "token_id": "1mauvais", "secret": "secret-ok-12345"},
    {"pve_user": "a@b", "token_id": "ok", "secret": "court"}, {"pve_user": "a@b", "token_id": "ok", "secret": "avec des espaces dedans"},
    {"pve_user": "a@b", "token_id": "ok", "secret": "secret-ok-12345", "extra": 1}, {"pve_user": "a@b", "token_id": "ok"},
    {"pve_user": "a@b\n", "token_id": "ok", "secret": "secret-ok-12345"}, {"pve_user": "a@b", "token_id": "ok\n", "secret": "secret-ok-12345"},
])
def test_malformed_input_is_refused_and_the_secret_is_never_echoed(env, payload):
    r = env.put("/api/me/proxmox-tokens/1", json=payload)
    assert r.status_code == 422 and payload.get("secret", "§§§") not in r.text and rows() == []


def test_unknown_connection_and_unauthenticated_access(env):
    assert put(env, conn=99).status_code == 404 and env.delete("/api/me/proxmox-tokens/99").status_code == 404
    anonymous = TestClient(app)
    for method, url in (("get", "/api/me/proxmox-tokens"), ("put", "/api/me/proxmox-tokens/1"), ("delete", "/api/me/proxmox-tokens/1")):
        assert getattr(anonymous, method)(url).status_code == 401


def test_every_role_manages_only_their_own_token_and_cannot_see_the_others(env):
    assert put(env).status_code == 200
    viewer = make_user(env, "victor", "viewer")
    assert viewer.get("/api/me/proxmox-tokens").json()["connections"][0]["state"] == "none"        # le jeton d'Alice n'est pas à Victor
    assert viewer.delete("/api/me/proxmox-tokens/1").status_code == 404
    assert put(viewer, BOB).status_code == 200                                                      # même un lecteur enregistre le SIEN
    assert env.get("/api/me/proxmox-tokens").json()["connections"][0]["pve_user"] == "alice@pve"
    assert {r.pve_user for r in rows()} == {"alice@pve", "bob@pve"}
    assert viewer.delete("/api/me/proxmox-tokens/1").status_code == 204 and {r.pve_user for r in rows()} == {"alice@pve"}


def test_registering_again_replaces_the_token_and_clears_a_previous_refusal(env, pve):
    put(env)
    with Session(get_engine()) as db:
        row = db.scalars(select(UserToken)).one(); row.refused_at = datetime.now(timezone.utc); db.commit()
    assert env.get("/api/me/proxmox-tokens").json()["connections"][0]["state"] == "refused"
    assert put(env).status_code == 200 and len(rows()) == 1 and rows()[0].refused_at is None


# ------------------------------------------------------------------ quel jeton part chez Proxmox

def test_each_user_acts_with_their_own_token_and_others_keep_the_shared_one(env, pve):
    put(env)                                                                        # Alice enregistre le sien
    bob = make_user(env, "bob")                                                     # Bob n'en a pas
    pve.calls.clear()
    assert env.get("/api/connections/1/nodes").status_code == 200
    assert pve.calls == [("alice@pve!perso", "/nodes")]                              # le journal de Proxmox verrait ALICE
    pve.calls.clear()
    assert bob.get("/api/connections/1/nodes").status_code == 200
    assert pve.calls == [("kaji@pve!kaji", "/nodes")]                                # Bob : le jeton partagé, comme avant
    put(bob, BOB)
    pve.calls.clear(); bob.get("/api/connections/1/nodes"); env.get("/api/connections/1/nodes")
    assert pve.calls == [("bob@pve!perso", "/nodes"), ("alice@pve!perso", "/nodes")]


def test_when_a_personal_token_is_required_a_user_without_one_gets_no_access_and_proxmox_is_not_called(env, pve, monkeypatch):
    put(env)
    bob = make_user(env, "bob")
    monkeypatch.setattr(get_settings(), "kaji_require_user_token", True)
    pve.calls.clear()
    r = bob.get("/api/connections/1/nodes")
    assert r.status_code == 403 and r.json()["detail"] == NO_TOKEN_DETAIL and pve.calls == []
    assert env.get("/api/connections/1/nodes").status_code == 200 and pve.calls == [("alice@pve!perso", "/nodes")]       # Alice, avec le sien
    assert put(bob, BOB).status_code == 200 and bob.get("/api/connections/1/nodes").status_code == 200                      # et Bob peut enregistrer le sien
    assert env.get("/api/me/proxmox-tokens").json()["required"] is True


def test_a_token_past_its_date_is_never_used_even_if_proxmox_would_still_accept_it(env, pve):
    put(env)
    with Session(get_engine()) as db:
        row = db.scalars(select(UserToken)).one(); row.expires_at = DAYS(-1); db.commit()
    pve.calls.clear()
    r = env.get("/api/connections/1/nodes")
    assert r.status_code == 403 and r.json()["detail"] == EXPIRED_DETAIL and pve.calls == []
    assert env.get("/api/me/proxmox-tokens").json()["connections"][0]["state"] == "expired"
    assert ALICE[2] not in r.text


def test_a_token_revoked_at_proxmox_is_reported_clearly_then_blocked_until_replaced(env, pve):
    put(env)
    pve.revoked.add("alice@pve!perso")
    r = env.get("/api/connections/1/nodes")
    assert r.status_code == 502 and r.json()["detail"] == REFUSED_DETAIL and ALICE[2] not in r.text           # message dédié, pas « token refusé » tout court
    assert rows()[0].refused_at is not None and env.get("/api/me/proxmox-tokens").json()["connections"][0]["state"] == "refused"
    pve.calls.clear()
    r = env.get("/api/connections/1/nodes")
    assert r.status_code == 403 and r.json()["detail"] == REFUSED_DETAIL and pve.calls == []                    # plus d'appel chez Proxmox
    pve.revoked.clear()
    assert put(env).status_code == 200 and env.get("/api/connections/1/nodes").status_code == 200              # l'enregistrer de nouveau débloque


def test_a_shared_token_refused_by_proxmox_keeps_the_old_message_and_is_not_blamed_on_the_user(env, pve):
    pve.revoked.add("kaji@pve!kaji")
    r = make_user(env, "bob").get("/api/connections/1/nodes")
    assert r.status_code == 502 and r.json()["detail"] == "Token refusé par Proxmox" and rows() == []


def test_a_changed_or_missing_separate_key_makes_tokens_unreadable_with_a_clear_message(env, pve, monkeypatch):
    put(env)
    pve.calls.clear()
    monkeypatch.setattr(get_settings(), "kaji_token_key", "une-autre-cle-des-jetons-personnels-0123456789ab")
    r = env.get("/api/connections/1/nodes")
    assert r.status_code == 503 and r.json()["detail"] == KEY_DETAIL and pve.calls == [] and KEY not in r.text
    monkeypatch.setattr(get_settings(), "kaji_token_key", "")
    assert env.get("/api/connections/1/nodes").status_code == 503


def test_typed_credentials_are_respected_even_when_they_match_an_existing_connection(env, pve):
    """« Tester la connexion » avec les identifiants SAISIS ne doit pas être remplacé par le jeton personnel de la connexion du même nom."""
    put(env)
    pve.calls.clear()
    r = env.post("/api/connections/test", json={"name": "x", "host": "10.0.0.5", "port": 8006, "user": SHARED[0], "token_id": SHARED[1],
                                                 "token_secret": "autre-secret-saisi-0009", "verify_ssl": False})
    assert r.status_code == 200 and r.json()["ok"] is False                           # le secret saisi est mauvais : refusé, pas remplacé
    assert pve.calls and all(c[0].startswith("REFUSÉ:kaji@pve!kaji") for c in pve.calls) and not any("alice" in c[0] for c in pve.calls)


def test_ticket_and_anonymous_clients_never_get_a_personal_token(env):
    """Même quand tous les autres arguments désignent la connexion enregistrée ET que l'utilisateur a un jeton personnel : une session par ticket reste une session par ticket."""
    put(env)
    uid = rows()[0].user_id
    seen = []
    factory = personal_factory(lambda **kw: seen.append(kw) or object(), uid)
    stored = dict(host="10.0.0.5", port=8006, user=SHARED[0], token_id=SHARED[1], token_secret=SHARED[2], verify_ssl=False)
    factory(**stored, ticket="T", csrf="C")
    factory(**stored, anonymous=True)
    assert seen == [{**stored, "ticket": "T", "csrf": "C"}, {**stored, "anonymous": True}]           # intacts : ni le compte ni le jeton d'Alice
    seen.clear()
    factory(**stored)
    assert seen[0]["user"] == "alice@pve" and seen[0]["token_id"] == "perso" and seen[0]["token_secret"] == ALICE[2]       # sans ticket, le jeton personnel est bien choisi


# ------------------------------------------------------------------ nettoyage et flux temps réel

def test_deleting_a_user_or_a_connection_removes_their_personal_tokens(env):
    bob = make_user(env, "bob")
    put(env); put(bob, BOB)
    bob_id = next(u["id"] for u in env.get("/api/kaji-users").json() if u["username"] == "bob")
    assert env.delete(f"/api/kaji-users/{bob_id}", params={"confirm": "true", "name": "bob"}).status_code == 200
    assert {r.pve_user for r in rows()} == {"alice@pve"}
    assert env.delete("/api/connections/1").status_code == 204 and rows() == []


def test_the_live_stream_is_shared_only_while_everyone_uses_the_shared_token(env, monkeypatch):
    from app.routers import live
    uid = next(u for u in [1])                                         # Alice, premier compte
    base = lambda **kw: None                                           # noqa: E731
    factory = personal_factory(base, uid)
    assert factory.scope_for(1) == 0                                    # pas de jeton personnel : flux commun, comme avant
    put(env)
    assert factory.scope_for(1) == uid and factory.scope_for(2) == 0    # son jeton : flux à part, et seulement pour CETTE connexion
    keys = []

    async def fake_stream(h, key, fetch, **kw):
        keys.append(key)
        yield "x"
    monkeypatch.setattr(live, "stream", fake_stream)
    env.get("/api/connections/1/events")
    make_user(env, "bob").get("/api/connections/1/events")
    assert keys == [(1, uid), 1]                                        # Alice : (connexion, utilisateur) ; Bob : la clé commune
    monkeypatch.setattr(get_settings(), "kaji_require_user_token", True)
    assert personal_factory(base, 99).scope_for(1) == 99                  # jeton exigé : jamais de flux commun


def test_the_table_and_the_model_hold_no_plain_secret(env):
    put(env)
    with Session(get_engine()) as db:
        raw = json.dumps([(r.pve_user, r.token_id, r.secret_enc) for r in db.scalars(select(UserToken))])
        assert ALICE[2] not in raw and KEY not in raw
        assert ALICE[2] not in json.dumps([(u.username, u.password_hash) for u in db.scalars(select(AdminUser))])
