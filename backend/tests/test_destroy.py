import httpx
import pytest

from app.config import get_settings
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.routers.destroy import volumes_of

# ---------- volumes détruits ----------

def test_volumes_of_lists_disks_and_unused_but_not_cdrom_or_empty():
    cfg = {"scsi0": "local-lvm:vm-116-disk-0,size=1G", "ide2": "local:iso/x.iso,media=cdrom", "ide3": "none,media=cdrom",
           "unused0": "local-lvm:vm-116-disk-1", "net0": "virtio=AA:AA:AA:AA:AA:AA,bridge=vmbr0", "name": "x"}
    assert volumes_of(cfg, "qemu") == ["scsi0=local-lvm:vm-116-disk-0", "unused0=local-lvm:vm-116-disk-1"]
    assert volumes_of({"rootfs": "local-lvm:vm-105-disk-0,size=8G", "mp0": "local-lvm:vm-105-disk-1,mp=/srv"}, "lxc") == \
        ["rootfs=local-lvm:vm-105-disk-0", "mp0=local-lvm:vm-105-disk-1"]


# ---------- API ----------

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:qmdestroy:116:kaji@pve!kaji:"
STATE = {"status": "stopped", "cfg": {}}
CALLS: list = []
FAIL: dict = {}
CFG_VM = {"name": "kaji-sandbox-clone", "scsi0": "local-lvm:vm-116-disk-0,size=1G", "unused0": "local-lvm:vm-116-disk-1"}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, dict(request.url.params)))
    if FAIL.get("code") and request.method == "DELETE":
        return httpx.Response(FAIL["code"], json={"data": None})
    if p.endswith("/status/current"):
        return httpx.Response(200, json={"data": {"status": STATE["status"]}})
    if p.endswith("/config"):
        return httpx.Response(200, json={"data": STATE["cfg"]})
    return httpx.Response(200, json={"data": UPID})


@pytest.fixture
def api(client, monkeypatch):
    CALLS.clear(); FAIL.clear(); STATE.update(status="stopped", cfg=dict(CFG_VM))
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, query="", gtype="qemu", vmid=116):
    return f"/api/connections/{cid}/guests/enzo/{gtype}/{vmid}{query}"


def deletes():
    return [x for x in CALLS if x[0] == "DELETE"]


def test_requires_auth(client):
    assert client.delete("/api/connections/1/guests/enzo/qemu/116?confirm=true&name=x").status_code == 401


def test_confirm_required_and_nothing_is_called(api):
    c, cid = api
    assert c.delete(u(cid)).status_code == 400
    assert c.delete(u(cid, "?name=kaji-sandbox-clone")).status_code == 400 and CALLS == []


@pytest.mark.parametrize("name", ["", "autre", "Kaji-Sandbox-Clone", "kaji-sandbox-clone ", "kaji"])
def test_wrong_or_missing_name_refused(api, name):
    c, cid = api
    assert c.delete(u(cid, f"?confirm=true&name={name}")).status_code == 400 and deletes() == []


def test_running_machine_refused(api):
    c, cid = api
    STATE["status"] = "running"
    r = c.delete(u(cid, "?confirm=true&name=kaji-sandbox-clone"))
    assert r.status_code == 409 and "arrêtée" in r.json()["detail"] and deletes() == []
    STATE["status"] = "paused"                                  # tout état autre que « stopped » est refusé
    assert c.delete(u(cid, "?confirm=true&name=kaji-sandbox-clone")).status_code == 409 and deletes() == []


def test_protected_by_proxmox_option_refused(api):
    c, cid = api
    STATE["cfg"] = {**CFG_VM, "protection": 1}
    assert c.delete(u(cid, "?confirm=true&name=kaji-sandbox-clone")).status_code == 409 and deletes() == []


def test_protected_by_kaji_refused_before_any_proxmox_call(api, monkeypatch):
    c, cid = api
    real = get_settings()
    monkeypatch.setattr("app.routers.destroy.get_settings", lambda: type("S", (), {"protected_vmids": {116, 105}})())
    r = c.delete(u(cid, "?confirm=true&name=kaji-sandbox-clone"))
    assert r.status_code == 403 and CALLS == [] and "protégée" in r.json()["detail"]
    assert c.delete(u(cid, "?confirm=true&name=web", "lxc", 105)).status_code == 403
    assert real.protected_vmids == set()                        # par défaut, rien n'est protégé


def test_protected_vmids_parsing():
    from app.config import Settings
    s = Settings(kaji_secret_key="x" * 20, kaji_protected_vmids=" 105, 108 ,abc,,")
    assert s.protected_vmids == {105, 108}


def test_successful_delete_calls_proxmox_once_with_purge(api):
    c, cid = api
    r = c.delete(u(cid, "?confirm=true&name=kaji-sandbox-clone"))
    assert r.status_code == 200 and r.json() == {"upid": UPID, "node": "enzo", "deleted": 116}
    assert [(m, p) for m, p, _ in CALLS] == [("GET", "/nodes/enzo/qemu/116/status/current"), ("GET", "/nodes/enzo/qemu/116/config"),
                                              ("DELETE", "/nodes/enzo/qemu/116")]
    assert CALLS[-1][2] == {"purge": "1"}


def test_options_purge_and_unreferenced(api):
    c, cid = api
    c.delete(u(cid, "?confirm=true&name=kaji-sandbox-clone&purge=false&destroy_unreferenced=true"))
    assert deletes()[0][2] == {"destroy-unreferenced-disks": "1"}


def test_lxc_uses_hostname(api):
    c, cid = api
    STATE["cfg"] = {"hostname": "web2", "rootfs": "local-lvm:vm-300-disk-0,size=8G"}
    assert c.delete(u(cid, "?confirm=true&name=kaji-sandbox-clone", "lxc", 300)).status_code == 400
    assert c.delete(u(cid, "?confirm=true&name=web2", "lxc", 300)).status_code == 200


def test_audit_lists_destroyed_disks_and_never_secrets(api):
    c, cid = api
    c.delete(u(cid, "?confirm=true&name=mauvais"))
    c.delete(u(cid, "?confirm=true&name=kaji-sandbox-clone"))
    FAIL["code"] = 403
    assert c.delete(u(cid, "?confirm=true&name=kaji-sandbox-clone")).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("guest-delete", "error"), ("guest-delete", "started"), ("guest-delete", "error")]
    assert "scsi0=local-lvm:vm-116-disk-0" in log[1]["detail"] and "unused0=" in log[1]["detail"] and log[1]["upid"] == UPID
    assert SECRET not in c.get("/api/audit").text
