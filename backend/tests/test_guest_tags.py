import httpx
import pytest

from app import tagspec as T
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, request.content.decode()))
    if request.method == "GET" and p == "/cluster/resources":
        return httpx.Response(200, json={"data": [{"type": "qemu", "vmid": 100, "name": "a", "node": "enzo", "status": "running", "tags": "Web;prod, db;;bad tag!;x" + "y" * 40},
                                                  {"type": "lxc", "vmid": 101, "node": "enzo", "tags": 5}, {"type": "qemu", "vmid": 102, "node": "enzo"}]})
    if request.method == "PUT" and p.endswith("/config"):
        sent = set(httpx.QueryParams(request.content.decode()).keys())
        if sent not in ({"tags"}, {"delete"}):                       # schéma : uniquement tags, ou delete=tags
            return httpx.Response(400, json={"data": None, "message": "Parameter verification failed."})
        if ST.get("fail"):
            return httpx.Response(ST["fail"], json={"data": None, "message": SECRET})
        return httpx.Response(200, json={"data": None})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def put(c, cid, tags, gtype="qemu", vmid=100, node="enzo"):
    return c.put(f"/api/connections/{cid}/guests/{node}/{gtype}/{vmid}/tags", json={"tags": tags})


def writes():
    return [x for x in CALLS if x[0] == "PUT"]


def test_guests_list_exposes_clean_sorted_tags(api):
    c, cid = api
    g = {x["vmid"]: x for x in c.get(f"/api/connections/{cid}/guests").json()}
    # « bad tag! » se coupe aux espaces : « bad » est valide, « tag! » (point d'exclamation) et la chaîne de 41 caractères sont écartés
    assert g[100]["tags"] == ["bad", "db", "prod", "web"]            # minuscules, triées, sans doublon
    assert g[101]["tags"] == [] and g[102]["tags"] == []             # illisible ou absent : liste vide


def test_set_tags_sends_only_tags(api):
    c, cid = api
    r = put(c, cid, ["Web", "prod", "web"])
    assert r.status_code == 200 and r.json() == {"tags": ["prod", "web"]}
    assert writes() == [("PUT", "/nodes/enzo/qemu/100/config", "tags=prod%3Bweb")]


def test_empty_list_deletes_the_option(api):
    c, cid = api
    assert put(c, cid, []).status_code == 200
    assert writes() == [("PUT", "/nodes/enzo/qemu/100/config", "delete=tags")]


def test_lxc_path(api):
    c, cid = api
    assert put(c, cid, ["a"], gtype="lxc", vmid=101).status_code == 200 and writes()[0][1] == "/nodes/enzo/lxc/101/config"


@pytest.mark.parametrize("tag", ["", " ", "a b", "a;b", "a,b", "-a", ".a", "a/b", "é", "x" * 33, "a\nb", "a=b", "<b>"])
def test_invalid_tag_refused(api, tag):
    c, cid = api
    assert put(c, cid, ["ok", tag]).status_code == 422 and not writes()


def test_too_many_tags_refused(api):
    c, cid = api
    assert put(c, cid, [f"t{i}" for i in range(21)]).status_code == 422 and not writes()
    assert put(c, cid, [f"t{i}" for i in range(20)]).status_code == 200


def test_body_cannot_add_other_options(api):
    c, cid = api
    r = c.put(f"/api/connections/{cid}/guests/enzo/qemu/100/tags", json={"tags": ["a"], "onboot": 1, "delete": "net0", "memory": 1})
    assert r.status_code == 200 and writes()[0][2] == "tags=a"


@pytest.mark.parametrize("path", ["enzo/vm/100", "enzo/qemu/99", "enzo/qemu/abc", "a;b/qemu/100", "enzo/qemu/1000000000"])
def test_path_validated(api, path):
    c, cid = api
    assert c.put(f"/api/connections/{cid}/guests/{path}/tags", json={"tags": ["a"]}).status_code in (404, 422) and not writes()


def test_requires_login(api):
    c, cid = api
    c.post("/api/auth/logout")
    assert put(c, cid, ["a"]).status_code == 401 and not writes()


def test_audit_success_and_error_without_secret(api):
    c, cid = api
    put(c, cid, ["a"])
    ST["fail"] = 403
    assert put(c, cid, ["b"]).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("guest-tags", "ok"), ("guest-tags", "error")]
    assert log[0]["target"] == "qemu/100@enzo" and SECRET not in c.get("/api/audit").text


def test_parse_tags_unit():
    assert T.parse_tags("B;a, c") == ["a", "b", "c"] and T.parse_tags(None) == [] and T.parse_tags(["a"]) == []
    assert len(T.parse_tags(";".join(f"t{i}" for i in range(100)))) == T.MAX_TAGS * 2
