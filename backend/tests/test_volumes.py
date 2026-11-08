import re
from urllib.parse import parse_qs, unquote

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:imgdel:local:kaji@pve!kaji:"
B1 = "vzdump-qemu-100-2026_11_01-02_00_00.vma.zst"
B2 = "vzdump-lxc-101-2026_11_02-02_00_00.tar.zst"
CALLS: list[dict] = []
ST: dict = {}
CONTENT_OK = {"iso", "vztmpl", "snippets", "import", "backup", "images", "rootdir"}


def vol(volid, content, **kw):
    return {"volid": volid, "content": content, "format": "raw", "size": 1, **kw}


def _contents():
    return {
        "backup": [vol(f"local:backup/{B1}", "backup", vmid=100, protected=0), vol(f"local:backup/{B2}", "backup", vmid=101, protected=1)],
        "iso": [vol("local:iso/debian.iso", "iso")],
        "vztmpl": [vol("local:vztmpl/debian-12.tar.zst", "vztmpl")],
        "snippets": [vol("local:snippets/ci.yaml", "snippets")],
        "import": [vol("local:import/d.qcow2", "import")],
    }


def _query(request):
    return {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}


def _handler(request: httpx.Request) -> httpx.Response:
    raw = unquote(request.url.raw_path.decode().split("?")[0]).removeprefix("/api2/json")
    body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    call = {"method": request.method, "path": raw, "query": _query(request), "body": body}
    CALLS.append(call)
    if ST.get("fail") and request.method != "GET":
        return httpx.Response(403, json={"data": None, "message": SECRET})
    if request.method == "GET" and raw == "/nodes/enzo/storage/local/content":
        c = call["query"].get("content")
        if set(call["query"]) - {"content", "vmid"} or c not in CONTENT_OK:
            return httpx.Response(400, json={"data": None, "message": "paramètre refusé"})
        return httpx.Response(200, json={"data": ST.get("content", _contents()).get(c, [])})
    m = re.fullmatch(r"/nodes/enzo/storage/local/content/(.+)", raw)
    if m and request.method == "DELETE":
        if call["query"] or body:
            return httpx.Response(400, json={"data": None, "message": "pas de paramètre"})
        return httpx.Response(200, json={"data": UPID})
    if m and request.method == "PUT":
        if set(body) - {"notes", "protected"} or body.get("protected") not in ("0", "1"):
            return httpx.Response(400, json={"data": None, "message": "paramètre refusé"})
        return httpx.Response(200, json={"data": None})
    if raw == "/nodes/enzo/storage/local/prunebackups":
        params = call["query"] if request.method == "GET" else body
        if set(params) - {"prune-backups", "vmid", "type"} or ("type" in params and params["type"] not in ("qemu", "lxc")):
            return httpx.Response(400, json={"data": None, "message": "paramètre refusé"})
        if "prune-backups" in params and not re.fullmatch(r"(keep-(all|last|hourly|daily|weekly|monthly|yearly)=[0-9]+)(,keep-[a-z]+=[0-9]+)*", params["prune-backups"]):
            return httpx.Response(400, json={"data": None, "message": "prune-backups invalide"})
        if request.method == "GET":
            return httpx.Response(200, json={"data": ST.get("prune", PRUNE)})
        if request.method == "DELETE":
            return httpx.Response(200, json={"data": UPID})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


PRUNE = [
    {"volid": f"local:backup/{B1}", "vmid": 100, "type": "qemu", "ctime": 1762000000, "mark": "remove"},
    {"volid": "local:backup/vzdump-qemu-100-2026_11_03-02_00_00.vma.zst", "vmid": 100, "type": "qemu", "ctime": 1762200000, "mark": "keep"},
    {"volid": f"local:backup/{B2}", "vmid": 101, "type": "lxc", "ctime": 1762100000, "mark": "protected"},
    {"volid": "local:backup/vzdump-qemu-102-x.vma", "vmid": 102, "type": "qemu", "ctime": 1762100000, "mark": "renamed"},
    {"volid": "local:backup/vzdump-qemu-103-2026_10_01-02_00_00.vma", "vmid": 103, "type": "qemu", "ctime": 1759000000, "mark": "remove"},
]


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def base(cid, storage="local"):
    return f"/api/connections/{cid}/nodes/enzo/storage/{storage}"


def writes():
    return [x for x in CALLS if x["method"] != "GET"]


def audit_pairs(c):
    return [(i["action"], i["status"]) for i in c.get("/api/audit").json()]


# ---------------------------------------------------------------- protéger
def test_protect_and_unprotect(api):
    c, cid = api
    assert c.put(f"{base(cid)}/backups/{B1}/protect", json={"protected": True}).json() == {"volid": f"local:backup/{B1}", "protected": True}
    assert writes()[-1]["path"] == f"/nodes/enzo/storage/local/content/local:backup/{B1}" and writes()[-1]["body"] == {"protected": "1"}
    assert c.put(f"{base(cid)}/backups/{B2}/protect", json={"protected": False}).status_code == 200
    assert writes()[-1]["body"] == {"protected": "0"}
    assert ("backup-protect", "started") in audit_pairs(c) and ("backup-unprotect", "started") in audit_pairs(c)


@pytest.mark.parametrize("name", ["vzdump-qemu-999-2026_11_01-02_00_00.vma", "../etc", "backup/vm/100/2026", "vzdump-qemu-100-2026_11_01-02_00_00.vma.zst/..", "x"])
def test_protect_unknown_or_malformed_volume(api, name):
    c, cid = api
    assert c.put(f"{base(cid)}/backups/{name}/protect", json={"protected": True}).status_code in (404, 405, 422) and not writes()          # 405 : « ../ » est normalisé par le client avant l'envoi


def test_protect_body_validated(api):
    c, cid = api
    assert c.put(f"{base(cid)}/backups/{B1}/protect", json={}).status_code == 422
    assert c.put(f"{base(cid)}/backups/{B1}/protect", json={"protected": "peut-être"}).status_code == 422 and not writes()


def test_protect_refuses_a_volume_that_is_not_a_backup(api):
    c, cid = api
    ST["content"] = {"backup": [vol(f"local:backup/{B1}", "iso")]}
    assert c.put(f"{base(cid)}/backups/{B1}/protect", json={"protected": True}).status_code == 409 and not writes()


# ---------------------------------------------------------------- supprimer un fichier
@pytest.mark.parametrize("kind,name", [("iso", "debian.iso"), ("vztmpl", "debian-12.tar.zst"), ("snippets", "ci.yaml"), ("import", "d.qcow2")])
def test_delete_file_ok(api, kind, name):
    c, cid = api
    r = c.delete(f"{base(cid)}/files/{kind}/{name}", params={"confirm": "true", "typed": name})
    assert r.status_code == 200 and r.json() == {"upid": UPID, "deleted": f"local:{kind}/{name}"}
    assert writes() == [{"method": "DELETE", "path": f"/nodes/enzo/storage/local/content/local:{kind}/{name}", "query": {}, "body": {}}]


def test_delete_file_needs_confirm_and_exact_name(api):
    c, cid = api
    u = f"{base(cid)}/files/iso/debian.iso"
    assert c.delete(u).status_code == 400
    assert c.delete(u, params={"confirm": "true"}).status_code == 400
    for typed in ("Debian.iso", "debian.iso ", "debian", ""):
        assert c.delete(u, params={"confirm": "true", "typed": typed}).status_code == 400
    assert c.delete(u, params={"typed": "debian.iso"}).status_code == 400
    assert not writes()


@pytest.mark.parametrize("kind", ["images", "rootdir", "backup", "iso/..", "autre"])
def test_delete_file_refuses_other_kinds(api, kind):
    """Disques de machines et sauvegardes : jamais par cette route, même avec toutes les confirmations."""
    c, cid = api
    ST["content"] = {k: [vol(f"local:{k}/vm-100-disk-0", k)] for k in ("images", "rootdir", "backup", "autre")}      # le volume EXISTE : seule la route le protège
    r = c.delete(f"{base(cid)}/files/{kind}/vm-100-disk-0", params={"confirm": "true", "typed": "vm-100-disk-0"})
    assert r.status_code in (404, 422) and not writes()
    assert r.status_code == 422 or kind == "iso/.."          # « iso/.. » : chemin normalisé avant l'envoi, la route n'existe pas (404)


@pytest.mark.parametrize("name", [".hidden.iso", "a b.iso", "a;b.iso", "é.iso", "x" * 260 + ".iso"])
def test_delete_file_name_validated(api, name):
    c, cid = api
    assert c.delete(f"{base(cid)}/files/iso/{name}", params={"confirm": "true", "typed": name}).status_code == 422 and not CALLS


def test_delete_file_unknown_404(api):
    c, cid = api
    assert c.delete(f"{base(cid)}/files/iso/absente.iso", params={"confirm": "true", "typed": "absente.iso"}).status_code == 404 and not writes()


def test_delete_file_refuses_volume_of_other_type(api):
    c, cid = api
    ST["content"] = {"iso": [vol("local:iso/debian.iso", "images")]}
    assert c.delete(f"{base(cid)}/files/iso/debian.iso", params={"confirm": "true", "typed": "debian.iso"}).status_code == 409 and not writes()


# ---------------------------------------------------------------- élagage : aperçu
def test_preview_shapes_marks_and_counts(api):
    c, cid = api
    r = c.post(f"{base(cid)}/prune/preview", json={"retention": {"keep_last": 1}, "vmid": 100, "guest_type": "qemu"})
    assert r.status_code == 200
    j = r.json()
    assert j["remove"] == 2 and j["counts"] == {"keep": 1, "remove": 2, "protected": 1, "renamed": 1}
    assert [i["mark"] for i in j["items"]] == ["keep", "remove", "protected", "renamed", "remove"] and j["items"][0]["date"]
    assert [i["vmid"] for i in j["items"]] == [100, 100, 101, 102, 103] and j["items"][0]["ctime"] > j["items"][1]["ctime"]
    assert CALLS[-1]["method"] == "GET" and CALLS[-1]["query"] == {"prune-backups": "keep-last=1", "vmid": "100", "type": "qemu"} and not writes()


def test_preview_without_rules_uses_the_storage_config(api):
    c, cid = api
    assert c.post(f"{base(cid)}/prune/preview", json={}).status_code == 200
    assert CALLS[-1]["query"] == {} and not writes()


def test_preview_unknown_marks_never_count_as_remove(api):
    c, cid = api
    ST["prune"] = [{"volid": "local:backup/x", "mark": "delete"}, {"volid": "local:backup/y", "mark": "REMOVE"}, {"volid": 5}, "x", {"volid": "local:backup/z", "mark": "remove"}]
    j = c.post(f"{base(cid)}/prune/preview", json={}).json()
    assert j["remove"] == 1 and [i["mark"] for i in j["items"]] == [None, None, "remove"]


@pytest.mark.parametrize("b", [
    {"retention": {}}, {"retention": {"keep_all": True, "keep_last": 3}}, {"retention": {"keep_last": 0}}, {"retention": {"keep_last": 10000}},
    {"vmid": 99}, {"vmid": 1000000000}, {"guest_type": "openvz"}, {"vmid": "abc"},
])
def test_preview_validated_without_call(api, b):
    c, cid = api
    assert c.post(f"{base(cid)}/prune/preview", json=b).status_code == 422 and not CALLS


# ---------------------------------------------------------------- élagage : exécution
def run(c, cid, **b):
    return c.post(f"{base(cid)}/prune", json={"retention": {"keep_last": 1}, "confirm": True, "type_name": "local", "expected_remove": 2, **b})


def test_prune_runs_with_the_same_params_as_the_preview(api):
    c, cid = api
    r = run(c, cid, vmid=100)
    assert r.status_code == 200 and r.json() == {"upid": UPID, "node": "enzo", "removed": 2}
    preview, delete = CALLS[-2], CALLS[-1]
    assert preview["method"] == "GET" and delete["method"] == "DELETE"
    assert preview["query"] == delete["query"] == {"prune-backups": "keep-last=1", "vmid": "100"} and delete["body"] == {}
    assert len(writes()) == 1


def test_prune_refused_when_the_count_changed(api):
    c, cid = api
    r = run(c, cid, expected_remove=1)
    assert r.status_code == 409 and "2" in r.json()["detail"] and not writes()
    assert run(c, cid, expected_remove=3).status_code == 409 and not writes()
    assert run(c, cid, expected_remove=0).status_code == 409 and not writes()


def test_prune_refused_when_nothing_to_remove(api):
    c, cid = api
    ST["prune"] = [PRUNE[1], PRUNE[2]]
    assert run(c, cid, expected_remove=0).status_code == 422 and not writes()


def test_prune_needs_confirm_and_exact_storage_name(api):
    c, cid = api
    assert run(c, cid, confirm=False).status_code == 400
    for typed in (None, "", "Local", "local ", "autre"):
        assert run(c, cid, type_name=typed).status_code == 400
    assert not writes() and not [x for x in CALLS if x["method"] == "GET" and "prunebackups" in x["path"]]


@pytest.mark.parametrize("b", [{"expected_remove": -1}, {"expected_remove": 5001}, {"retention": {"keep_all": True, "keep_daily": 2}}, {"vmid": 5}])
def test_prune_validated_without_write(api, b):
    c, cid = api
    assert run(c, cid, **b).status_code == 422 and not writes()


def test_prune_without_retention_uses_storage_rules(api):
    c, cid = api
    r = c.post(f"{base(cid)}/prune", json={"confirm": True, "type_name": "local", "expected_remove": 2})
    assert r.status_code == 200 and CALLS[-1]["method"] == "DELETE" and CALLS[-1]["body"] == {} and CALLS[-1]["query"] == {}


# ---------------------------------------------------------------- audit, fuites, accès
def test_audit_and_no_leak(api):
    c, cid = api
    run(c, cid)
    run(c, cid, expected_remove=9)                                       # refus
    c.delete(f"{base(cid)}/files/iso/debian.iso")                        # refus
    ST["fail"] = True
    r = run(c, cid)
    assert r.status_code == 502 and SECRET not in r.text
    pairs = audit_pairs(c)
    for a in (("storage-prune", "started"), ("storage-prune", "error"), ("file-delete", "error")):
        assert a in pairs
    assert SECRET not in c.get("/api/audit").text


def test_requires_login(client):
    b = "/api/connections/1/nodes/enzo/storage/local"
    assert client.put(f"{b}/backups/{B1}/protect", json={"protected": True}).status_code == 401
    assert client.delete(f"{b}/files/iso/a.iso").status_code == 401
    assert client.post(f"{b}/prune/preview", json={}).status_code == 401
    assert client.post(f"{b}/prune", json={}).status_code == 401
