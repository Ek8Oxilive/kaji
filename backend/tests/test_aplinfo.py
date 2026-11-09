"""Téléchargement d'un modèle LXC du catalogue (lot #147) : faux Proxmox STRICT. RIEN n'a tourné sur un vrai cluster."""
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:download:local:kaji@pve!kaji:"
ALPINE = "alpine-3.22-default_20250617_amd64.tar.xz"
CALLS: list[dict] = []
ST: dict = {}


def catalogue():
    return [{"type": "lxc", "template": ALPINE, "os": "alpine", "section": "system"},
            {"type": "lxc", "template": "debian-12-standard_12.12-1_amd64.tar.zst", "section": "system"},
            {"type": "openvz", "template": "vieux-modele.tar.gz"}]


def _json(code, data):
    return httpx.Response(code, json={"data": data})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
    CALLS.append({"method": request.method, "path": p, "query": query, "form": form})
    if request.method == "GET" and p == "/nodes/enzo/aplinfo":
        return _json(400, None) if query else _json(200, ST.get("catalogue", catalogue()))
    if request.method == "GET" and p == "/nodes/enzo/storage":
        return _json(400, None) if set(query) - {"content"} or query.get("content") != "vztmpl" else _json(
            200, ST.get("storages", [{"storage": "local", "active": 1}, {"storage": "inactif", "active": 0}]))
    if request.method == "GET" and p == "/nodes/enzo/storage/local/content":
        return _json(400, None) if set(query) - {"content"} or query.get("content") != "vztmpl" else _json(200, ST.get("present", []))
    if request.method == "POST" and p == "/nodes/enzo/aplinfo":
        if ST.get("fail"):
            return _json(ST["fail"], None)
        return _json(400, None) if set(form) != {"storage", "template"} or query else _json(200, UPID)
    return _json(404, None)


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, node="enzo"):
    return f"/api/connections/{cid}/nodes/{node}/aplinfo"


def writes():
    return [c for c in CALLS if c["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()


def test_requires_auth(client):
    assert client.post("/api/connections/1/nodes/enzo/aplinfo", json={"storage": "local", "template": ALPINE}).status_code == 401


def test_downloads_catalogue_template_with_exact_call_and_audit(api):
    c, cid = api
    r = c.post(u(cid), json={"storage": "local", "template": ALPINE, "url": "http://evil/x", "checksum": "abc"})
    assert r.status_code == 202 and r.json()["upid"] == UPID
    assert [(w["path"], w["form"]) for w in writes()] == [("/nodes/enzo/aplinfo", {"storage": "local", "template": ALPINE})]   # rien d'autre transmis
    last = audit(c)[0]
    assert (last["action"], last["status"], last["upid"]) == ("template-download", "started", UPID)


@pytest.mark.parametrize("template", ["../x", "debian-99", "a/b", "..", "", ALPINE + " ", "vieux-modele.tar.gz", "x" * 300, ALPINE.upper()])
def test_template_outside_catalogue_or_malformed_is_refused_422_without_write(api, template):
    c, cid = api
    r = c.post(u(cid), json={"storage": "local", "template": template})
    assert r.status_code == 422 and writes() == []
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("template-download", "error")


@pytest.mark.parametrize("template", ["../x", "a/b", "a..b", "", " x", "x y", "é", "x" * 256, "-x"])
def test_malformed_template_name_is_refused_before_any_proxmox_call(api, template):
    c, cid = api
    assert c.post(u(cid), json={"storage": "local", "template": template}).status_code == 422 and CALLS == []


@pytest.mark.parametrize("storage", ["../local", "lo cal", "-local", "", "x" * 65, "local;ls"])
def test_malformed_storage_refused_without_any_call(api, storage):
    c, cid = api
    assert c.post(u(cid), json={"storage": storage, "template": ALPINE}).status_code == 422 and CALLS == []


@pytest.mark.parametrize("storage", ["local-lvm", "inactif", "absent"])
def test_storage_must_accept_vztmpl_and_be_active(api, storage):
    c, cid = api
    r = c.post(u(cid), json={"storage": storage, "template": ALPINE})
    assert r.status_code == 422 and writes() == []


def test_already_present_is_409_without_write(api):
    c, cid = api
    ST["present"] = [{"volid": f"local:vztmpl/{ALPINE}", "content": "vztmpl"}]
    r = c.post(u(cid), json={"storage": "local", "template": ALPINE})
    assert r.status_code == 409 and writes() == []
    assert (audit(c)[0]["status"]) == "error"


def test_other_present_template_does_not_block(api):
    c, cid = api
    ST["present"] = [{"volid": "local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst"}]
    assert c.post(u(cid), json={"storage": "local", "template": ALPINE}).status_code == 202


def test_unreadable_catalogue_refuses(api):
    c, cid = api
    ST["catalogue"] = {"pas": "une liste"}
    assert c.post(u(cid), json={"storage": "local", "template": ALPINE}).status_code == 422 and writes() == []


def test_missing_fields_422_without_leak(api):
    c, cid = api
    r = c.post(u(cid), json={"storage": "local"})
    assert r.status_code == 422 and CALLS == [] and SECRET not in r.text


@pytest.mark.parametrize("code", [403, 500])
def test_proxmox_error_is_translated_audited_without_leak(api, code):
    c, cid = api
    ST["fail"] = code
    r = c.post(u(cid), json={"storage": "local", "template": ALPINE})
    assert r.status_code == 502 and SECRET not in r.text and "10.0.0.5" not in r.text
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("template-download", "error") and SECRET not in c.get("/api/audit").text


def test_invalid_node_refused(api):
    c, cid = api
    assert c.post(u(cid, "-bad"), json={"storage": "local", "template": ALPINE}).status_code == 422 and CALLS == []
