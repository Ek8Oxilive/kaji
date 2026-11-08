from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.vmspec import VmCreate, build_params

# ---------- construction des paramètres ----------

def spec(**kw):
    return VmCreate(name="kaji-sandbox", **kw)


def test_minimal_vm_has_no_disk_no_net_no_boot():
    p = build_params(spec(), 900)
    assert p["vmid"] == 900 and p["name"] == "kaji-sandbox" and p["scsihw"] == "virtio-scsi-single"
    assert not {"scsi0", "net0", "ide2", "boot", "pool", "start", "agent"} & set(p)


def test_full_vm_params():
    p = build_params(spec(memory=1024, cores=1, pool="kaji-test", agent=True, description=" test ",
                          disk={"storage": "local-lvm", "size_gb": 8},
                          net={"bridge": "vmbr0", "tag": 20, "firewall": True},
                          iso="local:iso/debian.iso"), 901)
    assert p["scsi0"] == "local-lvm:8" and p["net0"] == "virtio,bridge=vmbr0,tag=20,firewall=1"
    assert p["ide2"] == "local:iso/debian.iso,media=cdrom" and p["boot"] == "order=scsi0;ide2"
    assert (p["pool"], p["agent"], p["description"]) == ("kaji-test", 1, "test")


def test_iso_only_boots_from_cdrom():
    assert build_params(spec(iso="local:iso/x.iso"), 900)["boot"] == "order=ide2"


def test_windows11_gets_uefi_tpm_and_efi_disk():
    p = build_params(spec(ostype="win11", disk={"storage": "local-lvm", "size_gb": 64}), 902)
    assert p["bios"] == "ovmf" and p["machine"] == "q35"
    assert p["efidisk0"].startswith("local-lvm:1,efitype=4m") and p["tpmstate0"] == "local-lvm:1,version=v2.0"
    with pytest.raises(ValueError):
        build_params(spec(ostype="win11"), 902)               # sans disque : impossible


@pytest.mark.parametrize("bad", [
    {"name": "-x"}, {"name": "a b"}, {"name": "a;b"}, {"name": ""}, {"name": "x" * 64},
    {"vmid": 99}, {"memory": 1}, {"cores": 0}, {"sockets": 9}, {"cpu": "host,flags=+aes"}, {"ostype": "../x"},
    {"pool": "a b"}, {"pool": "../x"}, {"iso": "http://x/a.iso"}, {"iso": "local:iso/../../etc/passwd"},
    {"disk": {"storage": "a;b", "size_gb": 8}}, {"disk": {"storage": "local", "size_gb": 0}},
    {"net": {"bridge": "vmbr0;x"}}, {"net": {"bridge": "vmbr0", "tag": 5000}}, {"net": {"bridge": "vmbr0", "model": "evil"}},
    {"description": "x" * 201},
])
def test_invalid_specs_rejected(bad):
    with pytest.raises(ValidationError):
        VmCreate(**{"name": "ok", **bad})


def test_unknown_fields_never_reach_proxmox():
    p = build_params(VmCreate(name="ok", **{"args": "-evil", "hookscript": "x"}), 900)
    assert "args" not in p and "hookscript" not in p


# ---------- API ----------

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:qmcreate:900:kaji@pve!kaji:"
CALLS: list[tuple[str, str, dict]] = []
FAIL: dict = {}
RES: dict = {}                    # "rows" : réponse de /cluster/resources (par défaut : 115 « kaji-sandbox » et 120 en texte)


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    CALLS.append((request.method, p, form))
    if FAIL.get("code") and p == FAIL.get("path", p):
        return httpx.Response(FAIL["code"], json={"data": None})
    if p == "/cluster/resources":                       # strict : seul `type=vm` est connu de ce test
        if request.url.params.get("type") != "vm":
            return httpx.Response(400, json={"data": None})
        return httpx.Response(200, json={"data": RES.get("rows", [{"vmid": 115, "name": "kaji-sandbox", "type": "qemu"}, {"vmid": "120", "type": "lxc"}])})
    data = {
        "/cluster/nextid": "900",
        "/pools": [{"poolid": "kaji-test", "comment": "bac à sable"}, {"poolid": "autre"}],
        "/nodes/enzo/storage": [{"storage": "local-lvm", "type": "lvmthin", "avail": 5, "total": 9, "active": 1},
                                {"storage": "local", "type": "dir", "active": 1}],
    }.get(p, UPID if request.method == "POST" else None)
    return httpx.Response(200, json={"data": data})


@pytest.fixture
def api(client):
    CALLS.clear(); FAIL.clear(); RES.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def test_requires_auth(client):
    for m, p in (("get", "/nextid"), ("get", "/pools"), ("get", "/nodes/enzo/storages")):
        assert getattr(client, m)(f"/api/connections/1{p}").status_code == 401
    assert client.post("/api/connections/1/nodes/enzo/qemu", json={"name": "x"}).status_code == 401


def test_nextid_pools_and_storages(api):
    c, cid = api
    assert c.get(f"/api/connections/{cid}/nextid").json() == {"vmid": 900}
    assert [p["poolid"] for p in c.get(f"/api/connections/{cid}/pools").json()] == ["autre", "kaji-test"]
    assert [s["storage"] for s in c.get(f"/api/connections/{cid}/nodes/enzo/storages").json()] == ["local", "local-lvm"]
    assert c.get(f"/api/connections/{cid}/nodes/enzo/storages?content=bad").status_code == 422


def test_create_uses_nextid_and_posts_validated_params(api):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/nodes/enzo/qemu", json={"name": "kaji-sandbox", "pool": "kaji-test", "memory": 512, "args": "-evil"})
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo", "vmid": 900}
    method, path, form = CALLS[-1]
    assert (method, path) == ("POST", "/nodes/enzo/qemu")
    assert form["vmid"] == "900" and form["pool"] == "kaji-test" and "args" not in form


def test_create_with_explicit_vmid_skips_nextid(api):
    c, cid = api
    c.post(f"/api/connections/{cid}/nodes/enzo/qemu", json={"name": "x1", "vmid": 777})
    assert [x[1] for x in CALLS] == ["/cluster/resources", "/nodes/enzo/qemu"] and CALLS[1][2]["vmid"] == "777"      # nextid non demandé


@pytest.mark.parametrize("node", ["a;b", "-x"])
def test_invalid_node_rejected(api, node):
    c, cid = api
    assert c.post(f"/api/connections/{cid}/nodes/{node}/qemu", json={"name": "x1"}).status_code in (404, 422) and CALLS == []


def test_invalid_body_rejected_without_calling_proxmox(api):
    c, cid = api
    assert c.post(f"/api/connections/{cid}/nodes/enzo/qemu", json={"name": "a b"}).status_code == 422 and CALLS == []


def test_win11_without_disk_refused_and_audited(api):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/nodes/enzo/qemu", json={"name": "w11", "ostype": "win11", "vmid": 800})
    assert r.status_code == 422 and not any(x[0] == "POST" for x in CALLS)
    assert c.get("/api/audit").json()[0]["status"] == "error"


def test_audit_success_and_proxmox_refusal_without_secrets(api):
    c, cid = api
    c.post(f"/api/connections/{cid}/nodes/enzo/qemu", json={"name": "kaji-sandbox", "pool": "kaji-test"})
    FAIL.update(code=403, path="/nodes/enzo/qemu")
    assert c.post(f"/api/connections/{cid}/nodes/enzo/qemu", json={"name": "x2"}).status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("create-vm", "started"), ("create-vm", "error")]
    assert log[0]["target"] == "qemu/900@enzo" and log[0]["upid"] == UPID and "kaji-test" in log[0]["detail"]
    assert SECRET not in c.get("/api/audit").text


# ---------- identifiant déjà pris (pré-contrôle, aucun appel de création) ----------

def _vm(c, cid, **kw):
    return c.post(f"/api/connections/{cid}/nodes/enzo/qemu", json={"name": "x1", **kw})


@pytest.mark.parametrize("vmid", [115, 120])
def test_taken_vmid_is_refused_409_and_nothing_is_created(api, vmid):
    c, cid = api
    r = _vm(c, cid, vmid=vmid)
    assert r.status_code == 409 and r.json()["detail"] == "Cet identifiant est déjà utilisé" and str(vmid) not in r.text
    assert not any(x[0] == "POST" for x in CALLS)


def test_taken_vmid_refusal_is_audited_without_the_typed_value_in_the_message(api):
    c, cid = api
    _vm(c, cid, vmid=115)
    e = c.get("/api/audit").json()[0]
    assert (e["action"], e["status"], e["target"]) == ("create-vm", "error", "qemu/115@enzo") and "115" not in (e["detail"] or "")


def test_free_vmid_is_created_after_one_listing(api):
    c, cid = api
    assert _vm(c, cid, vmid=116).status_code == 202
    assert [x[1] for x in CALLS] == ["/cluster/resources", "/nodes/enzo/qemu"]


def test_automatic_vmid_does_not_list_the_machines(api):
    c, cid = api
    assert _vm(c, cid).status_code == 202 and [x[1] for x in CALLS] == ["/cluster/nextid", "/nodes/enzo/qemu"]


def test_an_empty_or_missing_listing_means_free(api):
    c, cid = api
    RES["rows"] = None
    assert _vm(c, cid, vmid=115).status_code == 202
    RES["rows"] = []
    assert _vm(c, cid, vmid=115).status_code == 202


@pytest.mark.parametrize("rows", ["texte", {"vmid": 115}, 5])
def test_an_unreadable_listing_is_refused_502_and_nothing_is_created(api, rows):
    c, cid = api
    RES["rows"] = rows
    r = _vm(c, cid, vmid=116)
    assert r.status_code == 502 and "illisible" in r.json()["detail"] and not any(x[0] == "POST" for x in CALLS)
    assert c.get("/api/audit").json()[0]["status"] == "error"


def test_entries_without_a_vmid_are_ignored(api):
    c, cid = api
    RES["rows"] = [{"name": "sans-id"}, "bizarre", None, {"vmid": None}]
    assert _vm(c, cid, vmid=116).status_code == 202


def test_a_listing_error_from_proxmox_is_audited_and_refused(api):
    c, cid = api
    FAIL.update(code=500, path="/cluster/resources")
    assert _vm(c, cid, vmid=116).status_code == 502 and not any(x[0] == "POST" for x in CALLS)
    assert c.get("/api/audit").json()[0]["status"] == "error"
