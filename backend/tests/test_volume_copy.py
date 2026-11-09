"""Copie d'un fichier vers un autre stockage / nœud (lot #148) : faux Proxmox STRICT (méthode, chemin, paramètres ; 400 sinon)."""
from urllib.parse import parse_qs, quote, unquote

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
ISO = "debian-12.iso"
BACKUP = "vzdump-qemu-100-2026_11_09-10_00_00.vma.zst"
CALLS: list[tuple[str, str, dict]] = []
SEEN: list[str] = []          # TOUTES les requêtes vers Proxmox (lectures comprises)
ST: dict = {}


def fresh():
    ST.clear()
    ST.update(noapply=False, fail=False, nodes=["enzo", "enzo2"],
              storages={"enzo": {"local": {"iso", "vztmpl", "snippets", "import", "backup"}, "local-lvm": {"images", "rootdir"}, "off": {"iso"}},
                        "enzo2": {"local": {"iso", "vztmpl", "snippets", "import", "backup"}, "local-lvm": {"images", "rootdir"}, "other": {"iso", "backup"}}},
              inactive={("enzo", "off")},
              files={("enzo", "local"): {f"local:iso/{ISO}": "iso", f"local:vztmpl/alpine.tar.zst": "vztmpl", f"local:snippets/note.yaml": "snippets", f"local:import/img.qcow2": "import",
                                         f"local:backup/{BACKUP}": "backup"},
                     ("enzo2", "local"): {}, ("enzo2", "other"): {}, ("enzo", "off"): {}})


def bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.raw_path.decode().split("?")[0].removeprefix("/api2/json")                 # chemin BRUT : le volid y est encodé (%3A, %2F)
    m = request.method
    SEEN.append(f"{m} {p}")
    query = dict(request.url.params)
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if m == "GET":
        if p == "/nodes":
            return httpx.Response(200, json={"data": [{"node": n, "status": "online"} for n in ST["nodes"]]})
        parts = p.split("/")
        if len(parts) == 4 and parts[1] == "nodes" and parts[3] == "storage":
            node, ctype = parts[2], query.get("content")
            return httpx.Response(200, json={"data": [{"storage": s, "active": 0 if (node, s) in ST["inactive"] else 1, "content": ",".join(sorted(c))}
                                                      for s, c in ST["storages"].get(node, {}).items() if ctype is None or ctype in c]})
        if len(parts) == 6 and parts[1] == "nodes" and parts[3] == "storage" and parts[5] == "content":
            files = ST["files"].get((parts[2], parts[4]))
            if ST.get("null_listing") == (parts[2], parts[4]):
                return httpx.Response(200, json={"data": None})
            if files is None:
                return httpx.Response(500, json={"data": None, "message": "storage inconnu"})
            return httpx.Response(200, json={"data": [{"volid": v, "content": c} for v, c in files.items() if query.get("content") in (None, c)]})
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if ST["fail"]:
        return httpx.Response(403, json={"data": None, "message": SECRET})
    parts = p.split("/")
    if m == "POST" and len(parts) == 7 and parts[1] == "nodes" and parts[3] == "storage" and parts[5] == "content":
        CALLS.append((m, p, body))
        if set(body) - {"target", "target_node"} or "target" not in body:
            return bad(f"paramètres refusés {sorted(set(body) - {'target', 'target_node'})}")
        if body.get("target_node") == parts[2]:
            return bad("target_node ne doit être renseigné que pour un autre nœud")
        src_node, src_storage, volid = parts[2], parts[4], unquote(parts[6])
        if volid not in ST["files"].get((src_node, src_storage), {}):
            return httpx.Response(500, json={"data": None, "message": "volume introuvable"})
        tstore, _, rest = body["target"].partition(":")
        if not ST["noapply"]:
            ST["files"].setdefault((body.get("target_node", src_node), tstore), {})[body["target"]] = ST["files"][(src_node, src_storage)][volid]
        return httpx.Response(200, json={"data": "UPID:enzo:0001:0002:0003:imgcopy::kaji@pve!kaji:"})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client):
    CALLS.clear(); SEEN.clear(); fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, kind="iso", name=ISO, node="enzo", storage="local"):
    return f"/api/connections/{cid}/nodes/{node}/storage/{storage}/copy/{kind}/{name}"


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# ---------------------------------------------------------------- copie : paramètres exacts
def test_copy_to_another_node_sends_exact_call_and_keeps_the_source(api):
    c, cid = api
    r = c.post(url(cid), json={"target_storage": "local", "target_node": "enzo2"})
    assert r.status_code == 200 and r.json()["target"] == f"local:iso/{ISO}" and r.json()["target_node"] == "enzo2" and r.json()["upid"].startswith("UPID:")
    assert CALLS == [("POST", f"/nodes/enzo/storage/local/content/{quote(f'local:iso/{ISO}', safe='')}", {"target": f"local:iso/{ISO}", "target_node": "enzo2"})]
    assert f"local:iso/{ISO}" in ST["files"][("enzo", "local")] and f"local:iso/{ISO}" in ST["files"][("enzo2", "local")]       # source intacte, copie présente


def test_copy_on_the_same_node_sends_no_target_node(api):
    c, cid = api
    ST["storages"]["enzo"]["more"] = {"iso"}; ST["files"][("enzo", "more")] = {}
    assert c.post(url(cid), json={"target_storage": "more"}).status_code == 200
    assert CALLS[-1][2] == {"target": f"more:iso/{ISO}"}


def test_copy_with_a_new_name_and_every_allowed_kind(api):
    c, cid = api
    assert c.post(url(cid, name=ISO), json={"target_storage": "local", "target_node": "enzo2", "target_name": "copie.iso"}).status_code == 200
    assert CALLS[-1][2]["target"] == "local:iso/copie.iso"
    for kind, name in (("vztmpl", "alpine.tar.zst"), ("snippets", "note.yaml"), ("import", "img.qcow2"), ("backup", BACKUP)):
        r = c.post(url(cid, kind, name), json={"target_storage": "local", "target_node": "enzo2"})
        assert r.status_code == 200, (kind, r.text)
        assert CALLS[-1][2]["target"] == f"local:{kind}/{name}"


def test_dry_run_changes_nothing(api):
    c, cid = api
    r = c.post(url(cid), json={"target_storage": "local", "target_node": "enzo2", "dry_run": True})
    assert r.status_code == 200 and r.json() == {"dry_run": True, "source": f"local:iso/{ISO}", "target": f"local:iso/{ISO}", "target_node": "enzo2", "node": "enzo"} and not CALLS


# ---------------------------------------------------------------- refus : aucun appel d'écriture
def test_existing_destination_is_409_and_nothing_is_overwritten(api):
    c, cid = api
    ST["files"][("enzo2", "local")][f"local:iso/{ISO}"] = "iso"
    r = c.post(url(cid), json={"target_storage": "local", "target_node": "enzo2"})
    assert r.status_code == 409 and "existe déjà" in r.json()["detail"] and not CALLS


@pytest.mark.parametrize("kind", ["images", "rootdir", "vztmplx", "ISO", "backups"])
def test_disk_and_unknown_kinds_are_refused(api, kind):
    c, cid = api
    ST["files"][("enzo", "local")]["local:images/disk-1"] = "images"; ST["files"][("enzo", "local")]["local:rootdir/disk-1"] = "rootdir"          # ils EXISTENT : seul le type les refuse
    r = c.post(url(cid, kind, "disk-1"), json={"target_storage": "local", "target_node": "enzo2"})
    assert r.status_code == 422 and not CALLS and not SEEN


@pytest.mark.parametrize("name", ["../x.iso", "a b.iso", "a;b.iso", "-x.iso", "x" * 211, "é.iso", "a\\b.iso"])
def test_invalid_names_are_refused_without_any_call(api, name):
    c, cid = api
    assert c.post(url(cid, name=quote(name, safe="")), json={"target_storage": "local", "target_node": "enzo2"}).status_code in (404, 422) and not CALLS and not SEEN
    assert c.post(url(cid), json={"target_storage": "local", "target_node": "enzo2", "target_name": name}).status_code == 422 and not CALLS and not SEEN


def test_backup_names_must_follow_the_vzdump_format(api):
    c, cid = api
    ST["files"][("enzo", "local")]["local:backup/photo.iso"] = "backup"
    assert c.post(url(cid, "backup", "photo.iso"), json={"target_storage": "local", "target_node": "enzo2"}).status_code == 422
    assert c.post(url(cid, "backup", BACKUP), json={"target_storage": "local", "target_node": "enzo2", "target_name": "photo.iso"}).status_code == 422
    assert not CALLS


@pytest.mark.parametrize("b", [
    {"target_storage": ""}, {"target_storage": "../x"}, {"target_storage": "a b"}, {"target_storage": "-x"}, {"target_storage": "x" * 65}, {"target_storage": "local;ls"},
    {"target_storage": "local", "target_node": "a b"}, {"target_storage": "local", "target_node": "x" * 64}, {"target_storage": "local", "target_node": "../e"},
    {"target_storage": "local", "dry_run": "yes"}, {"target_storage": 5}, {},
])
def test_invalid_destination_is_refused_without_any_call(api, b):
    c, cid = api
    assert c.post(url(cid), json=b).status_code == 422 and not CALLS and not SEEN                                  # aucune lecture non plus


def test_destination_must_exist_accept_the_type_and_be_active(api):
    c, cid = api
    base = {"target_node": "enzo2"}
    assert c.post(url(cid), json={"target_storage": "local-lvm", **base}).status_code == 422                       # ne contient pas d'ISO
    assert c.post(url(cid), json={"target_storage": "absent", **base}).status_code == 422
    ST["storages"]["enzo3"] = {"local": {"iso"}}; ST["files"][("enzo3", "local")] = {}
    r = c.post(url(cid), json={"target_storage": "local", "target_node": "enzo3"})                              # absent de /nodes, même si des stockages répondent
    assert r.status_code == 422 and "inconnu du cluster" in r.json()["detail"]
    assert c.post(url(cid), json={"target_storage": "off"}).status_code == 422                                      # stockage inactif sur enzo
    assert not CALLS


def test_copy_onto_itself_is_refused(api):
    c, cid = api
    assert c.post(url(cid), json={"target_storage": "local"}).status_code == 422
    assert c.post(url(cid), json={"target_storage": "local", "target_node": "enzo", "target_name": ISO}).status_code == 422
    assert not CALLS


def test_unknown_source_is_404(api):
    c, cid = api
    assert c.post(url(cid, name="absent.iso"), json={"target_storage": "local", "target_node": "enzo2"}).status_code == 404 and not CALLS


def test_wrong_kind_for_an_existing_name_is_refused(api):
    c, cid = api
    assert c.post(url(cid, "vztmpl", ISO), json={"target_storage": "local", "target_node": "enzo2"}).status_code == 404 and not CALLS     # c'est une ISO, pas un modèle


def test_unreadable_destination_listing_refuses_without_write(api):
    c, cid = api
    del ST["files"][("enzo2", "local")]
    r = c.post(url(cid), json={"target_storage": "local", "target_node": "enzo2"})
    assert r.status_code == 502 and not CALLS
    fresh(); ST["null_listing"] = ("enzo2", "local")                                                        # 200 mais pas une liste : refus, jamais « rien n'existe »
    r = c.post(url(cid), json={"target_storage": "local", "target_node": "enzo2"})
    assert r.status_code == 502 and "illisible" in r.json()["detail"] and not CALLS


# ---------------------------------------------------------------- audit, secrets, droits
def test_every_copy_and_refusal_is_audited_without_secret(api):
    c, cid = api
    c.post(url(cid), json={"target_storage": "local", "target_node": "enzo2"})                       # succès
    c.post(url(cid), json={"target_storage": "local", "target_node": "enzo2"})                       # 409
    pairs = audit_pairs(c)
    assert pairs.count(("volume-copy", "started")) == 1 and pairs.count(("volume-copy", "error")) == 1
    assert SECRET not in c.get("/api/audit").text


def test_proxmox_error_never_leaks_its_message(api):
    c, cid = api
    ST["fail"] = True
    r = c.post(url(cid), json={"target_storage": "local", "target_node": "enzo2"})
    assert r.status_code == 502 and SECRET not in r.text and SECRET not in c.get("/api/audit").text


def test_requires_authentication(client):
    assert client.post(url(1), json={"target_storage": "local"}).status_code == 401
