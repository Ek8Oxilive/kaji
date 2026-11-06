from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.hardware import build_new_disk, check_mp_path, next_disk_key, next_mp_key, normalize
from app.main import app
from app.proxmox import ProxmoxClient

# ---------- fonctions pures ----------

def test_next_keys_fill_gaps_and_respect_limits():
    assert next_disk_key({}, "scsi") == "scsi0"
    assert next_disk_key({"scsi0": "x", "scsi2": "y", "virtio0": "z"}, "scsi") == "scsi1"
    assert next_disk_key({f"ide{i}": "x" for i in range(3)}, "ide") == "ide3"
    with pytest.raises(ValueError):
        next_disk_key({f"ide{i}": "x" for i in range(4)}, "ide")
    assert next_mp_key({"mp0": "x", "mp1": "y"}) == "mp2" and next_mp_key({}) == "mp0"


def test_build_new_disk_and_mount_paths():
    assert build_new_disk("local-lvm", 8) == "local-lvm:8"
    assert build_new_disk("local-lvm", 8, "/srv/data") == "local-lvm:8,mp=/srv/data"


@pytest.mark.parametrize("p", ["/", "srv", "/a/../b", "/a//b", "/a,b", "/a b", "/a;b", "", "/" + "x" * 201])
def test_invalid_mount_paths(p):
    with pytest.raises(ValueError):
        check_mp_path(p)


def test_normalize_lists_unused_disks():
    n = normalize("qemu", {"scsi0": "l:v,size=1G", "unused0": "local-lvm:vm-115-disk-1", "unused1": "other:vm-115-disk-2"}, [])
    assert n["unused"] == [{"key": "unused0", "volume": "local-lvm:vm-115-disk-1", "storage": "local-lvm"},
                           {"key": "unused1", "volume": "other:vm-115-disk-2", "storage": "other"}]


# ---------- API ----------

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
QEMU = {"name": "kaji-sandbox", "scsi0": "local-lvm:vm-115-disk-0,size=1G", "scsi1": "local-lvm:vm-115-disk-1,size=2G",
        "ide2": "none,media=cdrom", "unused0": "local-lvm:vm-115-disk-2", "net0": "virtio=AA:AA:AA:AA:AA:AA,bridge=vmbr0"}
LXC = {"hostname": "web", "rootfs": "local-lvm:vm-105-disk-0,size=8G", "mp0": "local-lvm:vm-105-disk-1,mp=/srv,size=2G",
       "unused0": "local-lvm:vm-105-disk-2"}
CFG: dict = {}
WRITES: list = []
FAIL: dict = {}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:qmmove:115:kaji@pve!kaji:"


def _handler(request: httpx.Request) -> httpx.Response:
    if FAIL.get("code"):
        return httpx.Response(FAIL["code"], json={"data": None})
    if request.method == "GET":
        return httpx.Response(200, json={"data": CFG["v"]})
    WRITES.append((request.method, request.url.path.removeprefix("/api2/json"), {k: v[0] for k, v in parse_qs(request.content.decode()).items()}))
    return httpx.Response(200, json={"data": UPID if request.method == "POST" else None})


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
    return f"/api/connections/{cid}/guests/enzo/{gtype}/{vmid}/disks{suffix}"


def test_requires_auth(client):
    assert client.post(u(1), json={"storage": "x", "size_gb": 1}).status_code == 401
    assert client.post(u(1, "/scsi0/detach")).status_code == 401
    assert client.delete(u(1, "/unused0?confirm=true&name=x")).status_code == 401
    assert client.post(u(1, "/scsi0/move"), json={"storage": "x", "confirm": True}).status_code == 401


def test_add_disk_vm_picks_free_slot(api):
    c, cid = api
    r = c.post(u(cid), json={"storage": "local-lvm", "size_gb": 4})
    assert r.status_code == 201 and r.json() == {"key": "scsi2", "value": "local-lvm:4"}
    assert WRITES == [("PUT", "/nodes/enzo/qemu/115/config", {"scsi2": "local-lvm:4"})]
    assert c.post(u(cid), json={"storage": "local-lvm", "size_gb": 1, "bus": "virtio"}).json()["key"] == "virtio0"


def test_add_disk_lxc_requires_valid_mount_path(api):
    c, cid = api
    CFG["v"] = LXC
    assert c.post(u(cid, "", "lxc", 105), json={"storage": "local-lvm", "size_gb": 1}).status_code == 422
    assert c.post(u(cid, "", "lxc", 105), json={"storage": "local-lvm", "size_gb": 1, "mp": "/a/../b"}).status_code == 422 and WRITES == []
    r = c.post(u(cid, "", "lxc", 105), json={"storage": "local-lvm", "size_gb": 1, "mp": "/data"})
    assert r.status_code == 201 and r.json() == {"key": "mp1", "value": "local-lvm:1,mp=/data"}
    assert c.post(u(cid), json={"storage": "local-lvm", "size_gb": 1, "mp": "/data"}).status_code == 422     # mp sur une VM


@pytest.mark.parametrize("bad", [{"storage": "a;b", "size_gb": 1}, {"storage": "local-lvm", "size_gb": 0}, {"storage": "local-lvm", "size_gb": 70000},
                                 {"storage": "local-lvm", "size_gb": 1, "bus": "evil"}, {"storage": "../x", "size_gb": 1}])
def test_invalid_add_rejected_without_writing(api, bad):
    c, cid = api
    assert c.post(u(cid), json=bad).status_code == 422 and WRITES == []


def test_detach_keeps_data_and_only_applies_to_real_disks(api):
    c, cid = api
    assert c.post(u(cid, "/scsi1/detach")).status_code == 200
    assert WRITES == [("PUT", "/nodes/enzo/qemu/115/config", {"delete": "scsi1"})]
    WRITES.clear()
    for key, code in (("ide2", 404), ("net0", 404), ("scsi9", 404), ("unused0", 404), ("rootfs", 422)):
        assert c.post(u(cid, f"/{key}/detach")).status_code == code, key
    assert WRITES == []


def test_lxc_rootfs_cannot_be_detached_but_mountpoint_can(api):
    c, cid = api
    CFG["v"] = LXC
    assert c.post(u(cid, "/rootfs/detach", "lxc", 105)).status_code == 422 and WRITES == []
    assert c.post(u(cid, "/mp0/detach", "lxc", 105)).status_code == 200 and WRITES[0][2] == {"delete": "mp0"}


def test_reattach_unused_disk(api):
    c, cid = api
    r = c.post(u(cid, "/unused0/reattach"), json={"bus": "sata"})
    assert r.status_code == 200 and r.json() == {"key": "sata0"}
    # jamais de « delete » avec le rattachement : Proxmox le traiterait en premier et détruirait le volume
    assert WRITES == [("PUT", "/nodes/enzo/qemu/115/config", {"sata0": "local-lvm:vm-115-disk-2"})]
    assert all("delete" not in w[2] for w in WRITES)
    assert c.post(u(cid, "/scsi0/reattach"), json={}).status_code in (404, 422)
    CFG["v"] = LXC
    assert c.post(u(cid, "/unused0/reattach", "lxc", 105), json={}).status_code == 422                   # chemin manquant
    assert c.post(u(cid, "/unused0/reattach", "lxc", 105), json={"mp": "/back"}).status_code == 200
    assert WRITES[-1][2] == {"mp1": "local-lvm:vm-105-disk-2,mp=/back"}


def test_destroy_requires_confirm_exact_name_and_unused_key(api):
    c, cid = api
    assert c.delete(u(cid, "/unused0")).status_code == 400
    assert c.delete(u(cid, "/unused0?confirm=true")).status_code == 400                       # nom absent
    assert c.delete(u(cid, "/unused0?confirm=true&name=Kaji-Sandbox")).status_code == 400     # casse différente
    assert c.delete(u(cid, "/unused0?confirm=true&name=autre")).status_code == 400
    assert c.delete(u(cid, "/scsi1?confirm=true&name=kaji-sandbox")).status_code in (404, 422)  # pas un disque « non utilisé »
    assert c.delete(u(cid, "/unused7?confirm=true&name=kaji-sandbox")).status_code == 404
    assert WRITES == []
    r = c.delete(u(cid, "/unused0?confirm=true&name=kaji-sandbox"))
    assert r.status_code == 200 and WRITES == [("PUT", "/nodes/enzo/qemu/115/config", {"delete": "unused0"})]


def test_destroy_uses_hostname_for_lxc(api):
    c, cid = api
    CFG["v"] = LXC
    assert c.delete(u(cid, "/unused0?confirm=true&name=kaji-sandbox", "lxc", 105)).status_code == 400
    assert c.delete(u(cid, "/unused0?confirm=true&name=web", "lxc", 105)).status_code == 200


def test_move_requires_confirm_valid_disk_and_new_storage(api):
    c, cid = api
    assert c.post(u(cid, "/scsi0/move"), json={"storage": "autre"}).status_code == 400
    assert c.post(u(cid, "/scsi0/move"), json={"storage": "local-lvm", "confirm": True}).status_code == 422      # déjà dessus
    assert c.post(u(cid, "/ide2/move"), json={"storage": "autre", "confirm": True}).status_code == 404
    assert c.post(u(cid, "/scsi0/move"), json={"storage": "a;b", "confirm": True}).status_code == 422
    assert WRITES == []
    r = c.post(u(cid, "/scsi0/move"), json={"storage": "autre", "confirm": True})
    assert r.status_code == 202 and r.json()["upid"] == UPID
    assert WRITES == [("POST", "/nodes/enzo/qemu/115/move_disk", {"disk": "scsi0", "storage": "autre", "delete": "0"})]


def test_move_lxc_uses_move_volume_and_delete_flag(api):
    c, cid = api
    CFG["v"] = LXC
    c.post(u(cid, "/rootfs/move", "lxc", 105), json={"storage": "autre", "confirm": True, "delete_source": True})
    assert WRITES == [("POST", "/nodes/enzo/lxc/105/move_volume", {"volume": "rootfs", "storage": "autre", "delete": "1"})]


def test_audit_trail_without_secrets(api):
    c, cid = api
    c.post(u(cid, "/scsi1/detach"))
    c.delete(u(cid, "/unused0?confirm=true&name=mauvais"))                # refusé
    c.delete(u(cid, "/unused0?confirm=true&name=kaji-sandbox"))
    FAIL["code"] = 403
    assert c.post(u(cid), json={"storage": "local-lvm", "size_gb": 1}).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("disk-detach", "started"), ("disk-destroy", "error"), ("disk-destroy", "started"), ("disk-add", "error")]
    assert "DÉTRUIT" in log[2]["detail"] and log[0]["target"] == "qemu/115@enzo:scsi1" and SECRET not in c.get("/api/audit").text
