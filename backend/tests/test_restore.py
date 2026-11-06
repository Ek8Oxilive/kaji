import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.restorespec import RestoreBody, parse_volid, restore_request

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:pve1:0001A2B3:00C4D5E6:67890ABC:qmrestore:120:kaji@pve!kaji:"

F_VM = "vzdump-qemu-100-2026_11_02-02_00_01.vma.zst"
F_CT = "vzdump-lxc-200-2026_11_01-02_00_01.tar.zst"
VM_VOLID = f"local:backup/{F_VM}"
CT_VOLID = f"local:backup/{F_CT}"
LISTING = [
    {"volid": VM_VOLID, "content": "backup", "format": "vma.zst", "vmid": 100},
    {"volid": CT_VOLID, "content": "backup", "format": "tar.zst", "vmid": 200},
    {"content": "backup"}, "illisible",
]
VMS = [{"type": "qemu", "vmid": 100, "node": "pve1"}, {"type": "lxc", "vmid": 200, "node": "pve2"},
       {"type": "qemu", "vmid": "301", "node": "pve2"}, {"type": "qemu"}, "illisible"]
CALLS: list[dict] = []
STATE: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api2/json")
    CALLS.append({"method": request.method, "path": path, "params": dict(request.url.params),
                  "form": dict(httpx.QueryParams(request.content.decode()))})
    key = f"{request.method} {path}"
    if STATE.get("fail") and STATE["fail"] in key:
        return httpx.Response(STATE.get("code", 500), json={"data": None})
    # Le faux doit se comporter comme Proxmox sur les paramètres qui comptent : s'il répondait pareil quoi qu'on demande,
    # un test passerait même si le code demandait la mauvaise chose (mutation relevée à la relecture).
    if request.method == "GET" and path.endswith("/content"):
        if request.url.params.get("content") != "backup":
            return httpx.Response(200, json={"data": []})            # sans `content=backup` : pas les sauvegardes
        return httpx.Response(200, json={"data": STATE.get("listing", LISTING)})
    if request.method == "GET" and path == "/cluster/nextid":
        return httpx.Response(200, json={"data": STATE.get("nextid", "120")})
    if request.method == "GET" and path == "/cluster/resources":
        if request.url.params.get("type") != "vm":                   # `type=storage` : des stockages, aucun `vmid`
            return httpx.Response(200, json={"data": [{"type": "storage", "storage": "local", "node": "pve1"}]})
        return httpx.Response(200, json={"data": STATE.get("vms", VMS)})
    if request.method == "POST":
        return httpx.Response(200, json={"data": UPID})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    STATE.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def writes():
    return [c for c in CALLS if c["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()[::-1]


def url(cid, node="pve1"):
    return f"/api/connections/{cid}/nodes/{node}/restore"


GOOD_VM = {"volid": VM_VOLID, "vmid": 150, "storage": "local-lvm"}
GOOD_CT = {"volid": CT_VOLID, "vmid": 250, "storage": "local-lvm"}


# ============================== restauration d'une VM ===============================================================

def test_requires_auth(client):
    assert client.post("/api/connections/1/nodes/pve1/restore", json=GOOD_VM).status_code == 401


def test_unknown_connection(api):
    assert api[0].post(url(999), json=GOOD_VM).status_code == 404


def test_restore_vm_sends_exact_params_to_the_vm_endpoint(api):
    c, cid = api
    r = c.post(url(cid), json=GOOD_VM)
    assert r.status_code == 202
    assert r.json() == {"upid": UPID, "node": "pve1", "vmid": 150, "type": "qemu", "archive": F_VM}
    assert len(writes()) == 1 and writes()[0]["path"] == "/nodes/pve1/qemu"
    assert writes()[0]["form"] == {"vmid": "150", "archive": VM_VOLID, "storage": "local-lvm", "unique": "1"}


def test_restore_lxc_sends_exact_params_to_the_lxc_endpoint(api):
    c, cid = api
    r = c.post(url(cid, "pve2"), json=GOOD_CT)
    assert r.status_code == 202 and r.json()["type"] == "lxc" and r.json()["archive"] == F_CT
    assert len(writes()) == 1 and writes()[0]["path"] == "/nodes/pve2/lxc"
    assert writes()[0]["form"] == {"vmid": "250", "ostemplate": CT_VOLID, "restore": "1", "storage": "local-lvm",
                                   "unique": "1"}


def test_type_comes_from_the_file_name_never_from_the_caller(api):
    c, cid = api
    c.post(url(cid), json={**GOOD_VM, "type": "lxc", "gtype": "lxc", "kind": "lxc"})
    assert writes()[0]["path"] == "/nodes/pve1/qemu" and "ostemplate" not in writes()[0]["form"]
    CALLS.clear()
    c.post(url(cid), json={**GOOD_CT, "type": "qemu"})
    assert writes()[0]["path"] == "/nodes/pve1/lxc" and "archive" not in writes()[0]["form"]


def test_storage_is_always_sent(api):
    c, cid = api
    c.post(url(cid), json=GOOD_CT)
    assert writes()[0]["form"]["storage"] == "local-lvm"


def test_machine_is_never_started_and_force_is_never_sent(api):
    c, cid = api
    c.post(url(cid), json={**GOOD_VM, "start": True, "force": True, "live-restore": True})
    form = writes()[0]["form"]
    assert "force" not in form and "start" not in form and "live-restore" not in form


def test_unknown_fields_are_never_forwarded(api):
    c, cid = api
    extra = {"force": 1, "start": 1, "bwlimit": 1, "script": "/x", "hookscript": "x", "cores": 64, "name": "x",
             "ostemplate": "local:vztmpl/x", "archive": "/etc/passwd", "node": "evil", "unprivileged": 0}
    assert c.post(url(cid), json={**GOOD_VM, **extra}).status_code == 202
    assert writes()[0]["form"] == {"vmid": "150", "archive": VM_VOLID, "storage": "local-lvm", "unique": "1"}


def test_pool_is_forwarded_and_unique_can_be_turned_off(api):
    c, cid = api
    c.post(url(cid), json={**GOOD_VM, "pool": "kaji-test", "unique": False})
    assert writes()[0]["form"] == {"vmid": "150", "archive": VM_VOLID, "storage": "local-lvm", "pool": "kaji-test"}


# ============================== identifiant ========================================================================

def test_default_vmid_is_the_next_free_id(api):
    c, cid = api
    STATE["nextid"] = "177"
    r = c.post(url(cid), json={"volid": VM_VOLID, "storage": "local-lvm"})
    assert r.status_code == 202 and r.json()["vmid"] == 177
    assert writes()[0]["form"]["vmid"] == "177"
    assert any(x["path"] == "/cluster/nextid" for x in CALLS)


@pytest.mark.parametrize("bad", [None, "", "abc", [], {"a": 1}])
def test_unreadable_nextid_is_a_502_and_nothing_is_written(api, bad):
    c, cid = api
    STATE["nextid"] = bad
    assert c.post(url(cid), json={"volid": VM_VOLID, "storage": "local-lvm"}).status_code == 502
    assert writes() == []
    assert [(e["action"], e["status"]) for e in audit(c)] == [("backup-restore", "error")]


@pytest.mark.parametrize("used", [100, 200, 301])
def test_used_id_is_refused_and_nothing_is_written(api, used):
    """100 = VM sur pve1, 200 = LXC sur un AUTRE nœud, 301 = identifiant renvoyé en texte par Proxmox."""
    c, cid = api
    r = c.post(url(cid), json={**GOOD_VM, "vmid": used})
    assert r.status_code == 409 and "ne remplace jamais" in r.json()["detail"]
    assert writes() == []


def test_used_id_is_refused_for_a_container_backup_too(api):
    c, cid = api
    assert c.post(url(cid), json={**GOOD_CT, "vmid": 100}).status_code == 409 and writes() == []


def test_used_ids_are_read_from_vm_resources_only(api):
    """Garde-fou « identifiant déjà utilisé » : il lit `/cluster/resources?type=vm`. Avec un autre `type`, Proxmox ne
    renverrait aucun `vmid` et la protection ne protégerait plus rien sans qu'aucun test ne s'en aperçoive."""
    c, cid = api
    c.post(url(cid), json={**GOOD_VM, "vmid": 101})
    reads = [x for x in CALLS if x["path"] == "/cluster/resources"]
    assert len(reads) == 1 and reads[0]["params"] == {"type": "vm"}
    assert c.post(url(cid), json={**GOOD_VM, "vmid": 100}).status_code == 409      # et le résultat protège bel et bien


def test_force_cannot_be_used_to_overwrite(api):
    c, cid = api
    r = c.post(url(cid), json={**GOOD_VM, "vmid": 100, "force": True, "overwrite": True})
    assert r.status_code == 409 and writes() == []


def test_free_id_is_accepted(api):
    c, cid = api
    assert c.post(url(cid), json={**GOOD_VM, "vmid": 101}).status_code == 202


def test_resources_error_is_502_and_nothing_is_written(api):
    c, cid = api
    STATE["fail"] = "/cluster/resources"
    r = c.post(url(cid), json=GOOD_VM)
    assert r.status_code == 502 and writes() == [] and SECRET not in r.text


@pytest.mark.parametrize("vmid", [99, 0, -1, 1000000000, "abc", 150.5, True])
def test_invalid_vmid_refused_and_nothing_called(api, vmid):
    c, cid = api
    assert c.post(url(cid), json={**GOOD_VM, "vmid": vmid}).status_code == 422 and CALLS == []


# ============================== sauvegarde source ===================================================================

@pytest.mark.parametrize("volid", [
    "", "local", f"backup/{F_VM}", F_VM, f"local:{F_VM}", f"local:iso/{F_VM}", f"local:backup/{F_VM}.bak",
    f"local:backup/../{F_VM}", f"local:backup/sub/{F_VM}", f"/var/lib/vz/dump/{F_VM}", f"local:backup/{F_VM}\n",
    f"local:backup/{F_VM}\r", f"local:backup/{F_VM}\x00", f" local:backup/{F_VM}", f"local:backup/{F_VM} ",
    f"-x:backup/{F_VM}", f"a b:backup/{F_VM}", f"a;b:backup/{F_VM}", f"{'s' * 41}:backup/{F_VM}",
    "local:backup/vzdump-qemu-100-2026_11_02-02_00_01.vma.xz", "local:backup/vzdump-qemu-100-2026_11_02-02_00_01.exe",
    "local:backup/vzdump-ct-100-2026_11_02-02_00_01.tar", "local:backup/vzdump-qemu-1-2026_11_02-02_00_01.vma",
    "pbs:backup/ct/200/2026-11-01T02:00:01Z", "local:backup/vzdump-qemu-100-2026_11_02-02_00_01.log",
    "local:backup/vzdump-qemu-100-2026_11_02-02_00_01.vma.zst:extra", None, 7, [VM_VOLID], {"v": VM_VOLID},
])
def test_invalid_volid_refused_and_nothing_called(api, volid):
    c, cid = api
    r = c.post(url(cid), json={**GOOD_VM, "volid": volid})
    assert r.status_code == 422 and CALLS == []
    assert SECRET not in r.text


def test_missing_volid_or_storage_refused(api):
    c, cid = api
    assert c.post(url(cid), json={"storage": "local-lvm", "vmid": 150}).status_code == 422
    assert c.post(url(cid), json={"volid": VM_VOLID, "vmid": 150}).status_code == 422
    assert CALLS == []


def test_unknown_backup_is_404_and_nothing_is_written(api):
    c, cid = api
    gone = "local:backup/vzdump-qemu-999-2026_01_01-00_00_00.vma.zst"
    r = c.post(url(cid), json={**GOOD_VM, "volid": gone})
    assert r.status_code == 404 and writes() == []


def test_same_file_name_on_another_storage_is_not_matched(api):
    c, cid = api
    STATE["listing"] = [{"volid": f"autre:backup/{F_VM}", "content": "backup"}]
    assert c.post(url(cid), json=GOOD_VM).status_code == 404 and writes() == []


def test_non_backup_volume_is_refused(api):
    c, cid = api
    STATE["listing"] = [{"volid": VM_VOLID, "content": "images"}]
    assert c.post(url(cid), json=GOOD_VM).status_code == 409 and writes() == []


def test_backup_is_looked_up_with_content_backup(api):
    c, cid = api
    c.post(url(cid), json=GOOD_VM)
    first = CALLS[0]
    assert first["path"] == "/nodes/pve1/storage/local/content" and first["params"] == {"content": "backup"}


def test_listing_error_is_502_and_nothing_is_written(api):
    c, cid = api
    STATE["fail"] = "/content"
    r = c.post(url(cid), json=GOOD_VM)
    assert r.status_code == 502 and writes() == [] and SECRET not in r.text


# ============================== destination ========================================================================

@pytest.mark.parametrize("storage", ["", "a b", "-x", "a;b", "s" * 41, "local\n", "local\r", "a/b", "..", 7, None])
def test_invalid_destination_storage_refused_and_nothing_called(api, storage):
    c, cid = api
    assert c.post(url(cid), json={**GOOD_VM, "storage": storage}).status_code == 422 and CALLS == []


@pytest.mark.parametrize("pool", ["", "a b", "-x", "a;b", "p" * 41, "p\n", "a/b", 7])
def test_invalid_pool_refused_and_nothing_called(api, pool):
    c, cid = api
    assert c.post(url(cid), json={**GOOD_VM, "pool": pool}).status_code == 422 and CALLS == []


@pytest.mark.parametrize("node", ["-pve", "pve_1", "pve.1", "p" * 64])
def test_invalid_node_refused_and_nothing_called(api, node):
    c, cid = api
    assert c.post(url(cid, node), json=GOOD_VM).status_code in (404, 422) and CALLS == []


def test_invalid_value_is_not_echoed(api):
    c, cid = api
    r = c.post(url(cid), json={**GOOD_VM, "volid": "valeur-secrete-saisie"})
    assert r.status_code == 422 and "valeur-secrete-saisie" not in r.text


# ============================== erreurs et audit ===================================================================

@pytest.mark.parametrize("code", [401, 403, 500])
def test_proxmox_error_on_create_is_502_without_secret(api, code):
    c, cid = api
    STATE.update(fail="POST", code=code)
    r = c.post(url(cid), json=GOOD_VM)
    assert r.status_code == 502 and SECRET not in r.text


def test_audit_success_has_source_destination_and_upid(api):
    c, cid = api
    c.post(url(cid), json={**GOOD_VM, "pool": "kaji-test"})
    log = audit(c)
    assert [(e["action"], e["status"], e["target"]) for e in log] == [("backup-restore", "started", "qemu/150@pve1")]
    assert log[0]["upid"] == UPID
    assert VM_VOLID in log[0]["detail"] and "stockage=local-lvm" in log[0]["detail"] and "pool=kaji-test" in log[0]["detail"]
    assert SECRET not in c.get("/api/audit").text


def test_audit_records_every_refusal_and_error(api):
    c, cid = api
    c.post(url(cid), json={**GOOD_VM, "vmid": 100})                                             # id utilisé
    c.post(url(cid), json={**GOOD_VM, "volid": "local:backup/vzdump-qemu-999-2026_01_01-00_00_00.vma.zst"})  # introuvable
    STATE["listing"] = [{"volid": VM_VOLID, "content": "images"}]
    c.post(url(cid), json=GOOD_VM)                                                              # pas une sauvegarde
    STATE.clear()
    STATE.update(fail="POST", code=500)
    c.post(url(cid), json=GOOD_VM)                                                              # erreur Proxmox
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("backup-restore", "error")] * 4
    assert "déjà utilisé" in log[0]["detail"] and "introuvable" in log[1]["detail"]
    assert all(e["upid"] is None for e in log)
    assert SECRET not in c.get("/api/audit").text


def test_restore_route_does_not_shadow_creation_routes(api):
    c, cid = api
    assert c.post(f"/api/connections/{cid}/nodes/pve1/qemu", json={}).status_code != 404
    assert c.post(f"/api/connections/{cid}/nodes/pve1/lxc", json={}).status_code != 404


# ============================== unitaire ===========================================================================

def test_parse_volid_unit():
    assert parse_volid(VM_VOLID) == ("local", F_VM, "qemu")
    assert parse_volid(CT_VOLID) == ("local", F_CT, "lxc")
    with pytest.raises(ValueError):
        parse_volid(f"local:backup/{F_VM}\n")


def test_restore_request_unit():
    b = RestoreBody(volid=CT_VOLID, storage="s", unique=False)
    assert restore_request(b, 300) == ("lxc", {"vmid": 300, "storage": "s", "ostemplate": CT_VOLID, "restore": 1})
