from urllib.parse import parse_qs, quote, unquote

import httpx
import pytest
from pydantic import ValidationError

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.routers.cloudinit import CloudInitUpdate, IpConf, build_params, ipconfig_value, parse_ipconfig, shape

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl user@machine"
CI_PWD = "mot-de-passe-cloud-init"


# ---------- construction ----------

def test_params_are_mapped_and_ssh_keys_are_urlencoded():
    p, d = build_params(CloudInitUpdate(user="kaji", password=CI_PWD, ssh_keys=KEY + "\n\n", nameserver="1.1.1.1  9.9.9.9",
                                        searchdomain="lab.local", upgrade=True,
                                        ipconfig={"ipconfig0": {"mode": "static", "ip": "10.0.0.5/24", "gateway": "10.0.0.1"}}))
    assert d == [] and p["ciuser"] == "kaji" and p["cipassword"] == CI_PWD and p["ciupgrade"] == 1
    assert p["sshkeys"] == quote(KEY, safe="") and "%20" in p["sshkeys"] and "\n" not in p["sshkeys"] and unquote(p["sshkeys"]) == KEY
    assert (p["nameserver"], p["searchdomain"], p["ipconfig0"]) == ("1.1.1.1 9.9.9.9", "lab.local", "ip=10.0.0.5/24,gw=10.0.0.1")


def test_ipconfig_modes():
    assert ipconfig_value(IpConf(mode="dhcp")) == "ip=dhcp" and ipconfig_value(IpConf(mode="none")) == "ip=manual"
    for bad in (IpConf(mode="static"), IpConf(mode="static", ip="10.0.0.5"), IpConf(mode="static", ip="10.0.0.5/24", gateway="pas-une-ip")):
        with pytest.raises(ValueError):
            ipconfig_value(bad)


def test_clear_maps_to_proxmox_keys_and_refuses_clashes():
    assert build_params(CloudInitUpdate(clear=["user", "password", "ssh_keys", "ipconfig0"]))[1] == ["ciuser", "cipassword", "sshkeys", "ipconfig0"]
    with pytest.raises(ValueError):
        build_params(CloudInitUpdate(user="kaji", clear=["user"]))


@pytest.mark.parametrize("bad", [
    {"user": "Root"}, {"user": "-x"}, {"user": "a b"}, {"user": "x" * 33}, {"password": "court"}, {"password": "x" * 129},
    {"ssh_keys": "pas une clé"}, {"ssh_keys": ""}, {"ssh_keys": KEY + "\nssh-rsa court"}, {"ssh_keys": "\n".join([KEY] * 9)},
    {"nameserver": "pas-une-ip"}, {"nameserver": "1.1.1.1;x"}, {"nameserver": "  "}, {"searchdomain": "a b"}, {"searchdomain": "-x"},
    {"ipconfig": {"ipconfig99": {"mode": "dhcp"}}}, {"ipconfig": {"net0": {"mode": "dhcp"}}}, {"ipconfig": {"ipconfig0": {"mode": "evil"}}},
    {"clear": ["ciuser"]}, {"clear": ["../x"]},
])
def test_invalid_updates_rejected(bad):
    with pytest.raises(ValidationError):
        CloudInitUpdate(**bad)


def test_password_never_in_repr_or_dump():
    u = CloudInitUpdate(password=CI_PWD)
    assert CI_PWD not in repr(u) and CI_PWD not in str(u.model_dump())


# ---------- lecture ----------

def test_shape_hides_password_and_decodes_keys():
    cfg = {"ciuser": "kaji", "cipassword": "**********", "sshkeys": quote(KEY, safe=""), "ipconfig0": "ip=10.0.0.5/24,gw=10.0.0.1",
           "ipconfig1": "ip=dhcp", "nameserver": "1.1.1.1", "ciupgrade": 1, "ide2": "local-lvm:vm-115-cloudinit,media=cdrom"}
    s = shape(cfg)
    assert s["has_drive"] and s["drive"] == "ide2" and s["password_set"] is True and "**********" not in str(s)
    assert s["ssh_keys"] == KEY and s["upgrade"] is True and s["user"] == "kaji"
    assert s["ipconfig"] == {"ipconfig0": {"mode": "static", "ip": "10.0.0.5/24", "gateway": "10.0.0.1"},
                             "ipconfig1": {"mode": "dhcp", "ip": None, "gateway": None}}
    e = shape({"name": "x"})
    assert not e["has_drive"] and e["password_set"] is False and e["upgrade"] is None and e["ssh_keys"] is None
    assert parse_ipconfig("ip=manual")["mode"] == "none"


# ---------- API ----------

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
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
    WRITES.clear(); FAIL.clear(); CFG["v"] = {"name": "kaji-sandbox", "scsi0": "local-lvm:vm-115-disk-0,size=1G"}
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, suffix="", vmid=115):
    return f"/api/connections/{cid}/guests/enzo/qemu/{vmid}/cloudinit{suffix}"


def test_requires_auth(client):
    assert client.get(u(1)).status_code == 401
    assert client.patch(u(1), json={"user": "kaji"}).status_code == 401
    assert client.post(u(1, "/drive"), json={"storage": "x"}).status_code == 401
    assert client.delete(u(1, "/drive?confirm=true")).status_code == 401


def test_patch_sends_urlencoded_keys_and_password_only_to_proxmox(api):
    c, cid = api
    r = c.patch(u(cid), json={"user": "kaji", "password": CI_PWD, "ssh_keys": KEY, "upgrade": False})
    assert r.status_code == 200 and CI_PWD not in r.text
    assert WRITES[0][2] == {"ciuser": "kaji", "cipassword": CI_PWD, "sshkeys": quote(KEY, safe=""), "ciupgrade": "0"}
    audit = c.get("/api/audit").text
    assert CI_PWD not in audit and "AAAAC3Nza" not in audit and "mot de passe" in audit and "clés SSH" in audit


def test_patch_clear_goes_in_one_delete_parameter(api):
    c, cid = api
    c.patch(u(cid), json={"clear": ["user", "password", "ssh_keys"]})
    assert WRITES[0][2] == {"delete": "ciuser,cipassword,sshkeys"}


def test_empty_and_clashing_patches_refused(api):
    c, cid = api
    assert c.patch(u(cid), json={}).status_code == 400
    assert c.patch(u(cid), json={"user": "kaji", "clear": ["user"]}).status_code == 422 and WRITES == []


def test_validation_errors_do_not_echo_the_password(api):
    c, cid = api
    r = c.patch(u(cid), json={"password": "COURT", "user": "Root"})
    assert r.status_code == 422 and "COURT" not in r.text


def test_vm_only_lxc_path_does_not_exist(api):
    c, cid = api
    assert c.get(f"/api/connections/{cid}/guests/enzo/lxc/105/cloudinit").status_code in (404, 405, 422)


def test_add_drive_uses_ide2_then_first_free_slot(api):
    c, cid = api
    r = c.post(u(cid, "/drive"), json={"storage": "local-lvm"})
    assert r.status_code == 201 and r.json() == {"key": "ide2"} and WRITES == [("PUT", "/nodes/enzo/qemu/115/config", {"ide2": "local-lvm:cloudinit"})]
    CFG["v"]["ide2"] = "none,media=cdrom"
    assert c.post(u(cid, "/drive"), json={"storage": "local-lvm"}).json() == {"key": "ide0"}
    CFG["v"].update(ide0="none,media=cdrom", ide1="none,media=cdrom", ide3="none,media=cdrom")
    assert c.post(u(cid, "/drive"), json={"storage": "local-lvm"}).status_code == 409


def test_add_drive_refused_when_one_exists_or_storage_invalid(api):
    c, cid = api
    CFG["v"]["ide2"] = "local-lvm:vm-115-cloudinit,media=cdrom"
    assert c.post(u(cid, "/drive"), json={"storage": "local-lvm"}).status_code == 409 and WRITES == []
    assert c.post(u(cid, "/drive"), json={"storage": "a;b"}).status_code == 422


def test_remove_drive_needs_confirm_and_a_cloudinit_drive(api):
    c, cid = api
    assert c.delete(u(cid, "/drive")).status_code == 400
    assert c.delete(u(cid, "/drive?confirm=true")).status_code == 404 and WRITES == []        # pas de lecteur cloud-init
    CFG["v"]["ide2"] = "local:iso/debian.iso,media=cdrom"                                      # un vrai CD n'est jamais retiré
    assert c.delete(u(cid, "/drive?confirm=true")).status_code == 404 and WRITES == []
    CFG["v"]["ide3"] = "local-lvm:vm-115-cloudinit,media=cdrom"
    assert c.delete(u(cid, "/drive?confirm=true")).json() == {"removed": "ide3"} and WRITES[0][2] == {"delete": "ide3"}


def test_audit_trail_and_proxmox_refusal(api):
    c, cid = api
    c.patch(u(cid), json={"user": "kaji"})
    FAIL["code"] = 403
    assert c.patch(u(cid), json={"user": "autre"}).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("cloudinit-update", "started"), ("cloudinit-update", "error")]
    assert SECRET not in c.get("/api/audit").text
