import sys

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": "s3cr3t-value-xyz"}

RESOURCES = [
    {"type": "storage", "storage": "local", "node": "pve2", "plugintype": "dir", "status": "available",
     "shared": 0, "disk": 4, "maxdisk": 10, "content": "iso,backup,vztmpl,bogus"},
    {"type": "storage", "storage": "ceph", "node": "pve2", "plugintype": "rbd", "status": "available",
     "shared": 1, "disk": 30, "maxdisk": 100, "content": "images,rootdir"},
    {"type": "storage", "storage": "ceph", "node": "pve1", "plugintype": "rbd", "status": "available",
     "shared": 1, "disk": 30, "maxdisk": 100, "content": "images,rootdir"},
    {"type": "storage", "storage": "local", "node": "pve1", "plugintype": "dir", "status": "available",
     "shared": 0, "disk": 1, "maxdisk": 10, "content": "iso"},
    # stockage inactif : renvoyé, mais marqué inactif, sans chiffres
    {"type": "storage", "storage": "nfs-old", "node": "pve1", "plugintype": "nfs", "status": "unknown",
     "shared": 1, "content": "backup"},
    # lignes illisibles : ignorées, elles n'empêchent pas de lister les autres
    {"type": "storage", "node": "pve1"},
    {"type": "storage", "storage": "", "node": "pve1"},
    "n'importe quoi",
    {"type": "storage", "storage": "weird", "node": "pve1", "disk": "abc", "maxdisk": [1], "content": 7},
]
VOLUMES = [
    {"volid": "local:iso/debian.iso", "content": "iso", "format": "iso", "size": 650000000, "ctime": 1700000000},
    {"volid": "local:backup/vzdump-qemu-100-2026_11_01.vma.zst", "content": "backup", "format": "vma.zst",
     "size": 5, "ctime": 1700000500, "vmid": 100, "notes": "avant mise à jour", "protected": 1},
    {"volid": "local:vztmpl/debian-13.tar.zst", "content": "vztmpl", "format": "tgz", "size": 1, "ctime": "xx"},
    {"content": "iso"},          # sans volid : ignoré
    "illisible",
]
SEEN: list[httpx.Request] = []
FAIL = {}


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    if FAIL.get("code"):
        return httpx.Response(FAIL["code"], json={"data": None})
    if request.url.path == "/api2/json/cluster/resources":
        return httpx.Response(200, json={"data": RESOURCES})
    if request.url.path.endswith("/content"):
        return httpx.Response(200, json={"data": VOLUMES})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    FAIL.clear()
    SEEN.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler))
    )
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def _list(api):
    c, cid = api
    r = c.get(f"/api/connections/{cid}/storages")
    assert r.status_code == 200
    return r.json()


def _content_url(cid, node="pve1", storage="local", query=""):
    return f"/api/connections/{cid}/nodes/{node}/storage/{storage}/content{query}"


# ---------- liste des stockages -------------------------------------------------------------------------------------

def test_storages_requires_auth(client):
    assert client.get("/api/connections/1/storages").status_code == 401


def test_storages_sorted_by_name_then_node(api):
    assert [(s["storage"], s["node"]) for s in _list(api)] == [
        ("ceph", "pve1"), ("ceph", "pve2"), ("local", "pve1"), ("local", "pve2"),
        ("nfs-old", "pve1"), ("weird", "pve1")]


def test_storages_keep_historical_fields(api):
    """L'interface s'en sert : ces champs doivent rester, avec leur forme d'origine."""
    s = next(s for s in _list(api) if (s["storage"], s["node"]) == ("local", "pve2"))
    assert s["type"] == "dir" and s["status"] == "available" and s["shared"] is False
    assert s["disk"] == 4 and s["maxdisk"] == 10 and s["content"] == "iso,backup,vztmpl,bogus"


def test_storages_new_fields(api):
    s = next(s for s in _list(api) if (s["storage"], s["node"]) == ("local", "pve2"))
    assert s["used"] == 4 and s["total"] == 10 and s["free"] == 6 and s["active"] is True
    assert s["contents"] == ["iso", "vztmpl", "backup"]            # « bogus » ignoré, ordre stable


def test_shared_storage_lists_every_node_that_carries_it(api):
    ceph = [s for s in _list(api) if s["storage"] == "ceph"]
    assert all(s["nodes"] == ["pve1", "pve2"] and s["shared"] for s in ceph)
    local = next(s for s in _list(api) if (s["storage"], s["node"]) == ("local", "pve1"))
    assert local["nodes"] == ["pve1", "pve2"]                      # « local » existe sur chaque nœud


def test_inactive_storage_is_listed_and_marked_inactive(api):
    s = next(s for s in _list(api) if s["storage"] == "nfs-old")
    assert s["active"] is False and s["used"] is None and s["total"] is None and s["free"] is None


def test_unreadable_rows_do_not_prevent_listing_the_others(api):
    names = {s["storage"] for s in _list(api)}
    assert {"local", "ceph", "nfs-old"} <= names and "" not in names and None not in names
    weird = next(s for s in _list(api) if s["storage"] == "weird")
    assert weird["used"] is None and weird["total"] is None and weird["free"] is None and weird["contents"] == []


def test_storages_proxmox_error_is_502_without_secret(api):
    c, cid = api
    FAIL["code"] = 500
    r = c.get(f"/api/connections/{cid}/storages")
    assert r.status_code == 502 and "s3cr3t-value-xyz" not in r.text


# ---------- contenu d'un stockage -----------------------------------------------------------------------------------

def test_content_requires_auth(client):
    assert client.get(_content_url(1)).status_code == 401


def test_content_unknown_connection(api):
    assert api[0].get(_content_url(999)).status_code == 404


def test_content_volumes_shaped_and_sorted(api):
    c, cid = api
    vols = c.get(_content_url(cid)).json()
    assert [v["name"] for v in vols] == ["vzdump-qemu-100-2026_11_01.vma.zst", "debian.iso", "debian-13.tar.zst"]
    backup = vols[0]
    assert backup["volid"] == "local:backup/vzdump-qemu-100-2026_11_01.vma.zst"
    assert backup["content"] == "backup" and backup["format"] == "vma.zst" and backup["size"] == 5
    assert backup["vmid"] == 100 and backup["notes"] == "avant mise à jour" and backup["protected"] is True
    assert backup["date"] == "2023-11-14T22:21:40+00:00"


def test_content_unreadable_entries_ignored_and_bad_numbers_become_null(api):
    c, cid = api
    vols = c.get(_content_url(cid)).json()
    assert len(vols) == 3                                            # l'entrée sans volid et la chaîne sont écartées
    tmpl = next(v for v in vols if v["content"] == "vztmpl")
    assert tmpl["ctime"] is None and tmpl["date"] is None and tmpl["vmid"] is None and tmpl["protected"] is False


def test_content_filter_is_forwarded_to_proxmox(api):
    c, cid = api
    assert c.get(_content_url(cid, query="?content=backup")).status_code == 200
    req = SEEN[-1]
    assert req.url.path == "/api2/json/nodes/pve1/storage/local/content"
    assert dict(req.url.params) == {"content": "backup"}


def test_content_without_filter_sends_no_content_param(api):
    c, cid = api
    c.get(_content_url(cid))
    assert dict(SEEN[-1].url.params) == {}


@pytest.mark.parametrize("bad", ["rm", "backup,iso", "BACKUP", "backup;x", "../etc", "backup%0a", ""])
def test_invalid_content_refused_and_never_reaches_proxmox(api, bad):
    c, cid = api
    SEEN.clear()
    r = c.get(_content_url(cid), params={"content": bad})
    assert r.status_code == 422 and SEEN == []
    if bad:
        assert bad not in r.text                                     # la valeur saisie n'est jamais renvoyée


@pytest.mark.parametrize("bad", ["-pve", "pve_1", "pve.1", "p" * 64, "pve%20x", "pve%0a", "pve%00"])
def test_invalid_node_refused_and_never_reaches_proxmox(api, bad):
    c, cid = api
    SEEN.clear()
    r = c.get(_content_url(cid, node=bad))
    assert r.status_code in (404, 422) and SEEN == []


@pytest.mark.parametrize("bad", ["-x", "a b", "a.b", "s" * 41, "ok%0a", "ok%00"])
def test_invalid_storage_refused_and_never_reaches_proxmox(api, bad):
    c, cid = api
    SEEN.clear()
    r = c.get(_content_url(cid, storage=bad))
    assert r.status_code in (404, 422) and SEEN == []


def test_content_proxmox_error_is_502_without_secret(api):
    c, cid = api
    FAIL["code"] = 500
    r = c.get(_content_url(cid))
    assert r.status_code == 502 and "s3cr3t-value-xyz" not in r.text


def test_storage_routes_are_read_only(api):
    c, cid = api
    for method in ("post", "put", "delete", "patch"):
        assert getattr(c, method)(_content_url(cid)).status_code == 405


# ---------- données inattendues : une entrée illisible ne doit jamais faire tomber toute la liste ----------------------

ODD_RESOURCES = [
    {"type": "storage", "storage": "odd", "node": 5, "plugintype": "dir", "status": "available"},
    {"type": "storage", "storage": "odd", "node": "pve1", "plugintype": "dir", "status": "available"},
    {"type": "storage", "storage": "fine", "node": "pve1", "plugintype": "dir", "status": "available",
     "disk": "--5", "maxdisk": "²", "content": "iso"},
    {"type": "storage", "storage": "huge", "node": "pve1", "disk": "1e999", "maxdisk": 10 ** 400},
]
ODD_VOLUMES = [
    {"volid": "local:iso/a.iso", "content": 7, "format": 3, "notes": 4, "ctime": 10 ** 15, "size": "--5", "vmid": "²"},
    {"volid": "local:iso/b.iso", "content": "iso", "ctime": -1},
    {"volid": "local:iso/c.iso", "content": "iso", "ctime": 10 ** 400},
    {"volid": "local:iso/d.iso", "content": None},
]


def test_storages_with_unexpected_types_still_listed(api, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "RESOURCES", ODD_RESOURCES)
    rows = _list(api)
    assert [(s["storage"], s["node"]) for s in rows] == [
        ("fine", "pve1"), ("huge", "pve1"), ("odd", None), ("odd", "pve1")]
    fine = next(s for s in rows if s["storage"] == "fine")
    assert fine["used"] is None and fine["total"] is None and fine["free"] is None and fine["contents"] == ["iso"]
    huge = next(s for s in rows if s["storage"] == "huge")
    assert huge["used"] is None and huge["free"] is None


def test_volumes_with_unexpected_types_still_listed(api, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "VOLUMES", ODD_VOLUMES)
    c, cid = api
    r = c.get(_content_url(cid))
    assert r.status_code == 200
    vols = {v["name"]: v for v in r.json()}
    assert set(vols) == {"a.iso", "b.iso", "c.iso", "d.iso"}
    a = vols["a.iso"]
    assert a["content"] is None and a["format"] is None and a["notes"] is None
    assert a["size"] is None and a["vmid"] is None and a["date"] is None     # horodatage hors limites
    assert vols["b.iso"]["date"] is None and vols["c.iso"]["date"] is None


@pytest.mark.parametrize("raw", ["--5", "²", "1e999", "abc", "", " ", float("inf"), float("nan"), "9" * 5000, True, None, [1]])
def test_int_never_raises_and_gives_null_for_unreadable_values(raw):
    from app.storagespec import _int
    assert _int(raw) is None


@pytest.mark.parametrize("raw,expected", [("42", 42), (" 7 ", 7), ("-3", -3), (5, 5), (2.9, 2)])
def test_int_reads_valid_values(raw, expected):
    from app.storagespec import _int
    assert _int(raw) == expected


# ---------------------------------------------------------------- PBS : vérification et chiffrement des sauvegardes
def test_volumes_report_pbs_verification_and_encryption():
    from app.storagespec import shape_volumes
    fp = "ab:" * 31 + "ab"
    rows = shape_volumes([
        {"volid": "pbs:backup/vm/100/2026-11-08T10:00:00Z", "content": "backup", "verification": {"state": "ok", "upid": "UPID:x"}, "encrypted": fp},
        {"volid": "pbs:backup/vm/101/2026-11-08T10:00:00Z", "content": "backup", "verification": {"state": "failed"}, "encrypted": "1"},
        {"volid": "pbs:backup/vm/102/2026-11-08T10:00:00Z", "content": "backup", "verification": {"state": "none"}},
        {"volid": "pbs:backup/vm/103/2026-11-08T10:00:00Z", "content": "backup", "verification": {"state": "<script>"}, "encrypted": "0"},
        {"volid": "pbs:backup/vm/104/2026-11-08T10:00:00Z", "content": "backup", "verification": "ok", "encrypted": ""},
        {"volid": "local:iso/a.iso", "content": "iso"},
    ])
    by = {r["vmid"] if r["vmid"] is not None else r["name"]: r for r in rows}
    got = {r["volid"].split("/")[2] if "backup/" in r["volid"] else "iso": (r["verification"], r["encrypted"]) for r in rows}
    assert got == {"100": ("ok", True), "101": ("failed", True), "102": ("none", False), "103": (None, False), "104": (None, False), "iso": (None, False)}
    assert fp not in str(rows) and by                      # l'empreinte de la clé n'est pas reprise
