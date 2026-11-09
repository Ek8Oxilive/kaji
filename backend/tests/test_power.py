"""Reset, suspendre, hiberner, reprendre, convertir en modèle (lot #146) : faux Proxmox STRICT. RIEN n'a tourné sur un vrai cluster.

Le faux n'accepte que les méthodes, chemins et paramètres des schémas Proxmox du ticket : tout autre paramètre répond 400.
"""
import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.routers import load_routers

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:qmreset:116:kaji@pve!kaji:"
SCHEMA = {  # chemin -> paramètres POST autorisés (schémas réels du ticket)
    "/nodes/enzo/qemu/118/status/reset": {"skiplock"},
    "/nodes/enzo/qemu/118/status/suspend": {"skiplock", "statestorage", "todisk"},
    "/nodes/enzo/qemu/118/status/resume": {"nocheck", "skiplock"},
    "/nodes/enzo/qemu/118/template": {"disk"},
    "/nodes/enzo/lxc/118/template": set(),
}
CALLS: list[dict] = []
STATE: dict = {}


def _json(code, body):
    return httpx.Response(code, json=body)


def _handler(request: httpx.Request) -> httpx.Response:
    from urllib.parse import parse_qs
    p = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
    CALLS.append({"method": request.method, "path": p, "form": form, "query": dict(request.url.params)})
    if request.method == "GET" and p.endswith("/status/current"):
        return _json(200, {"data": STATE.get("current", {"status": "running", "qmpstatus": "running"})})
    if request.method == "GET" and p.endswith("/config"):
        return _json(200, {"data": STATE.get("cfg", {"name": "kaji-sandbox", "hostname": "kaji-ct"})})
    if request.method == "POST" and p in SCHEMA:
        if STATE.get("fail"):
            return _json(STATE["fail"], {"data": None})
        if set(form) - SCHEMA[p] or request.url.params:
            return _json(400, {"data": None})
        return _json(200, {"data": None if p.startswith("/nodes/enzo/lxc") else UPID})
    return _json(404, {"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    STATE.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, op, gtype="qemu", vmid=118):
    return f"/api/connections/{cid}/guests/enzo/{gtype}/{vmid}/{op}"


def writes():
    return [c for c in CALLS if c["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()


def cur(status, qmp=None):
    STATE["current"] = {"status": status, **({"qmpstatus": qmp} if qmp else {})}


# ------------------------------------------------------------- routes

def test_requires_auth(client):
    for op in ("reset", "suspend", "hibernate", "resume", "template"):
        assert client.post(f"/api/connections/1/guests/enzo/qemu/118/{op}").status_code == 401


def test_routes_are_not_shadowed_by_generic_action():
    """Aucune de nos routes ne doit passer après `{action}` (ORDER = 90) : sinon la VM recevrait un 422 d'action inconnue."""
    routes = [r for router in load_routers() for r in router.routes]
    paths = [r.path for r in routes]
    generic = paths.index(next(p for p in paths if p.endswith("/{vmid}/{action}")))
    for op in ("reset", "suspend", "hibernate", "resume", "template"):
        assert paths.index(next(p for p in paths if p.endswith(f"/{op}") and "/guests/" in p)) < generic


def test_power_state_is_read_only_and_whitelisted(api):
    c, cid = api
    STATE["current"] = {"status": "running", "qmpstatus": "paused", "secret": SECRET, "lock": "x"}
    r = c.get(u(cid, "power"))
    assert r.status_code == 200 and r.json() == {"status": "running", "qmpstatus": "paused", "paused": True}
    assert SECRET not in r.text and writes() == []
    cur("running", "running")
    assert c.get(u(cid, "power")).json()["paused"] is False
    cur("stopped")
    assert c.get(u(cid, "power")).json() == {"status": "stopped", "qmpstatus": None, "paused": False}


def test_power_state_requires_auth(client):
    assert client.get("/api/connections/1/guests/enzo/qemu/118/power").status_code == 401


# ------------------------------------------------------------- reset

def test_reset_needs_confirm_and_calls_nothing(api):
    c, cid = api
    r = c.post(u(cid, "reset"))
    assert r.status_code == 400 and CALLS == []
    assert c.post(u(cid, "reset"), json={"confirm": "true"}).status_code == 422 and CALLS == []     # booléen strict
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("reset", "error")


def test_reset_runs_when_confirmed_with_exact_call(api):
    c, cid = api
    r = c.post(u(cid, "reset"), json={"confirm": True, "skiplock": True, "inconnu": 1})
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo", "action": "reset"}
    assert [(w["path"], w["form"]) for w in writes()] == [("/nodes/enzo/qemu/118/status/reset", {})]    # champs inconnus jamais transmis
    last = audit(c)[0]
    assert (last["action"], last["status"], last["upid"], last["target"]) == ("reset", "started", UPID, "qemu/118@enzo")


@pytest.mark.parametrize("state", [("stopped", "stopped"), ("running", "paused"), ("running", "suspended")])
def test_reset_refused_unless_running_and_nothing_written(api, state):
    c, cid = api
    cur(*state)
    assert c.post(u(cid, "reset"), json={"confirm": True}).status_code == 409 and writes() == []


def test_reset_is_for_vm_only(api):
    c, cid = api
    assert c.post(u(cid, "reset", "lxc"), json={"confirm": True}).status_code in (404, 405, 422) and writes() == []


# ------------------------------------------------------------- suspend / resume

def test_suspend_when_running_without_confirm(api):
    c, cid = api
    r = c.post(u(cid, "suspend"))
    assert r.status_code == 202 and [(w["path"], w["form"]) for w in writes()] == [("/nodes/enzo/qemu/118/status/suspend", {})]


@pytest.mark.parametrize("state", [("stopped", "stopped"), ("running", "paused"), ("running", "prelaunch")])
def test_suspend_refused_unless_running(api, state):
    c, cid = api
    cur(*state)
    assert c.post(u(cid, "suspend")).status_code == 409 and writes() == []


@pytest.mark.parametrize("state", [("running", "paused"), ("running", "suspended"), ("paused", None)])
def test_resume_allowed_when_paused(api, state):
    c, cid = api
    cur(*state)
    r = c.post(u(cid, "resume"))
    assert r.status_code == 202 and [(w["path"], w["form"]) for w in writes()] == [("/nodes/enzo/qemu/118/status/resume", {})]


@pytest.mark.parametrize("state", [("running", "running"), ("stopped", "stopped")])
def test_resume_refused_when_not_paused(api, state):
    c, cid = api
    cur(*state)
    assert c.post(u(cid, "resume")).status_code == 409 and writes() == []


# ------------------------------------------------------------- hibernate

def test_hibernate_needs_confirm(api):
    c, cid = api
    assert c.post(u(cid, "hibernate")).status_code == 400 and CALLS == []


def test_hibernate_sends_todisk_and_optional_storage(api):
    c, cid = api
    assert c.post(u(cid, "hibernate"), json={"confirm": True}).status_code == 202
    assert writes()[-1]["path"] == "/nodes/enzo/qemu/118/status/suspend" and writes()[-1]["form"] == {"todisk": "1"}
    assert c.post(u(cid, "hibernate"), json={"confirm": True, "statestorage": "local-lvm"}).status_code == 202
    assert writes()[-1]["form"] == {"todisk": "1", "statestorage": "local-lvm"}


@pytest.mark.parametrize("bad", ["../etc", "a b", "-x", "local;rm", "x" * 65, ""])
def test_hibernate_refuses_invalid_state_storage_without_write(api, bad):
    c, cid = api
    r = c.post(u(cid, "hibernate"), json={"confirm": True, "statestorage": bad})
    assert r.status_code == 422 and writes() == [] and (bad == "" or bad not in r.text)


def test_hibernate_refused_when_not_running(api):
    c, cid = api
    cur("stopped", "stopped")
    assert c.post(u(cid, "hibernate"), json={"confirm": True}).status_code == 409 and writes() == []


# ------------------------------------------------------------- template

def tpl(c, cid, gtype="qemu", **body):
    return c.post(u(cid, "template", gtype), json=body)


def test_template_vm_ok_with_confirm_and_exact_name(api):
    c, cid = api
    cur("stopped")
    r = tpl(c, cid, confirm=True, name="kaji-sandbox")
    assert r.status_code == 202 and r.json()["upid"] == UPID
    assert [(w["path"], w["form"]) for w in writes()] == [("/nodes/enzo/qemu/118/template", {})]
    last = audit(c)[0]
    assert (last["action"], last["status"], last["upid"]) == ("guest-template", "started", UPID)


def test_template_lxc_ok_returns_null_upid(api):
    c, cid = api
    cur("stopped")
    r = tpl(c, cid, "lxc", confirm=True, name="kaji-ct")
    assert r.status_code == 202 and r.json()["upid"] is None
    assert [w["path"] for w in writes()] == ["/nodes/enzo/lxc/118/template"]


def test_template_refused_without_confirm(api):
    c, cid = api
    cur("stopped")
    assert tpl(c, cid, name="kaji-sandbox").status_code == 400 and CALLS == []
    assert tpl(c, cid, confirm="oui", name="kaji-sandbox").status_code == 422 and CALLS == []


@pytest.mark.parametrize("name", ["", "autre", "Kaji-Sandbox", "kaji-sandbox ", "kaji-sandbo"])
def test_template_refused_with_wrong_name(api, name):
    c, cid = api
    cur("stopped")
    assert tpl(c, cid, confirm=True, name=name).status_code == 400 and writes() == []


def test_template_without_name_on_machine_without_name_is_refused(api):
    c, cid = api
    cur("stopped")
    STATE["cfg"] = {}
    assert tpl(c, cid, confirm=True, name="").status_code == 400 and writes() == []


@pytest.mark.parametrize("current", [{"status": "running"}, {"status": "running", "qmpstatus": "paused"}, {}])
def test_template_refused_unless_stopped(api, current):
    c, cid = api
    STATE["current"] = current
    assert tpl(c, cid, confirm=True, name="kaji-sandbox").status_code == 409 and writes() == []


def test_template_refused_when_already_a_template(api):
    c, cid = api
    cur("stopped")
    STATE["cfg"] = {"name": "kaji-sandbox", "template": 1}
    assert tpl(c, cid, confirm=True, name="kaji-sandbox").status_code == 409 and writes() == []


def test_template_refused_when_protection_option_set(api):
    c, cid = api
    cur("stopped")
    STATE["cfg"] = {"name": "kaji-sandbox", "protection": 1}
    r = tpl(c, cid, confirm=True, name="kaji-sandbox")
    assert r.status_code == 409 and writes() == []


def test_template_refused_for_kaji_protected_vmid_even_confirmed(api, monkeypatch):
    c, cid = api
    cur("stopped")
    monkeypatch.setattr("app.routers.power.get_settings", lambda: type("S", (), {"protected_vmids": {118}})())
    r = tpl(c, cid, confirm=True, name="kaji-sandbox")
    assert r.status_code == 403 and CALLS == []
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("guest-template", "error")


# ------------------------------------------------------------- erreurs et fuites

@pytest.mark.parametrize("code", [403, 500])
def test_proxmox_errors_are_translated_audited_and_do_not_leak(api, code):
    c, cid = api
    STATE["fail"] = code
    r = c.post(u(cid, "reset"), json={"confirm": True})
    assert r.status_code == 502 and SECRET not in r.text and "10.0.0.5" not in r.text
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("reset", "error") and SECRET not in c.get("/api/audit").text


def test_invalid_path_params_are_refused_without_call(api):
    c, cid = api
    assert c.post(f"/api/connections/{cid}/guests/enzo/qemu/99/reset", json={"confirm": True}).status_code == 422
    assert c.post(f"/api/connections/{cid}/guests/-bad/qemu/118/reset", json={"confirm": True}).status_code == 422
    assert CALLS == []
