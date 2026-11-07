import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.routers.cluster import _pool, shape_guests

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
RES = [
    {"type": "qemu", "vmid": 100, "name": "a", "node": "enzo", "status": "running", "pool": "kaji-test", "tags": "web;prod"},
    {"type": "lxc", "vmid": 101, "name": "b", "node": "enzo2", "status": "stopped"},                       # sans pool : la clé est absente chez Proxmox
    {"type": "qemu", "vmid": 102, "node": "enzo", "pool": "<script>"}, {"type": "qemu", "vmid": 103, "node": "enzo", "pool": 5},
    {"type": "qemu", "vmid": 104, "node": "enzo", "pool": "x" * 70}, {"type": "qemu", "vmid": 105, "node": "enzo", "pool": ""},
    {"type": "storage", "id": "storage/enzo/local", "pool": "ignoré"},
]


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/cluster/resources"):
        return httpx.Response(200, json={"data": RES})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def test_guests_carry_pool_tags_and_node(api):
    c, cid = api
    g = {x["vmid"]: x for x in c.get(f"/api/connections/{cid}/guests").json()}
    assert g[100]["pool"] == "kaji-test" and g[100]["tags"] == ["prod", "web"] and g[100]["node"] == "enzo"
    assert g[101]["pool"] is None and g[101]["tags"] == [] and g[101]["node"] == "enzo2"
    assert sorted(g) == [100, 101, 102, 103, 104, 105]                                                      # le stockage n'est pas une machine


@pytest.mark.parametrize("v", ["<script>", 5, None, "", "x" * 70, "a b", "a;b", "a/b", "-a", ["a"], {"a": 1}, "é", "a\n"])
def test_unexpected_pool_is_dropped(v):
    assert _pool(v) is None


@pytest.mark.parametrize("v", ["kaji-test", "a", "_x", "Pool.1", "x" * 64])
def test_valid_pool_is_kept(v):
    assert _pool(v) == v


def test_shape_is_tolerant():
    assert shape_guests([{"type": "qemu", "vmid": 1, "pool": 12}])[0]["pool"] is None
