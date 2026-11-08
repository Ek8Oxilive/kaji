from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from app.deps import get_client_factory
from app.lxcspec import LxcCreate, build_lxc_params
from app.main import app
from app.proxmox import ProxmoxClient

TPL = "local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl user@machine"
DISK = {"storage": "local-lvm", "size_gb": 2}


def spec(**kw):
    return LxcCreate(hostname="kaji-ct", template=TPL, disk=DISK, **kw)


# ---------- paramètres ----------

def test_minimal_container_is_unprivileged_with_no_credentials_and_no_net():
    p = build_lxc_params(spec(), 300)
    assert p == {"vmid": 300, "ostemplate": TPL, "hostname": "kaji-ct", "memory": 512, "swap": 512, "cores": 1,
                 "rootfs": "local-lvm:2", "unprivileged": 1}


def test_full_container_params():
    p = build_lxc_params(spec(memory=256, swap=0, cores=2, pool="kaji-test", nesting=True, start=True, description=" t ",
                              net={"bridge": "vmbr0", "ip": "10.0.0.5/24", "gateway": "10.0.0.1", "tag": 20, "firewall": True},
                              password="un-bon-mot-de-passe", ssh_public_keys=KEY + "\n\n"), 301)
    assert p["net0"] == "name=eth0,bridge=vmbr0,type=veth,ip=10.0.0.5/24,gw=10.0.0.1,tag=20,firewall=1"
    assert (p["features"], p["pool"], p["start"], p["description"]) == ("nesting=1", "kaji-test", 1, "t")
    assert p["password"] == "un-bon-mot-de-passe" and p["ssh-public-keys"] == KEY


def test_privileged_is_an_explicit_choice():
    assert build_lxc_params(spec(unprivileged=False), 300)["unprivileged"] == 0


@pytest.mark.parametrize("bad", [
    {"hostname": "-x"}, {"hostname": "a b"}, {"hostname": "a;b"}, {"vmid": 99}, {"memory": 1}, {"cores": 0}, {"swap": -1},
    {"template": "local:iso/x.iso"}, {"template": "http://x/a.tar.zst"}, {"template": "local:vztmpl/../../etc/passwd.tar.zst"},
    {"template": "local:vztmpl/x.tar.zst;rm"}, {"pool": "../x"}, {"password": "court"}, {"password": "x" * 129},
    {"ssh_public_keys": "pas une clé"}, {"ssh_public_keys": KEY + "\nssh-rsa court"}, {"ssh_public_keys": "\n".join([KEY] * 9)},
    {"disk": {"storage": "a;b", "size_gb": 2}}, {"disk": {"storage": "local-lvm", "size_gb": 0}},
    {"net": {"bridge": "vmbr0;x"}}, {"net": {"bridge": "vmbr0", "tag": 5000}}, {"description": "x" * 201},
])
def test_invalid_specs_rejected(bad):
    base = {"hostname": "ok", "template": TPL, "disk": DISK}
    with pytest.raises(ValidationError):
        LxcCreate(**{**base, **bad})


def test_bad_ip_is_refused_by_the_builder():
    with pytest.raises(ValueError):
        build_lxc_params(spec(net={"bridge": "vmbr0", "ip": "192.168.1.5"}), 300)             # masque manquant


def test_password_is_never_in_repr_or_dump():
    s = spec(password="un-bon-mot-de-passe")
    assert "un-bon-mot-de-passe" not in repr(s) and "un-bon-mot-de-passe" not in str(s.model_dump())


def test_unknown_fields_ignored():
    assert "args" not in build_lxc_params(LxcCreate(hostname="ok", template=TPL, disk=DISK, **{"args": "x"}), 300)


# ---------- API ----------

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CT_PWD = "mot-de-passe-du-conteneur"
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:vzcreate:300:kaji@pve!kaji:"
CALLS: list = []
FAIL: dict = {}
RES: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, {k: v[0] for k, v in parse_qs(request.content.decode()).items()}))
    if FAIL.get("code") and request.method == "POST" and p.endswith("/lxc"):
        return httpx.Response(FAIL["code"], json={"data": None})
    if p == "/cluster/resources":                       # strict : seul `type=vm` est connu de ce test
        if request.url.params.get("type") != "vm":
            return httpx.Response(400, json={"data": None})
        return httpx.Response(200, json={"data": RES.get("rows", [{"vmid": 115, "type": "qemu"}, {"vmid": "116", "type": "lxc"}])})
    return httpx.Response(200, json={"data": "300" if p == "/cluster/nextid" else UPID})


@pytest.fixture
def api(client):
    CALLS.clear(); FAIL.clear(); RES.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, node="enzo"):
    return f"/api/connections/{cid}/nodes/{node}/lxc"


def good(**kw):
    return {"hostname": "kaji-ct", "template": TPL, "disk": DISK, **kw}


def test_requires_auth(client):
    assert client.post("/api/connections/1/nodes/enzo/lxc", json=good()).status_code == 401


def test_create_uses_nextid_and_validated_params(api):
    c, cid = api
    r = c.post(url(cid), json=good(pool="kaji-test", args="-evil"))
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo", "vmid": 300}
    method, path, form = CALLS[-1]
    assert (method, path) == ("POST", "/nodes/enzo/lxc") and form["vmid"] == "300" and form["pool"] == "kaji-test" and "args" not in form


def test_password_reaches_proxmox_but_never_the_audit_nor_any_response(api):
    c, cid = api
    r = c.post(url(cid), json=good(password=CT_PWD, ssh_public_keys=KEY))
    assert r.status_code == 202 and CT_PWD not in r.text
    assert CALLS[-1][2]["password"] == CT_PWD                                    # transmis à Proxmox, et seulement à lui
    audit = c.get("/api/audit").text
    assert CT_PWD not in audit and KEY not in audit and "AAAAC3Nza" not in audit
    assert "mot de passe" in audit and "clé SSH" in audit                        # on sait seulement qu'un accès est configuré


def test_validation_errors_do_not_echo_the_password(api):
    c, cid = api
    r = c.post(url(cid), json={"hostname": "ok", "template": TPL, "password": "COURT-ECHO"})   # disque manquant + mot de passe trop court
    assert r.status_code == 422 and "COURT-ECHO" not in r.text


def test_proxmox_refusal_audited_without_secret(api):
    c, cid = api
    FAIL["code"] = 403
    assert c.post(url(cid), json=good(password=CT_PWD)).status_code == 502
    log = c.get("/api/audit").json()
    assert log[0]["status"] == "error" and CT_PWD not in c.get("/api/audit").text and SECRET not in c.get("/api/audit").text


def test_audit_marks_privileged_and_no_access(api):
    c, cid = api
    c.post(url(cid), json=good(unprivileged=False))
    d = c.get("/api/audit").json()[0]["detail"]
    assert "PRIVILÉGIÉ" in d and "aucun accès configuré" in d


@pytest.mark.parametrize("node", ["a;b", "-x"])
def test_invalid_node_rejected(api, node):
    c, cid = api
    assert c.post(url(cid, node), json=good()).status_code in (404, 422) and CALLS == []


# ---------- identifiant déjà pris (pré-contrôle, aucun appel de création) ----------

@pytest.mark.parametrize("vmid", [115, 116])
def test_taken_vmid_is_refused_409_and_nothing_is_created(api, vmid):
    c, cid = api
    r = c.post(url(cid), json=good(vmid=vmid))
    assert r.status_code == 409 and r.json()["detail"] == "Cet identifiant est déjà utilisé" and str(vmid) not in r.text
    assert not any(x[0] == "POST" for x in CALLS)


def test_taken_vmid_refusal_is_audited_without_the_typed_value_in_the_message(api):
    c, cid = api
    c.post(url(cid), json=good(vmid=116))
    e = c.get("/api/audit").json()[0]
    assert (e["action"], e["status"], e["target"]) == ("create-lxc", "error", "lxc/116@enzo") and "116" not in (e["detail"] or "")


def test_free_vmid_is_created_after_one_listing(api):
    c, cid = api
    assert c.post(url(cid), json=good(vmid=117)).status_code == 202
    assert [x[1] for x in CALLS] == ["/cluster/resources", "/nodes/enzo/lxc"]


def test_automatic_vmid_does_not_list_the_machines(api):
    c, cid = api
    assert c.post(url(cid), json=good()).status_code == 202 and [x[1] for x in CALLS] == ["/cluster/nextid", "/nodes/enzo/lxc"]


@pytest.mark.parametrize("rows", ["texte", {"vmid": 115}, 5])
def test_an_unreadable_listing_is_refused_502_and_nothing_is_created(api, rows):
    c, cid = api
    RES["rows"] = rows
    r = c.post(url(cid), json=good(vmid=117))
    assert r.status_code == 502 and "illisible" in r.json()["detail"] and not any(x[0] == "POST" for x in CALLS)
    assert c.get("/api/audit").json()[0]["status"] == "error"


def test_an_empty_or_missing_listing_means_free(api):
    c, cid = api
    for rows in (None, []):
        RES["rows"] = rows
        assert c.post(url(cid), json=good(vmid=116)).status_code == 202
