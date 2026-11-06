import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": "s3cr3t-value-xyz"}

DATA = {
    "/api2/json/cluster/status": [
        {"type": "cluster", "name": "lab", "quorate": 1},
        {"type": "node", "name": "pve2", "online": 1, "ip": "10.0.0.6"},
        {"type": "node", "name": "pve1", "online": 0, "ip": "10.0.0.5"},
    ],
    "/api2/json/nodes": [
        {"node": "pve2", "status": "online", "cpu": 0.1, "maxcpu": 4, "mem": 1, "maxmem": 8, "uptime": 5},
        {"node": "pve1", "status": "offline"},
    ],
    "/api2/json/cluster/resources": {
        "vm": [
            {"type": "lxc", "vmid": 200, "name": "ct", "node": "pve2", "status": "stopped"},
            {"type": "qemu", "vmid": 100, "name": "vm", "node": "pve1", "status": "running",
             "cpu": 0.5, "maxcpu": 2, "mem": 1024, "maxmem": 2048, "uptime": 60, "template": 0},
            {"type": "node", "node": "pve1"},
        ],
        "storage": [
            {"type": "storage", "storage": "local", "node": "pve1", "plugintype": "dir",
             "status": "available", "disk": 1, "maxdisk": 10, "content": "iso,backup"},
        ],
    },
}
FAIL = {}


def _handler(request: httpx.Request) -> httpx.Response:
    if FAIL.get("code"):
        return httpx.Response(FAIL["code"], json={"data": None})
    if FAIL.get("timeout"):
        raise httpx.ReadTimeout("t")
    d = DATA[request.url.path]
    if isinstance(d, dict):
        d = d[request.url.params["type"]]
    return httpx.Response(200, json={"data": d})


@pytest.fixture
def api(client):
    FAIL.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler))
    )
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def test_requires_auth(client):
    assert client.get("/api/connections/1/nodes").status_code == 401


def test_unknown_connection(api):
    assert api[0].get("/api/connections/999/nodes").status_code == 404


def test_cluster_status(api):
    c, cid = api
    r = c.get(f"/api/connections/{cid}/cluster/status").json()
    assert r["name"] == "lab" and r["quorate"] is True
    assert [n["name"] for n in r["nodes"]] == ["pve2", "pve1"]
    assert r["nodes"][1]["online"] is False


def test_nodes_sorted(api):
    c, cid = api
    assert [n["node"] for n in c.get(f"/api/connections/{cid}/nodes").json()] == ["pve1", "pve2"]


def test_guests_unified_and_filtered(api):
    c, cid = api
    g = c.get(f"/api/connections/{cid}/guests").json()
    assert [(x["vmid"], x["type"]) for x in g] == [(100, "qemu"), (200, "lxc")]
    assert g[1]["cpu"] == 0 and g[1]["template"] is False
    only = c.get(f"/api/connections/{cid}/guests", params={"node": "pve2"}).json()
    assert [x["vmid"] for x in only] == [200]


def test_storages(api):
    c, cid = api
    assert c.get(f"/api/connections/{cid}/storages").json()[0]["storage"] == "local"


@pytest.mark.parametrize("code,expected", [(401, 502), (403, 502), (500, 502)])
def test_proxmox_errors_mapped(api, code, expected):
    c, cid = api
    FAIL["code"] = code
    r = c.get(f"/api/connections/{cid}/nodes")
    assert r.status_code == expected and "s3cr3t-value-xyz" not in r.text


def test_timeout_mapped_to_504(api):
    c, cid = api
    FAIL["timeout"] = True
    assert c.get(f"/api/connections/{cid}/nodes").status_code == 504
