from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.hardware import normalize, parse_disk, parse_net, parse_size, rebuild_net
from app.main import app
from app.proxmox import ProxmoxClient

# ---------- fonctions pures ----------

def test_parse_size():
    assert parse_size("32G") == 32 * 1024**3 and parse_size("512M") == 512 * 1024**2 and parse_size("x") is None


def test_parse_net_qemu_and_lxc():
    n = parse_net("net0", "virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,firewall=1,tag=10", lxc=False)
    assert (n["model"], n["mac"], n["bridge"], n["tag"], n["firewall"]) == ("virtio", "BC:24:11:AA:BB:CC", "vmbr0", 10, True)
    l = parse_net("net0", "name=eth0,bridge=vmbr1,hwaddr=AA:BB:CC:00:11:22,ip=dhcp,type=veth", lxc=True)
    assert (l["name"], l["mac"], l["bridge"], l["ip"], l["tag"]) == ("eth0", "AA:BB:CC:00:11:22", "vmbr1", "dhcp", None)


def test_rebuild_net_keeps_mac_and_unknown_options():
    raw = "virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,firewall=1,rate=5"
    out = rebuild_net(raw, lxc=False, bridge="vmbr2", tag=20)
    assert out == "virtio=BC:24:11:AA:BB:CC,bridge=vmbr2,firewall=1,rate=5,tag=20"
    assert "tag" not in rebuild_net(out, lxc=False, tag=None)
    assert "firewall=0" in rebuild_net(raw, lxc=False, firewall=False)
    assert rebuild_net(raw, lxc=False) == raw          # rien demandé : rien ne change


def test_parse_disk_and_cdrom():
    d = parse_disk("scsi0", "local-lvm:vm-100-disk-0,iothread=1,size=32G")
    assert (d["kind"], d["storage"], d["size_bytes"], d["options"]) == ("disk", "local-lvm", 32 * 1024**3, {"iothread": "1"})
    assert parse_disk("ide2", "none,media=cdrom")["empty"] is True
    c = parse_disk("ide2", "local:iso/win.iso,media=cdrom,size=5G")
    assert c["kind"] == "cdrom" and c["volume"] == "iso/win.iso"


def test_normalize_filters_to_known_settings():
    cfg = {"name": "w", "memory": 4096, "cores": 2, "args": "-fw_cfg boom", "scsi0": "local-lvm:vm-1-disk-0,size=10G",
           "net0": "virtio=AA:AA:AA:AA:AA:AA,bridge=vmbr0", "digest": "x"}
    n = normalize("qemu", cfg, [{"key": "memory", "value": 4096, "pending": 8192}, {"key": "cores", "value": 2}])
    assert "args" not in n["settings"] and "digest" not in n["settings"]
    assert n["reboot_required"] and n["pending"] == [{"key": "memory", "value": 4096, "pending": 8192, "delete": False}]


# ---------- API ----------

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
QEMU = {"name": "w11", "memory": 4096, "cores": 2, "sockets": 1, "scsi0": "local-lvm:vm-108-disk-0,size=64G",
        "ide2": "local:iso/win.iso,media=cdrom", "net0": "virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,firewall=1"}
LXC = {"hostname": "web", "memory": 512, "swap": 512, "cores": 1, "rootfs": "local-lvm:vm-105-disk-0,size=8G",
       "net0": "name=eth0,bridge=vmbr0,hwaddr=AA:BB:CC:00:11:22,ip=dhcp"}
WRITES = []
CFG = {}
FAIL = {}


def _handler(request: httpx.Request) -> httpx.Response:
    if FAIL.get("code"):
        return httpx.Response(FAIL["code"], json={"data": None})
    p = request.url.path
    if request.method == "GET" and p.endswith("/config"):
        return httpx.Response(200, json={"data": CFG["v"]})
    if request.method == "GET" and p.endswith("/pending"):
        return httpx.Response(200, json={"data": [{"key": "memory", "value": 4096, "pending": 8192}]})
    if request.method == "PUT":
        WRITES.append((p, {k: v[0] for k, v in parse_qs(request.content.decode()).items()}))
        return httpx.Response(200, json={"data": None})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    WRITES.clear(); FAIL.clear(); CFG["v"] = QEMU
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, what, gtype="qemu", vmid=108, node="enzo"):
    return f"/api/connections/{cid}/guests/{node}/{gtype}/{vmid}/{what}"


def test_requires_auth(client):
    assert client.get(u(1, "config")).status_code == 401
    assert client.patch(u(1, "config"), json={"cores": 2}).status_code == 401
    assert client.post(u(1, "resize"), json={"disk": "scsi0", "add_gb": 1}).status_code == 401


def test_get_config_normalized(api):
    c, cid = api
    r = c.get(u(cid, "config")).json()
    assert r["settings"]["memory"] == 4096 and r["reboot_required"] is True
    assert [d["key"] for d in r["disks"]] == ["ide2", "scsi0"] and r["nets"][0]["mac"] == "BC:24:11:AA:BB:CC"


def test_update_simple_settings(api):
    c, cid = api
    r = c.patch(u(cid, "config"), json={"memory": 8192, "cores": 4, "cpu": "host"})
    assert r.status_code == 200 and r.json()["changed"] == ["cores", "cpu", "memory"]
    assert WRITES == [("/api2/json/nodes/enzo/qemu/108/config", {"memory": "8192", "cores": "4", "cpu": "host"})]


def test_update_net_keeps_mac_and_cdrom_eject(api):
    c, cid = api
    c.patch(u(cid, "config"), json={"nets": {"net0": {"bridge": "vmbr1", "tag": 30}}, "cdroms": {"ide2": {"iso": None}}})
    sent = WRITES[0][1]
    assert sent["net0"] == "virtio=BC:24:11:AA:BB:CC,bridge=vmbr1,firewall=1,tag=30"
    assert sent["ide2"] == "none,media=cdrom"


def test_cdrom_mount_iso(api):
    c, cid = api
    c.patch(u(cid, "config"), json={"cdroms": {"ide2": {"iso": "local:iso/debian.iso"}}})
    assert WRITES[0][1]["ide2"] == "local:iso/debian.iso,media=cdrom"


@pytest.mark.parametrize("payload", [
    {"nets": {"net0": {"bridge": "vmbr0;rm"}}}, {"nets": {"net0": {"tag": 5000}}},
    {"cdroms": {"ide2": {"iso": "local:iso/../../etc/passwd"}}}, {"cdroms": {"ide2": {"iso": "http://x/a.iso"}}},
    {"cpu": "host,flags=+aes;x"}, {"memory": 1}, {"cores": 0}, {"unknown": 1, "args": "-evil"},
])
def test_invalid_values_rejected_without_writing(api, payload):
    c, cid = api
    r = c.patch(u(cid, "config"), json=payload)
    assert r.status_code in (422, 400) and WRITES == []


def test_unknown_extra_fields_ignored_never_forwarded(api):
    c, cid = api
    c.patch(u(cid, "config"), json={"cores": 2, "args": "-evil", "hookscript": "x"})
    assert WRITES[0][1] == {"cores": "2"}


@pytest.mark.parametrize("payload", [
    {"nets": {"net9": {"bridge": "vmbr0"}}}, {"nets": {"scsi0": {"bridge": "vmbr0"}}},
    {"cdroms": {"scsi0": {"iso": None}}}, {"cdroms": {"ide9": {"iso": None}}},
])
def test_unknown_or_wrong_device_404(api, payload):
    c, cid = api
    assert c.patch(u(cid, "config"), json=payload).status_code == 404 and WRITES == []


def test_empty_update_refused(api):
    c, cid = api
    assert c.patch(u(cid, "config"), json={}).status_code == 400 and WRITES == []


def test_lxc_rules(api):
    c, cid = api
    CFG["v"] = LXC
    assert c.patch(u(cid, "config", "lxc", 105), json={"balloon": 100}).status_code == 422
    assert c.patch(u(cid, "config", "lxc", 105), json={"cdroms": {"ide2": {"iso": None}}}).status_code == 422
    assert c.patch(u(cid, "config"), json={"swap": 256}).status_code == 422          # swap sur une VM
    r = c.patch(u(cid, "config", "lxc", 105), json={"memory": 1024, "swap": 256, "nets": {"net0": {"bridge": "vmbr1"}}})
    assert r.status_code == 200
    assert WRITES[0][1]["net0"] == "name=eth0,bridge=vmbr1,hwaddr=AA:BB:CC:00:11:22,ip=dhcp"


def test_resize_requires_confirmation_and_valid_disk(api):
    c, cid = api
    assert c.post(u(cid, "resize"), json={"disk": "scsi0", "add_gb": 5}).status_code == 400
    assert c.post(u(cid, "resize"), json={"disk": "scsi0", "add_gb": 0, "confirm": True}).status_code == 422
    assert c.post(u(cid, "resize"), json={"disk": "scsi0", "add_gb": -5, "confirm": True}).status_code == 422
    assert c.post(u(cid, "resize"), json={"disk": "ide2", "add_gb": 5, "confirm": True}).status_code == 404   # CD-ROM
    assert c.post(u(cid, "resize"), json={"disk": "net0", "add_gb": 5, "confirm": True}).status_code == 404
    assert WRITES == []
    r = c.post(u(cid, "resize"), json={"disk": "scsi0", "add_gb": 5, "confirm": True})
    assert r.status_code == 202
    assert WRITES == [("/api2/json/nodes/enzo/qemu/108/resize", {"disk": "scsi0", "size": "+5G"})]


def test_resize_lxc_rootfs(api):
    c, cid = api
    CFG["v"] = LXC
    assert c.post(u(cid, "resize", "lxc", 105), json={"disk": "rootfs", "add_gb": 1, "confirm": True}).status_code == 202
    assert WRITES[0][1] == {"disk": "rootfs", "size": "+1G"}


def test_everything_is_audited_without_secrets(api):
    c, cid = api
    c.patch(u(cid, "config"), json={"cores": 4})
    c.patch(u(cid, "config"), json={})
    c.post(u(cid, "resize"), json={"disk": "scsi0", "add_gb": 5})
    FAIL["code"] = 403
    c.patch(u(cid, "config"), json={"cores": 2})
    log = c.get("/api/audit").json()
    assert [(e["action"], e["status"]) for e in log][::-1] == [("config", "started"), ("config", "error"), ("resize", "error")] + [("config", "error")]
    assert SECRET not in c.get("/api/audit").text


def test_proxmox_refusal_reported(api):
    c, cid = api
    CFG["v"] = QEMU
    FAIL["code"] = 403
    assert c.patch(u(cid, "config"), json={"cores": 2}).status_code == 502
