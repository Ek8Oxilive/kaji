import httpx
import pytest

from app.backupspec import BackupBody, _protected, shape_backups, vzdump_params
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:pve1:0001A2B3:00C4D5E6:67890ABC:vzdump:100:kaji@pve!kaji:"
DEL_UPID = "UPID:pve1:0001A2B4:00C4D5E7:67890ABD:imgdel:vzdump-qemu-100:kaji@pve!kaji:"

V_NEW = "vzdump-qemu-100-2026_11_02-02_00_01.vma.zst"
V_OLD = "vzdump-qemu-100-2026_10_01-02_00_01.vma.zst"
V_LXC = "vzdump-lxc-200-2026_11_01-02_00_01.tar.zst"
V_PROT = "vzdump-qemu-101-2026_09_01-02_00_01.vma.gz"
LISTING = [
    {"volid": f"local:backup/{V_OLD}", "content": "backup", "format": "vma.zst", "size": 5, "ctime": 1700000000, "vmid": 100},
    {"volid": f"local:backup/{V_NEW}", "content": "backup", "format": "vma.zst", "size": 7, "ctime": 1700005000, "vmid": 100,
     "notes": "avant mise à jour"},
    {"volid": f"local:backup/{V_LXC}", "content": "backup", "format": "tar.zst", "size": 3, "ctime": 1700002000, "vmid": 200},
    {"volid": f"local:backup/{V_PROT}", "content": "backup", "format": "vma.gz", "size": 1, "ctime": 1699000000,
     "vmid": 101, "protected": 1},
    {"content": "backup"}, "illisible",
]
CALLS: list[dict] = []
STATE: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api2/json")
    CALLS.append({"method": request.method, "path": path, "raw": request.url.raw_path.decode(),
                  "params": dict(request.url.params), "form": dict(httpx.QueryParams(request.content.decode()))})
    if STATE.get("fail") == request.method:
        return httpx.Response(STATE.get("code", 500), json={"data": None})
    if request.method == "GET" and path.endswith("/content"):
        return httpx.Response(200, json={"data": STATE.get("listing", LISTING)})
    if request.method == "POST" and path.endswith("/vzdump"):
        return httpx.Response(200, json={"data": UPID})
    if request.method == "DELETE":
        return httpx.Response(200, json={"data": DEL_UPID})
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


def list_url(cid, node="pve1", storage="local", query=""):
    return f"/api/connections/{cid}/nodes/{node}/storage/{storage}/backups{query}"


def del_url(cid, volume=V_OLD, query="", node="pve1", storage="local"):
    return f"/api/connections/{cid}/nodes/{node}/storage/{storage}/backups/{volume}{query}"


def post_url(cid, node="pve1"):
    return f"/api/connections/{cid}/nodes/{node}/backups"


GOOD = {"vmid": 100, "storage": "local", "mode": "snapshot", "compress": "zstd"}


# ============================== lister ==============================================================================

def test_list_requires_auth(client):
    assert client.get("/api/connections/1/nodes/pve1/storage/local/backups").status_code == 401


def test_list_unknown_connection(api):
    assert api[0].get(list_url(999)).status_code == 404


def test_list_newest_first_with_type_and_deletable(api):
    c, cid = api
    r = c.get(list_url(cid)).json()
    assert [b["name"] for b in r] == [V_NEW, V_LXC, V_OLD, V_PROT]
    new = r[0]
    assert new["volid"] == f"local:backup/{V_NEW}" and new["type"] == "qemu" and new["vmid"] == 100
    assert new["notes"] == "avant mise à jour" and new["protected"] is False and new["deletable"] is True
    assert new["date"] == "2023-11-14T23:36:40+00:00"
    assert r[1]["type"] == "lxc" and r[1]["vmid"] == 200
    prot = r[3]
    assert prot["protected"] is True and prot["deletable"] is False


def test_list_asks_proxmox_for_backups_only(api):
    c, cid = api
    c.get(list_url(cid))
    assert CALLS[-1]["path"] == "/nodes/pve1/storage/local/content" and CALLS[-1]["params"] == {"content": "backup"}


def test_list_filter_by_vmid(api):
    c, cid = api
    assert [b["name"] for b in c.get(list_url(cid, query="?vmid=100")).json()] == [V_NEW, V_OLD]
    assert c.get(list_url(cid, query="?vmid=999")).json() == []
    assert c.get(list_url(cid, query="?vmid=abc")).status_code == 422


def test_list_ignores_unreadable_entries(api):
    assert len(api[0].get(list_url(api[1])).json()) == 4


@pytest.mark.parametrize("kw", [{"node": "-pve"}, {"node": "pve_1"}, {"storage": "a b"}, {"storage": "-x"}])
def test_list_invalid_node_or_storage_refused_without_call(api, kw):
    c, cid = api
    assert c.get(list_url(cid, **kw)).status_code in (404, 422) and CALLS == []


def test_list_proxmox_error_is_502_without_secret(api):
    c, cid = api
    STATE.update(fail="GET", code=500)
    r = c.get(list_url(cid))
    assert r.status_code == 502 and SECRET not in r.text


# ============================== lancer ==============================================================================

def test_create_requires_auth(client):
    assert client.post("/api/connections/1/nodes/pve1/backups", json=GOOD).status_code == 401


def test_create_sends_exact_whitelisted_params_and_never_prunes(api):
    c, cid = api
    r = c.post(post_url(cid), json={**GOOD, "notes": "{{guestname}} · avant migration"})
    assert r.status_code == 200 and r.json() == {"upid": UPID, "node": "pve1", "vmid": 100, "storage": "local"}
    assert len(writes()) == 1 and writes()[0]["path"] == "/nodes/pve1/vzdump"
    assert writes()[0]["form"] == {"vmid": "100", "storage": "local", "mode": "snapshot", "compress": "zstd",
                                   "remove": "0", "notes-template": "{{guestname}} · avant migration"}


def test_create_remove_is_zero_even_with_defaults(api):
    c, cid = api
    c.post(post_url(cid), json={"vmid": 100, "storage": "local"})
    assert writes()[0]["form"] == {"vmid": "100", "storage": "local", "mode": "snapshot", "compress": "zstd", "remove": "0"}


@pytest.mark.parametrize("compress,sent", [("zstd", "zstd"), ("gzip", "gzip"), ("lzo", "lzo"), ("none", "0")])
def test_create_compression_values(api, compress, sent):
    c, cid = api
    assert c.post(post_url(cid), json={**GOOD, "compress": compress}).status_code == 200
    assert writes()[0]["form"]["compress"] == sent


@pytest.mark.parametrize("mode", ["snapshot", "suspend", "stop"])
def test_create_modes(api, mode):
    c, cid = api
    assert c.post(post_url(cid), json={**GOOD, "mode": mode}).status_code == 200
    assert writes()[0]["form"]["mode"] == mode


def test_create_unknown_fields_are_never_forwarded(api):
    c, cid = api
    extra = {"script": "/tmp/x.sh", "mailto": "a@b.c", "dumpdir": "/tmp", "bwlimit": 1, "protected": 1, "pool": "p",
             "exclude-path": "/", "notes-template": "x", "remove": 1, "all": 1, "node": "evil", "vmid2": 3}
    assert c.post(post_url(cid), json={**GOOD, **extra}).status_code == 200
    assert writes()[0]["form"] == {"vmid": "100", "storage": "local", "mode": "snapshot", "compress": "zstd",
                                   "remove": "0"}


@pytest.mark.parametrize("patch", [
    {"vmid": 99}, {"vmid": 1000000000}, {"vmid": "abc"}, {"vmid": None}, {"vmid": 100.5},
    {"storage": "a b"}, {"storage": "-x"}, {"storage": "a;b"}, {"storage": "s" * 41}, {"storage": ""},
    {"mode": "hot"}, {"mode": ""}, {"mode": "STOP"},
    {"compress": "xz"}, {"compress": "0"}, {"compress": "1"}, {"compress": ""},
    {"notes": "a\nb"}, {"notes": "a\rb"}, {"notes": "a\\nb"}, {"notes": "a\x00b"}, {"notes": "n" * 201},
])
def test_create_invalid_body_refused_and_nothing_called(api, patch):
    c, cid = api
    r = c.post(post_url(cid), json={**GOOD, **patch})
    assert r.status_code == 422 and CALLS == []
    assert SECRET not in r.text


def test_create_invalid_value_is_not_echoed(api):
    c, cid = api
    assert "evil-mode-value" not in api[0].post(post_url(api[1]), json={**GOOD, "mode": "evil-mode-value"}).text


@pytest.mark.parametrize("node", ["-pve", "pve_1", "pve.1", "p" * 64])
def test_create_invalid_node_refused_without_call(api, node):
    c, cid = api
    assert c.post(post_url(cid, node), json=GOOD).status_code in (404, 422) and CALLS == []


def test_create_audit_started_with_upid_and_no_notes_text(api):
    c, cid = api
    c.post(post_url(cid), json={**GOOD, "mode": "stop", "compress": "none", "notes": "texte-libre-de-notes"})
    log = audit(c)
    assert [(e["action"], e["status"], e["target"]) for e in log] == [("backup-create", "started", "100@pve1")]
    assert log[0]["upid"] == UPID
    assert "stockage=local" in log[0]["detail"] and "mode=stop" in log[0]["detail"] and "compression=none" in log[0]["detail"]
    assert "texte-libre-de-notes" not in c.get("/api/audit").text and SECRET not in c.get("/api/audit").text


@pytest.mark.parametrize("code", [401, 403, 500])
def test_create_proxmox_error_is_502_audited_without_secret(api, code):
    c, cid = api
    STATE.update(fail="POST", code=code)
    r = c.post(post_url(cid), json=GOOD)
    assert r.status_code == 502 and SECRET not in r.text
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("backup-create", "error")] and log[0]["upid"] is None
    assert SECRET not in c.get("/api/audit").text


# ============================== supprimer ===========================================================================

def test_delete_requires_auth(client):
    assert client.delete(f"/api/connections/1/nodes/pve1/storage/local/backups/{V_OLD}?confirm=true&name={V_OLD}").status_code == 401


def test_delete_happy_path_one_exact_call(api):
    c, cid = api
    r = c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}"))
    assert r.status_code == 200 and r.json() == {"upid": DEL_UPID, "deleted": f"local:backup/{V_OLD}"}
    assert len(writes()) == 1 and writes()[0]["method"] == "DELETE"
    # le volid complet est envoyé encodé en UN SEUL segment (`:` et `/` encodés)
    assert writes()[0]["raw"] == f"/api2/json/nodes/pve1/storage/local/content/local%3Abackup%2F{V_OLD}"


def test_delete_without_confirm_refused_and_proxmox_never_called(api):
    c, cid = api
    assert c.delete(del_url(cid, query=f"?name={V_OLD}")).status_code == 400
    assert c.delete(del_url(cid, query=f"?confirm=false&name={V_OLD}")).status_code == 400
    assert c.delete(del_url(cid)).status_code == 400
    assert CALLS == []


@pytest.mark.parametrize("typed", ["", "autre", V_NEW, V_OLD.upper(), V_OLD + " ", " " + V_OLD, V_OLD[:-1], "vzdump"])
def test_delete_wrong_name_refused_and_proxmox_never_called(api, typed):
    c, cid = api
    assert c.delete(del_url(cid), params={"confirm": "true", "name": typed}).status_code == 400
    assert CALLS == []


def test_delete_unknown_backup_is_404_and_nothing_deleted(api):
    c, cid = api
    gone = "vzdump-qemu-999-2026_01_01-00_00_00.vma.zst"
    assert c.delete(del_url(cid, gone, f"?confirm=true&name={gone}")).status_code == 404
    assert writes() == []


def test_delete_same_file_name_on_another_storage_is_not_matched(api):
    c, cid = api
    STATE["listing"] = [{"volid": f"autre:backup/{V_OLD}", "content": "backup"}]
    assert c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}")).status_code == 404
    assert writes() == []


def test_delete_protected_backup_refused_and_nothing_deleted(api):
    c, cid = api
    r = c.delete(del_url(cid, V_PROT, f"?confirm=true&name={V_PROT}"))
    assert r.status_code == 409 and "protég" in r.json()["detail"] and writes() == []


def test_delete_non_backup_volume_refused(api):
    c, cid = api
    STATE["listing"] = [{"volid": f"local:backup/{V_OLD}", "content": "images"}]
    assert c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}")).status_code == 409
    assert writes() == []


@pytest.mark.parametrize("volume", [
    "debian.iso", "..", "vzdump-qemu-100-2026_11_01-02_00_01.log", "vzdump-qemu-100-2026_11_01-02_00_01.vma.xz",
    "vzdump-qemu-100-2026_11_01-02_00_01.exe", "vzdump-qemu-1-2026_11_01-02_00_01.vma", "vzdump-ct-100-2026_11_01-02_00_01.tar",
    "ct%2F100%2F2026-11-01T02:00:01Z", "vzdump-qemu-100-2026_11_01-02_00_01.vma.zst%0a", "vzdump-qemu-100-2026_11_01-02_00_01.vma.zst%00",
    "%2e%2e%2fetc", "vzdump-qemu-100-2026_11_01-02_00_01.vma.zst;rm", "*",
])
def test_delete_invalid_volume_name_refused_without_any_call(api, volume):
    c, cid = api
    r = c.delete(del_url(cid, volume, "?confirm=true&name=x"))
    assert r.status_code in (404, 405, 422) and CALLS == []


@pytest.mark.parametrize("kw", [{"node": "-pve"}, {"node": "pve_1"}, {"storage": "a b"}, {"storage": "-x"}])
def test_delete_invalid_node_or_storage_refused_without_call(api, kw):
    c, cid = api
    r = c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}", **kw))
    assert r.status_code in (404, 422) and CALLS == []


def test_no_mass_deletion_route_exists(api):
    c, cid = api
    for url in (list_url(cid), f"/api/connections/{cid}/nodes/pve1/backups"):
        assert c.delete(url + "?confirm=true").status_code in (404, 405)
    assert writes() == []


def test_delete_listing_error_is_502_and_nothing_deleted(api):
    c, cid = api
    STATE.update(fail="GET", code=500)
    r = c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}"))
    assert r.status_code == 502 and writes() == [] and SECRET not in r.text
    assert [(e["action"], e["status"]) for e in audit(c)] == [("backup-delete", "error")]


def test_delete_proxmox_error_is_502_without_secret(api):
    c, cid = api
    STATE.update(fail="DELETE", code=403)
    r = c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}"))
    assert r.status_code == 502 and SECRET not in r.text


def test_delete_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    c.delete(del_url(cid))                                                          # sans confirm
    c.delete(del_url(cid, query="?confirm=true&name=autre"))                        # mauvais nom
    c.delete(del_url(cid, V_PROT, f"?confirm=true&name={V_PROT}"))                  # protégée
    gone = "vzdump-qemu-999-2026_01_01-00_00_00.vma.zst"
    c.delete(del_url(cid, gone, f"?confirm=true&name={gone}"))                      # introuvable
    c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}"))                     # réussie
    STATE.update(fail="DELETE", code=500)
    c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}"))                     # erreur Proxmox
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("backup-delete", "error")] * 4 + \
        [("backup-delete", "started"), ("backup-delete", "error")]
    assert log[4]["upid"] == DEL_UPID and f"local:backup/{V_OLD}" in log[4]["detail"]
    assert all(e["target"].endswith("@pve1") for e in log)
    assert SECRET not in c.get("/api/audit").text


# ============================== mise en forme (unitaire) ===========================================================

def test_vzdump_params_unit():
    p = vzdump_params(BackupBody(vmid=100, storage="local", mode="stop", compress="none"))
    assert p == {"vmid": 100, "storage": "local", "mode": "stop", "compress": "0", "remove": 0}


def test_shape_backups_tolerates_unexpected_types():
    data = [{"volid": f"local:backup/{V_NEW}", "content": 7, "format": 3, "notes": 4, "ctime": 10 ** 15, "size": "--5",
             "vmid": "²", "protected": "oui"},
            {"volid": "pbs:backup/ct/100/2026-11-01T02:00:01Z", "ctime": "x"}]
    out = shape_backups(data)
    assert len(out) == 2
    first = next(b for b in out if b["name"] == V_NEW)
    assert first["size"] is None and first["date"] is None and first["notes"] is None and first["format"] is None
    assert first["vmid"] == 100                                                     # repris du nom du fichier
    pbs = next(b for b in out if b["volid"].startswith("pbs:"))
    assert pbs["type"] is None and pbs["deletable"] is False                        # forme inconnue : pas supprimable ici


@pytest.mark.parametrize("raw", [None, False, 0, "0", "", " ", "false", "FALSE", 0.0])
def test_protected_flag_false_only_for_clearly_false_values(raw):
    assert _protected(raw) is False


@pytest.mark.parametrize("raw", [1, True, "1", "true", "True", "yes", "oui", 2, "x", [0], {"a": 1}, [], {}])
def test_protected_flag_fails_closed_for_everything_else(raw):
    assert _protected(raw) is True


@pytest.mark.parametrize("raw", ["true", "oui", 1, "1", True, [], {}])
def test_delete_refused_for_any_protected_or_unexpected_value(api, raw):
    c, cid = api
    STATE["listing"] = [{"volid": f"local:backup/{V_OLD}", "content": "backup", "protected": raw}]
    assert c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}")).status_code == 409
    assert writes() == []


@pytest.mark.parametrize("raw", ["0", 0, False, None])
def test_delete_allowed_when_protection_is_clearly_off(api, raw):
    c, cid = api
    STATE["listing"] = [{"volid": f"local:backup/{V_OLD}", "content": "backup", "protected": raw}]
    assert c.delete(del_url(cid, query=f"?confirm=true&name={V_OLD}")).status_code == 200
    assert len(writes()) == 1


def test_listing_marks_string_zero_as_not_protected_and_deletable():
    b = shape_backups([{"volid": f"local:backup/{V_OLD}", "protected": "0"}])[0]
    assert b["protected"] is False and b["deletable"] is True
