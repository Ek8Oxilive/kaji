from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
CIFS_PWD = "mdp-cifs-très-secret"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "921a2c39e40935cc1d681235282a3f4359c66196"
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}

# Paramètres que le vrai Proxmox accepte (relevés dans apidoc.js du cluster réel, POST/PUT /storage) :
POST_OK = {"authsupported", "base", "blocksize", "bwlimit", "comstar_hg", "comstar_tg", "content", "content-dirs", "create-base-path",
           "create-subdirs", "data-pool", "datastore", "disable", "domain", "encryption-key", "export", "fingerprint", "format", "fs-name",
           "fuse", "is_mountpoint", "iscsiprovider", "keyring", "krbd", "lio_tpg", "master-pubkey", "max-protected-backups", "mkdir",
           "monhost", "mountpoint", "namespace", "nocow", "nodes", "nowritecache", "options", "password", "path", "pool", "port",
           "portal", "preallocation", "prune-backups", "saferemove", "saferemove-stepsize", "saferemove_throughput", "server", "share",
           "shared", "skip-cert-verification", "smbversion", "snapshot-as-volume-chain", "sparse", "storage", "subdir", "tagged_only",
           "target", "thinpool", "type", "username", "vgname", "zfs-base-path"}
# En modification : ni type, ni chemin, ni serveur NFS, ni export, ni portail, ni cible, ni vgname, ni thinpool, ni partage CIFS…
PUT_OK = (POST_OK - {"type", "base", "export", "iscsiprovider", "path", "portal", "target", "thinpool", "vgname", "share", "datastore",
                     "authsupported", "mkdir"}) | {"delete", "digest"}
BOOL01 = {"disable", "shared", "saferemove", "sparse", "fuse", "krbd", "create-base-path"}

EXISTING = [
    {"storage": "local", "type": "dir", "path": "/var/lib/vz", "content": "backup,import,vztmpl,iso", "digest": DIGEST},
    {"storage": "local-lvm", "type": "lvmthin", "vgname": "pve", "thinpool": "data", "content": "images,rootdir", "digest": DIGEST},
    {"storage": "nas", "type": "cifs", "server": "10.0.0.9", "share": "bk", "username": "kaji", "content": "backup", "digest": DIGEST},
    {"storage": "pbs1", "type": "pbs", "server": "10.0.0.7", "datastore": "d", "content": "backup", "digest": DIGEST},
]


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    CALLS.append((request.method, p, body))
    if ST.get("down"):
        return httpx.Response(500, json={"data": None, "message": SECRET})
    if request.method == "GET" and p == "/storage":
        return httpx.Response(200, json={"data": ST.get("list", EXISTING)})
    if (request.method, p) == ("POST", "/storage"):
        bad = set(body) - POST_OK
        if bad or "storage" not in body or "type" not in body:
            return httpx.Response(400, json={"data": None, "message": f"paramètre refusé {sorted(bad)}"})
    elif request.method == "PUT" and p.startswith("/storage/"):
        bad = set(body) - PUT_OK
        if bad:
            return httpx.Response(400, json={"data": None, "message": f"paramètre refusé {sorted(bad)}"})
    elif request.method == "DELETE" and p.startswith("/storage/"):
        if body:
            return httpx.Response(400, json={"data": None, "message": "pas de paramètre"})
    else:
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    for k in BOOL01 & set(body):
        if body[k] not in ("0", "1"):
            return httpx.Response(400, json={"data": None, "message": f"{k} doit valoir 0 ou 1"})
    if ST.get("write_fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, name=""):
    return f"/api/connections/{cid}/storage-config" + (f"/{name}" if name else "")


def writes():
    return [x for x in CALLS if x[0] != "GET"]


def audit_text(c):
    return str(c.get("/api/audit").json()) if c.get("/api/audit").status_code == 200 else ""


# ---------------------------------------------------------------- lecture
def test_list_and_get_are_whitelisted(api):
    c, cid = api
    r = c.get(url(cid))
    assert r.status_code == 200
    by = {x["storage"]: x for x in r.json()}
    assert by["local"]["content"] == ["backup", "import", "vztmpl", "iso"] and by["local"]["path"] == "/var/lib/vz"
    assert by["local"]["digest"] == DIGEST and by["local"]["managed"] is True
    assert by["pbs1"] == {"storage": "pbs1", "type": "pbs", "managed": False}          # type non géré : rien d'autre n'est exposé
    assert c.get(url(cid, "nas")).json()["secrets_set"] == []
    assert c.get(url(cid, "absent")).status_code == 404


def test_get_never_returns_secret_even_if_proxmox_did(api):
    c, cid = api
    ST["list"] = [{"storage": "nas", "type": "cifs", "server": "s", "share": "x", "password": CIFS_PWD, "digest": DIGEST}]
    r = c.get(url(cid, "nas"))
    assert CIFS_PWD not in r.text and r.json()["secrets_set"] == ["password"]


# ---------------------------------------------------------------- ajout
def test_add_dir(api):
    c, cid = api
    r = c.post(url(cid), json={"storage": "iso2", "type": "dir", "path": "/mnt/iso", "content": ["vztmpl", "iso"], "create_base_path": True})
    assert r.status_code == 201 and r.json() == {"storage": "iso2", "type": "dir"}
    assert writes() == [("POST", "/storage", {"storage": "iso2", "type": "dir", "path": "/mnt/iso", "content": "iso,vztmpl", "create-base-path": "1"})]


def test_add_nfs_cifs_lvm_zfs_iscsi_ceph(api):
    c, cid = api
    cases = [
        ({"type": "nfs", "server": "10.0.0.2", "export": "/srv/nfs", "options": "vers=4.2", "content": ["backup"]},
         {"type": "nfs", "server": "10.0.0.2", "export": "/srv/nfs", "options": "vers=4.2", "content": "backup"}),
        ({"type": "cifs", "server": "nas.lan", "share": "sauv", "username": "kaji", "password": CIFS_PWD, "smbversion": "3", "domain": "WORK"},
         {"type": "cifs", "server": "nas.lan", "share": "sauv", "username": "kaji", "password": CIFS_PWD, "smbversion": "3", "domain": "WORK"}),
        ({"type": "lvm", "vgname": "vgdata", "shared": False, "content": ["images"]}, {"type": "lvm", "vgname": "vgdata", "shared": "0", "content": "images"}),
        ({"type": "zfspool", "pool": "tank/vm", "blocksize": "16k", "sparse": True}, {"type": "zfspool", "pool": "tank/vm", "blocksize": "16k", "sparse": "1"}),
        ({"type": "iscsi", "portal": "10.0.0.4:3260", "target": "iqn.2001-04.com.ex:disk1"}, {"type": "iscsi", "portal": "10.0.0.4:3260", "target": "iqn.2001-04.com.ex:disk1"}),
        ({"type": "cephfs", "monhost": ["10.0.0.1", "10.0.0.2"], "fs_name": "cephfs", "fuse": True},
         {"type": "cephfs", "monhost": "10.0.0.1,10.0.0.2", "fs-name": "cephfs", "fuse": "1"}),
        ({"type": "rbd", "pool": "rbdpool", "monhost": ["10.0.0.1"], "krbd": True, "namespace": "ns1"},
         {"type": "rbd", "pool": "rbdpool", "monhost": "10.0.0.1", "krbd": "1", "namespace": "ns1"}),
    ]
    for i, (b, expected) in enumerate(cases):
        name = f"st{i}"
        assert c.post(url(cid), json={"storage": name, **b}).status_code == 201, b
        assert writes()[-1] == ("POST", "/storage", {"storage": name, **expected})


def test_add_with_nodes_and_prune(api):
    c, cid = api
    r = c.post(url(cid), json={"storage": "bk", "type": "dir", "path": "/mnt/bk", "nodes": ["enzo2", "enzo"],
                               "prune_backups": {"keep_last": 3, "keep_daily": 7}, "max_protected_backups": 5})
    assert r.status_code == 201
    assert writes()[-1][2] == {"storage": "bk", "type": "dir", "path": "/mnt/bk", "nodes": "enzo,enzo2",
                               "prune-backups": "keep-last=3,keep-daily=7", "max-protected-backups": "5"}


def test_add_refuses_existing_name(api):
    c, cid = api
    assert c.post(url(cid), json={"storage": "local", "type": "dir", "path": "/x"}).status_code == 409 and not writes()


@pytest.mark.parametrize("body", [
    {"type": "dir"},                                                    # chemin manquant
    {"type": "nfs", "server": "s"},                                     # export manquant
    {"type": "cifs", "server": "s"},                                    # partage manquant
    {"type": "lvmthin", "vgname": "pve"},                               # pool thin manquant
    {"type": "rbd", "pool": "p"},                                       # moniteurs manquants
    {"type": "pbs", "server": "s", "datastore": "d"},                   # type pas encore géré
    {"type": "dir", "path": "/x", "server": "s"},                       # champ d'un autre type
    {"type": "dir", "path": "/x", "password": "mdp"},
    {"type": "lvm", "vgname": "v", "content": ["iso"]},                 # contenu impossible sur LVM
    {"type": "lvm", "vgname": "v", "content": []},
    {"type": "cephfs", "monhost": ["h"], "content": ["images"]},
    {"type": "dir", "path": "/x", "content": ["inconnu"]},
    {"type": "dir", "path": "/x", "nodes": []},
    {"type": "dir", "path": "/x", "nodes": ["bad node"]},
    {"type": "dir", "path": "/x", "prune_backups": {"keep_all": True, "keep_last": 3}},
    {"type": "dir", "path": "/x", "prune_backups": {}},
    {"type": "dir", "path": "/x", "prune_backups": {"keep_last": 0}},
    {"type": "dir", "path": "/x", "max_protected_backups": -2},
    {"type": "dir", "path": None},
])
def test_add_refused_without_write(api, body):
    c, cid = api
    r = c.post(url(cid), json={"storage": "nouveau", **body})
    assert r.status_code == 422 and not writes()


@pytest.mark.parametrize("field,value", [
    ("path", "relatif"), ("path", "/a/../etc"), ("path", "/a//b"), ("path", "/a b"), ("path", "/a;rm"), ("path", "/a\n"), ("path", "/" + "a" * 250),
])
def test_dir_path_validated(api, field, value):
    c, cid = api
    assert c.post(url(cid), json={"storage": "n", "type": "dir", field: value}).status_code == 422 and not CALLS


@pytest.mark.parametrize("b", [
    {"type": "nfs", "server": "a b", "export": "/x"}, {"type": "nfs", "server": "a;b", "export": "/x"}, {"type": "nfs", "server": "s", "export": "x"},
    {"type": "nfs", "server": "s", "export": "/x", "options": "a b"}, {"type": "nfs", "server": "s", "export": "/x", "options": "vers=4;rm"},
    {"type": "cifs", "server": "s", "share": "a/b"}, {"type": "cifs", "server": "s", "share": "a b"},
    {"type": "cifs", "server": "s", "share": "x", "username": "a b"}, {"type": "cifs", "server": "s", "share": "x", "smbversion": "9"},
    {"type": "cifs", "server": "s", "share": "x", "password": "a\nb"}, {"type": "cifs", "server": "s", "share": "x", "password": ""},
    {"type": "lvm", "vgname": "a b"}, {"type": "lvm", "vgname": "-x"}, {"type": "zfspool", "pool": "a b"}, {"type": "zfspool", "pool": "a", "blocksize": "3k"},
    {"type": "iscsi", "portal": "p", "target": "iqn x"}, {"type": "rbd", "pool": "p", "monhost": ["a b"]},
    {"type": "rbd", "pool": "p", "monhost": ["h"], "keyring": "[client]\nkey = AQ$(rm)"},
    {"type": "cephfs", "monhost": ["h"] * 9},
])
def test_other_fields_validated(api, b):
    c, cid = api
    assert c.post(url(cid), json={"storage": "n", **b}).status_code == 422 and not CALLS


@pytest.mark.parametrize("name", ["", "a b", "-x", "a/b", "x" * 41, "é", "a;b"])
def test_storage_name_validated(api, name):
    c, cid = api
    assert c.post(url(cid), json={"storage": name, "type": "dir", "path": "/x"}).status_code == 422 and not CALLS


def test_unknown_field_is_ignored_not_forwarded(api):
    c, cid = api
    r = c.post(url(cid), json={"storage": "n", "type": "dir", "path": "/x", "encryption-key": "autogen", "mkdir": 1, "evil": "x"})
    assert r.status_code == 201 and writes()[-1][2] == {"storage": "n", "type": "dir", "path": "/x"}


# ---------------------------------------------------------------- modification
def test_edit_content_and_disable(api):
    c, cid = api
    r = c.put(url(cid, "local"), json={"content": ["iso", "backup"], "disable": True})
    assert r.status_code == 200 and r.json() == {"storage": "local", "type": "dir"}
    assert writes() == [("PUT", "/storage/local", {"content": "iso,backup", "disable": "1"})]


def test_edit_cifs_password_and_reset(api):
    c, cid = api
    assert c.put(url(cid, "nas"), json={"password": CIFS_PWD, "reset": ["domain", "prune_backups"], "digest": DIGEST}).status_code == 200
    assert writes() == [("PUT", "/storage/nas", {"password": CIFS_PWD, "delete": "domain,prune-backups", "digest": DIGEST})]


@pytest.mark.parametrize("b", [
    {"path": "/autre"},                      # chemin : création seulement
    {"type": "nfs"},                         # le type ne change pas
    {"server": "x"},                         # serveur NFS/CIFS : création seulement
    {"share": "autre"},
    {"vgname": "autre"},
    {},                                       # rien à modifier
    {"reset": []},
    {"reset": ["content"]},                   # pas retirable
    {"reset": ["path"]},
    {"reset": ["namespace"]},                 # ne concerne pas un CIFS
    {"digest": "pas-un-digest", "disable": True},
    {"disable": None},
    {"content": []},                          # liste vide
])
def test_edit_refused_without_write(api, b):
    c, cid = api
    assert c.put(url(cid, "nas"), json=b).status_code == 422 and not writes()


def test_edit_cannot_set_and_reset_same_field(api):
    c, cid = api
    assert c.put(url(cid, "nas"), json={"domain": "X", "reset": ["domain"]}).status_code == 422 and not writes()


def test_edit_unknown_and_unmanaged(api):
    c, cid = api
    assert c.put(url(cid, "absent"), json={"disable": True}).status_code == 404
    assert c.put(url(cid, "pbs1"), json={"disable": True}).status_code == 422 and not writes()      # pbs : pas encore géré


# ---------------------------------------------------------------- suppression
def test_delete_requires_confirm_and_exact_name(api):
    c, cid = api
    assert c.delete(url(cid, "nas")).status_code == 400
    assert c.delete(url(cid, "nas") + "?confirm=true").status_code == 400
    for typed in ("Nas", "nas ", "local", "n"):
        assert c.delete(url(cid, "nas"), params={"confirm": "true", "name": typed}).status_code == 400
    assert c.delete(url(cid, "nas") + "?name=nas").status_code == 400
    assert not writes()


def test_delete_ok(api):
    c, cid = api
    r = c.delete(url(cid, "nas"), params={"confirm": "true", "name": "nas"})
    assert r.status_code == 200 and r.json() == {"deleted": "nas"}
    assert writes() == [("DELETE", "/storage/nas", {})]


def test_delete_unknown_404(api):
    c, cid = api
    assert c.delete(url(cid, "absent"), params={"confirm": "true", "name": "absent"}).status_code == 404 and not writes()


# ---------------------------------------------------------------- audit et fuites
def test_audit_records_success_and_refusals_without_secret(api):
    c, cid = api
    c.post(url(cid), json={"storage": "nas2", "type": "cifs", "server": "s", "share": "x", "password": CIFS_PWD})
    c.put(url(cid, "nas"), json={"password": CIFS_PWD, "path": "/x"})          # refus
    c.delete(url(cid, "nas"))                                                   # refus
    c.delete(url(cid, "nas"), params={"confirm": "true", "name": "nas"})
    log = c.get("/api/audit")
    assert log.status_code == 200
    items = log.json()
    acts = [(i["action"], i["status"]) for i in items]
    for a in (("storage-add", "started"), ("storage-edit", "error"), ("storage-delete", "error"), ("storage-delete", "started")):
        assert a in acts
    assert CIFS_PWD not in log.text and "défini" in log.text


def test_proxmox_errors_are_audited_and_do_not_leak(api):
    c, cid = api
    ST["write_fail"] = True
    r = c.post(url(cid), json={"storage": "n", "type": "dir", "path": "/x"})
    assert r.status_code == 502 and SECRET not in r.text
    ST.clear()
    ST["down"] = True
    assert c.get(url(cid)).status_code == 502
    assert SECRET not in c.get(url(cid)).text
    assert SECRET not in c.get("/api/audit").text


def test_validation_error_never_echoes_secret(api):
    c, cid = api
    r = c.post(url(cid), json={"storage": "n", "type": "cifs", "server": "s", "share": "a b", "password": CIFS_PWD})
    assert r.status_code == 422 and CIFS_PWD not in r.text


def test_requires_login(client):
    assert client.get("/api/connections/1/storage-config").status_code == 401
    assert client.post("/api/connections/1/storage-config", json={}).status_code == 401
    assert client.delete("/api/connections/1/storage-config/x").status_code == 401
