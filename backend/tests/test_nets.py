from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.hardware import build_new_net, next_net_index, normalize, parse_boot_order
from app.main import app
from app.proxmox import ProxmoxClient

# ---------- fonctions pures ----------

def test_next_net_index_fills_gaps():
    assert next_net_index({}) == 0
    assert next_net_index({"net0": "x", "net2": "y"}) == 1
    with pytest.raises(ValueError):
        next_net_index({f"net{i}": "x" for i in range(32)})


def test_build_new_net_qemu_and_lxc():
    assert build_new_net(False, 1, bridge="vmbr0") == "virtio,bridge=vmbr0"
    assert build_new_net(False, 1, bridge="vmbr1", model="e1000", tag=20, firewall=True) == "e1000,bridge=vmbr1,tag=20,firewall=1"
    assert build_new_net(True, 1, bridge="vmbr0", ip="dhcp") == "name=eth1,bridge=vmbr0,type=veth,ip=dhcp"
    assert build_new_net(True, 0, bridge="vmbr0", ip="192.168.1.50/24", gateway="192.168.1.1") == \
        "name=eth0,bridge=vmbr0,type=veth,ip=192.168.1.50/24,gw=192.168.1.1"


@pytest.mark.parametrize("ip,gw", [("192.168.1.50", None), ("999.1.1.1/24", None), ("dhcp", "192.168.1.1"),
                                   ("192.168.1.50/24", "pas-une-ip"), ("1.1.1.1/24,ip=evil", None), ("a;b", None)])
def test_invalid_ip_or_gateway_rejected(ip, gw):
    with pytest.raises(ValueError):
        build_new_net(True, 0, bridge="vmbr0", ip=ip, gateway=gw)


def test_boot_order_parse_and_normalize():
    assert parse_boot_order("order=scsi0;ide2;net0") == ["scsi0", "ide2", "net0"]
    assert parse_boot_order("order=scsi0;evil;net0") == ["scsi0", "net0"] and parse_boot_order(None) == [] and parse_boot_order("cdn") == []
    n = normalize("qemu", {"boot": "order=scsi0;net0", "scsi0": "l:v,size=1G", "net0": "virtio=AA:AA:AA:AA:AA:AA,bridge=vmbr0"}, [])
    assert n["boot_order"] == ["scsi0", "net0"] and normalize("lxc", {"hostname": "x"}, [])["boot_order"] == []


# ---------- API ----------

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
QEMU = {"name": "sandbox", "memory": 256, "scsi0": "local-lvm:vm-115-disk-0,size=1G", "ide2": "none,media=cdrom",
        "net0": "virtio=BC:24:11:AA:BB:CC,bridge=vmbr0"}
LXC = {"hostname": "web", "rootfs": "local-lvm:vm-105-disk-0,size=8G", "net0": "name=eth0,bridge=vmbr0,hwaddr=AA:BB:CC:00:11:22,ip=dhcp"}
CFG: dict = {}
WRITES: list = []
FAIL: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    if FAIL.get("code"):
        return httpx.Response(FAIL["code"], json={"data": None})
    if request.method == "GET":
        return httpx.Response(200, json={"data": CFG["v"]})
    WRITES.append((request.method, request.url.path.removeprefix("/api2/json"), {k: v[0] for k, v in parse_qs(request.content.decode()).items()}))
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    WRITES.clear(); FAIL.clear(); CFG["v"] = QEMU
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, suffix="", gtype="qemu", vmid=115):
    return f"/api/connections/{cid}/guests/enzo/{gtype}/{vmid}/{suffix}".rstrip("/")


def test_requires_auth(client):
    assert client.post(u(1, "nets"), json={"bridge": "vmbr0"}).status_code == 401
    assert client.delete(u(1, "nets/net0?confirm=true")).status_code == 401


def test_add_net_vm_goes_through_the_nets_route_and_picks_free_index(api):
    c, cid = api
    r = c.post(u(cid, "nets"), json={"bridge": "vmbr0", "tag": 30, "firewall": True})
    assert r.status_code == 201 and r.json() == {"key": "net1", "value": "virtio,bridge=vmbr0,tag=30,firewall=1"}
    assert WRITES == [("PUT", "/nodes/enzo/qemu/115/config", {"net1": "virtio,bridge=vmbr0,tag=30,firewall=1"})]


def test_add_net_lxc_with_static_ip(api):
    c, cid = api
    CFG["v"] = LXC
    r = c.post(u(cid, "nets", "lxc", 105), json={"bridge": "vmbr0", "ip": "10.0.0.5/24", "gateway": "10.0.0.1"})
    assert r.status_code == 201 and r.json()["key"] == "net1"
    assert WRITES[0][2]["net1"] == "name=eth1,bridge=vmbr0,type=veth,ip=10.0.0.5/24,gw=10.0.0.1"


@pytest.mark.parametrize("payload,gtype", [
    ({"bridge": "vmbr0;x"}, "qemu"), ({"bridge": "vmbr0", "tag": 5000}, "qemu"), ({"bridge": "vmbr0", "model": "evil"}, "qemu"),
    ({"bridge": "vmbr0", "ip": "dhcp"}, "qemu"), ({"bridge": "vmbr0", "ip": "bad"}, "lxc"), ({"bridge": "vmbr0", "ip": "dhcp", "gateway": "1.1.1.1"}, "lxc"),
])
def test_invalid_net_rejected_without_writing(api, payload, gtype):
    c, cid = api
    CFG["v"] = LXC if gtype == "lxc" else QEMU
    assert c.post(u(cid, "nets", gtype, 105 if gtype == "lxc" else 115), json=payload).status_code == 422 and WRITES == []


def test_remove_net_needs_confirmation_and_existing_card(api):
    c, cid = api
    assert c.delete(u(cid, "nets/net0")).status_code == 400 and WRITES == []
    assert c.delete(u(cid, "nets/net9?confirm=true")).status_code == 404
    assert c.delete(u(cid, "nets/scsi0?confirm=true")).status_code in (404, 422) and WRITES == []
    r = c.delete(u(cid, "nets/net0?confirm=true"))
    assert r.status_code == 200 and WRITES == [("PUT", "/nodes/enzo/qemu/115/config", {"delete": "net0"})]


def test_boot_order_patch(api):
    c, cid = api
    r = c.patch(u(cid, "config"), json={"boot": ["ide2", "scsi0", "net0"]})
    assert r.status_code == 200 and WRITES[0][2] == {"boot": "order=ide2;scsi0;net0"}


@pytest.mark.parametrize("boot", [["scsi0", "scsi0"], ["scsi0;x"], ["evil"], [], ["net0", "net0"]])
def test_invalid_boot_rejected(api, boot):
    c, cid = api
    assert c.patch(u(cid, "config"), json={"boot": boot}).status_code == 422 and WRITES == []


def test_boot_unknown_device_404_and_lxc_refused(api):
    c, cid = api
    assert c.patch(u(cid, "config"), json={"boot": ["scsi5"]}).status_code == 404 and WRITES == []
    CFG["v"] = LXC
    assert c.patch(u(cid, "config", "lxc", 105), json={"boot": ["net0"]}).status_code == 422


def test_audit_trail_without_secrets(api):
    c, cid = api
    c.post(u(cid, "nets"), json={"bridge": "vmbr0"})
    c.delete(u(cid, "nets/net0"))                            # refusé
    c.delete(u(cid, "nets/net0?confirm=true"))
    FAIL["code"] = 403
    assert c.post(u(cid, "nets"), json={"bridge": "vmbr0"}).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("net-add", "started"), ("net-remove", "error"), ("net-remove", "started"), ("net-add", "error")]
    assert "BC:24:11:AA:BB:CC" in log[2]["detail"] and SECRET not in c.get("/api/audit").text
