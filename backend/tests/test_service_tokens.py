"""Jeton de SERVICE d'une connexion pour le planificateur et les alertes (lot #441, option A du cadrage).

Le faux Proxmox authentifie chaque jeton, note qui appelle et sert `/access/permissions` : on vérifie qu'un jeton qui détient un droit en trop (Administrator…) est REFUSÉ, que le
planificateur agit avec le jeton de service et non le jeton partagé, et que l'expiration, un refus de Proxmox, une clé changée ou `KAJI_REQUIRE_SERVICE_TOKEN` donnent une erreur claire.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import tokenkey
from app.config import get_settings
from app.crypto import encrypt
from app.db import get_engine
from app.deps import SERVICE_EXPIRED_DETAIL, SERVICE_MISSING_DETAIL, SERVICE_REFUSED_DETAIL, KEY_DETAIL, get_base_client_factory, service_factory
from app.main import app
from app.models import AuditLog, Connection, ScheduledAction, ServiceToken
from app.proxmox import ProxmoxClient
from app.scheduler import run_due
from tests.test_user_tokens import ALICE, BOB, KEY, PWD, SHARED, FakePve, login, make_user

SVC = ("svc-kaji@pve", "sched", "secret-service-0004")
GOOD = {"Sys.Audit": 1, "VM.Audit": 1, "VM.PowerMgmt": 1, "VM.Snapshot": 1, "Datastore.Audit": 1, "Pool.Audit": 1}
MON_0730_PARIS = datetime(2026, 11, 16, 6, 30, tzinfo=timezone.utc)
URL = "/api/connections/1/service-token"


class ServicePve(FakePve):
    """Ajoute les droits des jetons (`/access/permissions`) et un nœud minimal pour le planificateur."""

    def __init__(self):
        super().__init__()
        self.known["svc-kaji@pve!sched"] = SVC[2]
        self.perms: dict[str, dict | int] = {"svc-kaji@pve!sched": {"/": dict(GOOD)}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        ident, _, secret = auth.removeprefix("PVEAPIToken=").partition("=")
        path = request.url.path.removeprefix("/api2/json")
        if self.known.get(ident) == secret and ident not in self.revoked:
            if path == "/access/permissions":
                self.calls.append((ident, path))
                what = self.perms.get(ident, {"/": {"VM.Audit": 1}})
                return httpx.Response(what, json={"data": None}) if isinstance(what, int) else httpx.Response(200, json={"data": what})
            if path == "/nodes/n1/qemu/115/status/current":
                self.calls.append((ident, path))
                return httpx.Response(200, json={"data": {"status": "stopped"}})
            if path == "/nodes/n1/qemu/115/status/start":
                self.calls.append((ident, path))
                return httpx.Response(200, json={"data": "UPID:n1:0001:0002:0003:qmstart:115:svc:"})
            if path.startswith("/nodes/n1/tasks/") and path.endswith("/status"):
                self.calls.append((ident, path))
                return httpx.Response(200, json={"data": {"status": "stopped", "exitstatus": "OK"}})
        return super().handler(request)


@pytest.fixture
def pve():
    return ServicePve()


@pytest.fixture
def env(client, pve, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "kaji_token_key", KEY)
    monkeypatch.setattr(s, "kaji_token_key_file", "")
    monkeypatch.setattr(s, "kaji_token_key_previous", "")
    monkeypatch.setattr(s, "kaji_require_service_token", False)
    monkeypatch.setattr(s, "kaji_service_token_max_days", 365)
    app.dependency_overrides[get_base_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(pve.handler)))
    client.post("/api/auth/setup", json={"username": "alice", "password": PWD})
    with Session(get_engine()) as db:
        db.add(Connection(name="lab", host="10.0.0.5", port=8006, user=SHARED[0], token_id=SHARED[1], token_secret_enc=encrypt(s.kaji_secret_key, SHARED[2]), verify_ssl=False))
        db.commit()
    yield client
    app.dependency_overrides.pop(get_base_client_factory, None)


def body(identity=SVC, **extra) -> dict:
    return {"pve_user": identity[0], "token_id": identity[1], "secret": identity[2], **extra}


def put(c: TestClient, identity=SVC, **extra):
    return c.put(URL, json=body(identity, **extra))


def rows() -> list[ServiceToken]:
    with Session(get_engine()) as db:
        return list(db.scalars(select(ServiceToken)))


def audit_text() -> str:
    with Session(get_engine()) as db:
        return json.dumps([(a.action, a.target, a.status, a.detail) for a in db.scalars(select(AuditLog))], ensure_ascii=False)


def base_for(pve):
    return lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(pve.handler))


def shared_params() -> dict:
    return dict(host="10.0.0.5", port=8006, user=SHARED[0], token_id=SHARED[1], token_secret=SHARED[2], verify_ssl=False)


def call_nodes(factory) -> None:
    async def go():
        c = factory(**shared_params())
        try:
            await c.get("/nodes")
        finally:
            await c.aclose()
    asyncio.run(go())


# ------------------------------------------------------------------ enregistrement : droits limités

def test_a_token_limited_to_what_the_scheduler_needs_is_registered_encrypted_and_never_returned(env, pve):
    r = put(env)
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["state"], v["pve_user"], v["token_id"], v["verified"], v["lacks"], v["created_by"]) == ("ok", "svc-kaji@pve", "sched", True, [], "alice")
    assert SVC[2] not in r.text and "secret" not in v
    assert ("svc-kaji@pve!sched", "/access/permissions") in pve.calls                       # droits lus AVEC le jeton lui-même
    (row,) = rows()
    assert SVC[2] not in row.secret_enc and tokenkey.decrypt(row.secret_enc, [KEY]) == SVC[2]
    audit = audit_text()
    assert "service-token-set" in audit and "droits limités vérifiés" in audit and SVC[2] not in audit and KEY not in audit
    got = env.get(URL).json()
    assert got["enabled"] and not got["required"] and got["max_days"] == 365 and got["token"]["state"] == "ok" and "Sys.Audit" in got["allowed_privileges"]
    assert SVC[2] not in json.dumps(got)


@pytest.mark.parametrize("extra", [
    {"Sys.Modify": 1}, {"Permissions.Modify": 1}, {"VM.Allocate": 1}, {"Sys.Console": 1}, {"User.Modify": 1, "Sys.PowerMgmt": 1},
])
def test_a_token_with_any_right_beyond_the_needed_ones_is_refused_and_the_extra_rights_are_named(env, pve, extra):
    pve.perms["svc-kaji@pve!sched"] = {"/": {**GOOD, **extra}}
    r = put(env)
    assert r.status_code == 422 and rows() == [] and SVC[2] not in r.text + audit_text()
    for priv in extra:
        assert priv in r.json()["detail"]
    assert "jamais Administrator" in r.json()["detail"]
    assert "service-token-set" in audit_text() and "error" in audit_text()


def test_a_forbidden_privilege_on_any_path_counts_not_only_on_the_root(env, pve):
    pve.perms["svc-kaji@pve!sched"] = {"/": dict(GOOD), "/vms/115": {"VM.Config.Disk": 1}, "/storage": {"Datastore.Allocate": 0}}
    r = put(env)
    assert r.status_code == 422 and "VM.Config.Disk" in r.text and "Datastore.Allocate" in r.text and rows() == []        # même « non propagé » : le droit existe


def test_rights_that_cannot_be_read_mean_no_token(env, pve):
    for odd in (403, 404, {}, {"/": "oups"}, {"/": {"VM.Audit": 1}, "/vms": ["pas", "un", "dict"]}):
        pve.perms["svc-kaji@pve!sched"] = odd
        r = put(env)
        assert r.status_code == 422 and "impossible de vérifier" in r.text and rows() == [], odd


def test_a_token_lacking_the_minimum_is_accepted_but_the_missing_rights_are_reported(env, pve):
    pve.perms["svc-kaji@pve!sched"] = {"/": {"VM.PowerMgmt": 1}}
    r = put(env)
    assert r.status_code == 200 and r.json()["lacks"] == ["Sys.Audit", "VM.Audit"]


def test_the_common_token_rules_apply_to_service_tokens_too(env, pve):
    for identity, needle in ((("root@pam", "x", "secret-root-0000"), "root@pam"), (SHARED, "PARTAGÉ")):
        r = put(env, identity)
        assert r.status_code == 422 and needle in r.json()["detail"] and rows() == []
    assert put(env, privsep=False).status_code == 422
    pve.info["svc-kaji@pve!sched"] = {"privsep": 1, "expire": int((datetime.now(timezone.utc) + timedelta(days=500)).timestamp())}
    r = put(env)
    assert r.status_code == 422 and "au plus 365 jours" in r.text and "KAJI_SERVICE_TOKEN_MAX_DAYS" in r.text and rows() == []
    pve.info["svc-kaji@pve!sched"] = {"privsep": 1, "expire": 0}
    assert put(env).status_code == 422 and rows() == []


def test_without_the_separate_key_nothing_is_stored(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "kaji_token_key", "")
    assert env.get(URL).json()["enabled"] is False
    r = put(env)
    assert r.status_code == 409 and "KAJI_TOKEN_KEY" in r.text and rows() == []


def test_only_administrators_write_everybody_reads_and_the_replacement_clears_a_refusal(env, pve):
    operator, viewer = make_user(env, "olivier", "operator"), make_user(env, "victor", "viewer")
    for c in (operator, viewer):
        assert put(c).status_code == 403 and c.delete(URL).status_code == 403 and rows() == []
        assert c.get(URL).status_code == 200 and "token" in c.get(URL).json()
    assert put(env).status_code == 200
    with Session(get_engine()) as db:
        row = db.scalars(select(ServiceToken)).one(); row.refused_at = datetime.now(timezone.utc); db.commit()
    assert env.get(URL).json()["token"]["state"] == "refused"
    assert put(env).status_code == 200 and rows()[0].refused_at is None and len(rows()) == 1
    assert viewer.delete(URL).status_code == 403 and env.delete(URL).status_code == 204 and rows() == [] and env.delete(URL).status_code == 404
    assert env.get("/api/connections/99/service-token").status_code == 404 and TestClient(app).get(URL).status_code == 401


def test_deleting_the_connection_removes_its_service_token(env):
    put(env)
    assert env.delete("/api/connections/1").status_code == 204 and rows() == []


# ------------------------------------------------------------------ ce que les tâches de fond utilisent

def test_background_calls_use_the_service_token_and_users_keep_their_own_path(env, pve):
    put(env)
    pve.calls.clear()
    call_nodes(service_factory(base_for(pve)))
    assert pve.calls == [("svc-kaji@pve!sched", "/nodes")]                                       # PAS le jeton partagé
    pve.calls.clear()
    assert env.get("/api/connections/1/nodes").status_code == 200
    assert pve.calls == [("kaji@pve!kaji", "/nodes")]                                           # un utilisateur sans jeton personnel : le jeton partagé, inchangé


def test_the_scheduler_acts_with_the_service_token_end_to_end(env, pve):
    put(env)
    with Session(get_engine()) as db:
        db.add(ScheduledAction(conn_id=1, node="n1", gtype="qemu", vmid=115, action="start", days="0", time="07:30", timezone="Europe/Paris", enabled=True, created_by="alice"))
        db.commit()
    pve.calls.clear()
    with Session(get_engine()) as db:
        done = asyncio.run(run_due(db, service_factory(base_for(pve)), MON_0730_PARIS))
    assert done and done[0]["status"] == "ok", done
    assert {c[0] for c in pve.calls} == {"svc-kaji@pve!sched"} and any(p.endswith("/status/start") for _, p in pve.calls)      # démarrage fait par le jeton de service


def test_without_a_service_token_background_calls_fall_back_to_the_shared_one_unless_required(env, pve, monkeypatch):
    pve.calls.clear()
    call_nodes(service_factory(base_for(pve)))
    assert pve.calls == [("kaji@pve!kaji", "/nodes")]                                           # comportement historique
    monkeypatch.setattr(get_settings(), "kaji_require_service_token", True)
    pve.calls.clear()
    with pytest.raises(Exception) as e:
        call_nodes(service_factory(base_for(pve)))
    assert getattr(e.value, "detail", "") == SERVICE_MISSING_DETAIL and pve.calls == []
    put(env)
    pve.calls.clear(); call_nodes(service_factory(base_for(pve)))
    assert pve.calls == [("svc-kaji@pve!sched", "/nodes")]


def test_an_expired_refused_or_unreadable_service_token_is_an_explicit_error_never_a_silent_fallback(env, pve, monkeypatch):
    put(env)
    with Session(get_engine()) as db:
        row = db.scalars(select(ServiceToken)).one(); row.expires_at = datetime.now(timezone.utc) - timedelta(days=1); db.commit()
    pve.calls.clear()
    with pytest.raises(Exception) as e:
        call_nodes(service_factory(base_for(pve)))
    assert e.value.detail == SERVICE_EXPIRED_DETAIL and pve.calls == []
    put(env)                                                                                     # remplacé : de nouveau valable
    pve.revoked.add("svc-kaji@pve!sched")
    with pytest.raises(httpx.HTTPStatusError):
        call_nodes(service_factory(base_for(pve)))                                               # Proxmox répond 401 : le jeton est marqué
    assert rows()[0].refused_at is not None
    pve.calls.clear()
    with pytest.raises(Exception) as e:
        call_nodes(service_factory(base_for(pve)))
    assert e.value.detail == SERVICE_REFUSED_DETAIL and pve.calls == []                          # puis bloqué sans appeler Proxmox
    pve.revoked.clear(); put(env)
    monkeypatch.setattr(get_settings(), "kaji_token_key", "une-autre-cle-des-jetons-personnels-0123456789ab")
    with pytest.raises(Exception) as e:
        call_nodes(service_factory(base_for(pve)))
    assert e.value.detail == KEY_DETAIL and SVC[2] not in str(e.value.detail)


def test_service_refusal_message_differs_from_the_personal_one(env, pve):
    from app.routers.cluster import http_error
    from app.deps import REFUSED_DETAIL, PersonalTokenRefused, ServiceTokenRefused
    req, resp = httpx.Request("GET", "https://x/"), httpx.Response(401)
    assert http_error(ServiceTokenRefused("x", request=req, response=resp)).detail == SERVICE_REFUSED_DETAIL
    assert http_error(PersonalTokenRefused("x", request=req, response=resp)).detail == REFUSED_DETAIL


def test_typed_credentials_ticket_and_unknown_hosts_never_get_the_service_token(env, pve):
    put(env)
    seen = []
    factory = service_factory(lambda **kw: seen.append(kw) or object())
    factory(**{**shared_params(), "token_secret": "secret-saisi-autre-0009"})                  # secret saisi : respecté
    factory(**shared_params(), ticket="T", csrf="C")
    factory(**{**shared_params(), "host": "10.9.9.9"})                                           # autre hôte : aucune connexion enregistrée
    assert [k["token_id"] for k in seen] == ["kaji", "kaji", "kaji"] and seen[0]["token_secret"] == "secret-saisi-autre-0009"
    seen.clear(); factory(**shared_params())
    assert seen[0]["user"] == "svc-kaji@pve" and seen[0]["token_id"] == "sched" and seen[0]["token_secret"] == SVC[2]


# ------------------------------------------------------------------ branchement, rotation, sauvegarde

def test_the_real_scheduler_loop_is_started_with_the_service_aware_factory(env, monkeypatch):
    """Le test qui manquait : `main.py` doit passer la fabrique de SERVICE au planificateur (sinon tout ce qui précède ne servirait à rien en production)."""
    import app.proxmox as proxmox
    import app.scheduler as scheduler
    put(env)
    got, built = {}, []

    async def fake_loop(factory, session_factory, *a, **k):
        got["factory"] = factory
        await asyncio.sleep(3600)
    monkeypatch.setattr(scheduler, "loop", fake_loop)
    monkeypatch.setattr(proxmox, "ProxmoxClient", lambda **kw: built.append(kw) or object())        # ce que main.py enveloppe au démarrage
    monkeypatch.setattr(get_settings(), "kaji_scheduler", True)
    with TestClient(app):
        for _ in range(50):
            if "factory" in got:
                break
            import time; time.sleep(0.02)
        got["factory"](**shared_params())
    assert built and built[0]["token_id"] == "sched" and built[0]["user"] == "svc-kaji@pve" and built[0]["token_secret"] == SVC[2]       # jeton de service, pas le partagé


def test_service_tokens_are_rotated_with_the_separate_key(env):
    from app.tokenrotate import rotate_all
    old, new = "ancienne-cle-des-jetons-de-service-0123456789ab", "nouvelle-cle-des-jetons-de-service-0123456789ab"
    with Session(get_engine()) as db:
        db.add(ServiceToken(conn_id=7, pve_user="svc@pve", token_id="s", secret_enc=tokenkey.encrypt(SVC[2], [old]), expires_at=datetime.now(timezone.utc) + timedelta(days=30), verified=True, created_by="alice"))
        db.commit()
    with Session(get_engine()) as db:
        res = rotate_all(db, [new, old])
    assert (res.total, res.rotated) == (1, 1)
    with Session(get_engine()) as db:
        blob = db.scalars(select(ServiceToken)).one().secret_enc
    assert tokenkey.decrypt(blob, [new]) == SVC[2] and not tokenkey.readable(blob, [old])


def test_verify_checks_service_tokens_on_a_database_file(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from app.backup import verify
    from app.migrations import run_migrations
    from tests.test_backup_restore import KEY as SECRET_KEY, make_db
    path = make_db(tmp_path / "kaji.db")
    other = "une-autre-cle-de-service-0123456789abcdef-xyz"
    engine = create_engine(URL.create("sqlite", database=str(path)))
    run_migrations(engine)
    with Session(engine) as db:
        db.add(ServiceToken(conn_id=1, pve_user="svc@pve", token_id="s", secret_enc=tokenkey.encrypt(SVC[2], [KEY]), expires_at=datetime.now(timezone.utc) + timedelta(days=30), verified=True, created_by="a"))
        db.commit()
    engine.dispose()
    rep = verify(path, SECRET_KEY, [KEY])
    assert rep.ok and rep.service_tokens == (1, 1) and "Jetons de service : 1 ; déchiffrés : 1/1" in rep.render() and SVC[2] not in rep.render()
    bad = verify(path, SECRET_KEY, [other])
    assert not bad.ok and bad.service_tokens == (0, 1) and "jeton(s) de service illisible(s)" in bad.render()
    none = verify(path, SECRET_KEY, [])
    assert not none.ok and "jeton(s) de service dans cette base" in none.render()
