import httpx
import pytest

from app import diskdelete as DD
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:lvmremove:vgempty:kaji@pve!kaji:"
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}


def disk(dev, used=None):
    return {"devpath": dev, "type": "ssd", "size": 100, "used": used, "gpt": 1, "osdid": -1}


def part(dev, used=None):
    return {"devpath": dev, "type": "partition", "size": 1, "used": used}


DISKS = [
    disk("/dev/nvme0n1", "partitions"), part("/dev/nvme0n1p1", "BIOS boot"), part("/dev/nvme0n1p2", "EFI"), part("/dev/nvme0n1p3", "LVM"), part("/dev/nvme0n1p4", "LVM"),
    disk("/dev/sdb", "partitions"), part("/dev/sdb1", "LVM"), disk("/dev/sdc", "partitions"), part("/dev/sdc1", "LVM"), disk("/dev/sdd", "partitions"), part("/dev/sdd1", "LVM"),
    disk("/dev/sdh", "partitions"), part("/dev/sdh1", "LVM"), disk("/dev/sdi", "partitions"), part("/dev/sdi1", "LVM"),
    disk("/dev/sde", "partitions"), part("/dev/sde1", "ext4"), disk("/dev/sdf", "partitions"), part("/dev/sdf1", "ext4"), disk("/dev/sdg", "partitions"), part("/dev/sdg1", "mounted"),
]
LVM = {"children": [
    {"name": "pve", "size": 9, "free": 1, "lvcount": 16, "children": [{"name": "/dev/nvme0n1p3"}]},
    {"name": "vgonsys", "size": 9, "free": 9, "lvcount": 0, "children": [{"name": "/dev/nvme0n1p4"}]},
    {"name": "vgempty", "size": 9, "free": 9, "lvcount": 0, "children": [{"name": "/dev/sdb1"}]},
    {"name": "vgfull", "size": 9, "free": 5, "lvcount": 2, "children": [{"name": "/dev/sdc1"}]},
    {"name": "vgthin", "size": 9, "free": 9, "lvcount": 0, "children": [{"name": "/dev/sdd1"}]},
    {"name": "vgstore", "size": 9, "free": 9, "lvcount": 0, "children": [{"name": "/dev/sdb1"}]},
    {"name": "root", "size": 9, "free": 9, "lvcount": 0, "children": [{"name": "/dev/sdh1"}]},            # vide, hors système, mais nom réservé
    {"name": "vgorphan", "size": 9, "free": 5, "lvcount": 3, "children": [{"name": "/dev/sdi1"}]},        # volumes inconnus de la config Proxmox
    {"name": "vgnull", "size": 9, "free": 5, "children": [{"name": "/dev/sdi1"}]},                        # nombre de volumes inconnu
    {"name": "vgthin2", "size": 9, "free": 9, "lvcount": 0, "children": [{"name": "/dev/sdi1"}]},         # contient un pool LVM-thin sans stockage
]}
THIN = [{"lv": "data", "vg": "pve", "lv_size": 9, "used": 5}, {"lv": "pool1", "vg": "vgthin", "lv_size": 9, "used": 0}, {"lv": "poolfull", "vg": "vgthin", "lv_size": 9, "used": 5},
        {"lv": "poolst", "vg": "vgthin", "lv_size": 9, "used": 0}, {"lv": "poolnull", "vg": "vgthin", "lv_size": 9},
        {"lv": "p2", "vg": "vgthin2", "lv_size": 9, "used": 0}]
DIRS = [{"path": "/mnt/pve/dirempty", "device": "/dev/sde1", "type": "ext4"}, {"path": "/mnt/pve/dirfull", "device": "/dev/sdf1", "type": "ext4"},
        {"path": "/mnt/pve/dirsys", "device": "/dev/sdg1", "type": "ext4"}]
ZFS = [{"name": "rpool", "size": 10**10, "alloc": 1000, "free": 1}, {"name": "tankempty", "size": 10**10, "alloc": 1000, "free": 10**10}, {"name": "tankfull", "size": 10**10, "alloc": 10**9, "free": 1}, {"name": "tankvm", "size": 10**10, "alloc": 1000, "free": 1}]
STORAGES = [
    {"storage": "local", "type": "dir", "path": "/var/lib/vz"}, {"storage": "local-lvm", "type": "lvmthin", "vgname": "pve", "thinpool": "data"},
    {"storage": "vgf", "type": "lvm", "vgname": "vgfull"}, {"storage": "vge", "type": "lvm", "vgname": "vgempty"}, {"storage": "vgs", "type": "lvm", "vgname": "vgstore"},
    {"storage": "dirf", "type": "dir", "path": "/mnt/pve/dirfull"}, {"storage": "dire", "type": "dir", "path": "/mnt/pve/dirempty"},
    {"storage": "zvm", "type": "zfspool", "pool": "tankvm"}, {"storage": "zempty", "type": "zfspool", "pool": "tankempty/vm"},
    {"storage": "thinbusy", "type": "lvmthin", "vgname": "vgthin", "thinpool": "poolst"}, {"storage": "thinok", "type": "lvmthin", "vgname": "vgthin", "thinpool": "pool1"},
    {"storage": "othernode", "type": "dir", "path": "/mnt/pve/dirempty", "nodes": "enzo2"},      # même chemin, mais sur un autre nœud
    {"storage": "thinother", "type": "lvmthin", "vgname": "vgother", "thinpool": "pool1"},       # même nom de pool, autre groupe
]
CONTENT = {"vgf": 3, "vge": 0, "vgs": 4, "dirf": 2, "dire": 0, "zvm": 5, "zempty": 0, "thinbusy": 3, "thinok": 0, "othernode": 5, "thinother": 7}
DELETE_SCHEMA = {"lvm": {"cleanup-config", "cleanup-disks"}, "directory": {"cleanup-config", "cleanup-disks"}, "zfs": {"cleanup-config", "cleanup-disks"},
                 "lvmthin": {"cleanup-config", "cleanup-disks", "volume-group"}}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, request.url.query.decode() + request.content.decode()))
    if request.method == "GET":
        if ST.get("read_down") == p or ST.get("read_down") == "*":
            return httpx.Response(500, json={"data": None, "message": SECRET})
        if p == "/storage":
            return httpx.Response(200, json={"data": ST.get("storages", STORAGES)})
        if p.startswith("/nodes/enzo/storage/") and p.endswith("/content"):
            sid = p.split("/")[4]
            if CONTENT.get(sid, 0) is None or sid in ST.get("content_down", ()):
                return httpx.Response(500, json={"data": None})
            return httpx.Response(200, json={"data": [{"volid": f"{sid}:v{i}"} for i in range(CONTENT.get(sid, 0))]})
        data = {"/nodes/enzo/disks/list": DISKS, "/nodes/enzo/disks/lvm": LVM, "/nodes/enzo/disks/lvmthin": THIN, "/nodes/enzo/disks/directory": DIRS, "/nodes/enzo/disks/zfs": ZFS}
        return httpx.Response(200, json={"data": data[p]}) if p in data else httpx.Response(404, json={"data": None})
    parts = p.split("/")
    kind = parts[4] if len(parts) > 4 else ""
    sent = set(httpx.QueryParams(request.url.query.decode()).keys())
    if request.method == "DELETE" and kind in DELETE_SCHEMA and sent != DELETE_SCHEMA[kind]:
        return httpx.Response(400, json={"data": None, "message": "Parameter verification failed.", "errors": {k: "schema" for k in sent ^ DELETE_SCHEMA[kind]}})
    if ST.get("write_fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    return httpx.Response(200, json={"data": UPID})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def rm(c, cid, kind, name, **b):
    return c.post(f"/api/connections/{cid}/nodes/enzo/disks/{kind}/{name}/delete", json={"confirm": True, "type_name": name, **b})


def writes():
    return [x for x in CALLS if x[0] not in ("GET",)]


# ---------------------------------------------------------------- cas permis
def test_delete_empty_lvm_group(api):
    c, cid = api
    r = rm(c, cid, "lvm", "vgempty")
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo"}
    assert writes() == [("DELETE", "/nodes/enzo/disks/lvm/vgempty", "cleanup-config=1&cleanup-disks=0")]


def test_cleanup_flags_are_explicit(api):
    c, cid = api
    assert rm(c, cid, "lvm", "vgempty", cleanup_config=False, cleanup_disks=True).status_code == 202
    assert writes()[0][2] == "cleanup-config=0&cleanup-disks=1"


def test_delete_empty_thin_pool_sends_volume_group(api):
    c, cid = api
    assert rm(c, cid, "lvmthin", "pool1", vg="vgthin").status_code == 202
    assert writes() == [("DELETE", "/nodes/enzo/disks/lvmthin/pool1", "cleanup-config=1&cleanup-disks=0&volume-group=vgthin")]


def test_delete_empty_directory_and_zfs(api):
    c, cid = api
    assert rm(c, cid, "directory", "dirempty").status_code == 202
    assert rm(c, cid, "zfs", "tankempty").status_code == 202                       # son stockage zempty (tankempty/vm) est vide
    assert [w[1] for w in writes()] == ["/nodes/enzo/disks/directory/dirempty", "/nodes/enzo/disks/zfs/tankempty"]


# ---------------------------------------------------------------- refus absolus
@pytest.mark.parametrize("kind,name,extra", [("lvm", "pve", {}), ("lvmthin", "data", {"vg": "pve"}), ("zfs", "rpool", {})])
def test_reserved_names_never(api, kind, name, extra):
    c, cid = api
    assert rm(c, cid, kind, name, **extra).status_code in (404, 422) and not writes()


def test_reserved_name_refused_even_when_empty_and_off_system(api):
    c, cid = api
    r = rm(c, cid, "lvm", "root")
    assert r.status_code == 422 and "réservé" in r.json()["detail"]
    r = rm(c, cid, "zfs", "rpool")
    assert r.status_code == 422 and "réservé" in r.json()["detail"]
    assert not writes()


def test_lvm_group_with_unknown_or_unreadable_volume_count_refused(api):
    c, cid = api
    assert "volumes logiques" in rm(c, cid, "lvm", "vgorphan").json()["detail"]        # 3 volumes, aucun stockage ne les décrit
    assert "volumes logiques" in rm(c, cid, "lvm", "vgnull").json()["detail"]
    assert not writes()


def test_lvm_group_holding_a_thin_pool_refused_without_any_storage(api):
    c, cid = api
    r = rm(c, cid, "lvm", "vgthin2")
    assert r.status_code == 422 and "LVM-thin" in r.json()["detail"] and not writes()


def test_system_disk_volumes_never(api):
    c, cid = api
    r = rm(c, cid, "lvm", "vgonsys")                                                # vide, mais sur le disque système
    assert r.status_code == 422 and "système" in r.json()["detail"]
    r = rm(c, cid, "directory", "dirsys")                                           # partition montée
    assert r.status_code == 422 and "système" in r.json()["detail"]
    assert not writes()


def test_non_empty_volumes_never(api):
    c, cid = api
    assert rm(c, cid, "lvm", "vgfull").status_code == 422                          # volumes logiques
    assert rm(c, cid, "lvm", "vgthin").status_code == 422                          # contient des pools LVM-thin
    assert rm(c, cid, "lvmthin", "poolfull", vg="vgthin").status_code == 422       # données
    assert rm(c, cid, "lvmthin", "poolnull", vg="vgthin").status_code == 422       # usage inconnu : prudence
    assert rm(c, cid, "zfs", "tankfull").status_code == 422                        # données
    assert not writes()


def test_storage_content_blocks_even_if_volume_looks_empty(api):
    c, cid = api
    r = rm(c, cid, "lvm", "vgstore")
    assert r.status_code == 422 and "vgs" in r.json()["detail"] and "4" in r.json()["detail"]
    assert rm(c, cid, "lvmthin", "poolst", vg="vgthin").status_code == 422
    assert rm(c, cid, "directory", "dirfull").status_code == 422
    assert rm(c, cid, "zfs", "tankvm").status_code == 422
    assert not writes()


def test_unreadable_storage_state_refuses(api):
    c, cid = api
    ST["read_down"] = "/storage"
    assert rm(c, cid, "lvm", "vgempty").status_code == 502 and not writes()
    ST.clear()
    ST["content_down"] = ("vge",)
    r = rm(c, cid, "lvm", "vgempty")
    assert r.status_code == 502 and "illisible" in r.json()["detail"] and not writes()
    ST.clear()
    ST["storages"] = "pas une liste"
    assert rm(c, cid, "directory", "dirempty").status_code == 502 and not writes()


def test_unreadable_volume_lists_refuse_and_no_secret(api):
    c, cid = api
    ST["read_down"] = "/nodes/enzo/disks/lvm"
    r = rm(c, cid, "lvm", "vgempty")
    assert r.status_code == 502 and SECRET not in r.text and not writes()


def test_other_node_storage_is_ignored(api):
    c, cid = api
    assert rm(c, cid, "directory", "dirempty").status_code == 202                  # 'othernode' (même chemin, autre nœud, 5 éléments) ne compte pas


def test_same_pool_name_in_another_group_is_not_this_pool(api):
    c, cid = api
    assert rm(c, cid, "lvmthin", "pool1", vg="vgthin").status_code == 202           # 'thinother' (vgother/pool1, 7 éléments) n'est pas ce pool


def test_unknown_volume_404(api):
    c, cid = api
    assert rm(c, cid, "lvm", "vgnope").status_code == 404 and rm(c, cid, "lvmthin", "pool1", vg="vgautre").status_code == 404 and not writes()


# ---------------------------------------------------------------- confirmation et saisie
def test_confirm_and_retyped_name(api):
    c, cid = api
    assert rm(c, cid, "lvm", "vgempty", confirm=False).status_code == 400
    for typed in (None, "", "vgempt", "VGEMPTY", "vgempty "):
        assert c.post(f"/api/connections/{cid}/nodes/enzo/disks/lvm/vgempty/delete", json={"confirm": True, "type_name": typed}).status_code == 400
    assert not writes()


def test_thin_pool_needs_vg(api):
    c, cid = api
    assert rm(c, cid, "lvmthin", "pool1").status_code == 400 and not writes()


@pytest.mark.parametrize("name", ["-x", "a b", "a;b", "a.b/c", "x" * 41, ".a"])
def test_name_validated(api, name):
    c, cid = api
    assert rm(c, cid, "lvm", name).status_code in (404, 422) and not CALLS


def test_kind_validated_and_no_delete_http_method(api):
    c, cid = api
    assert rm(c, cid, "btrfs", "x").status_code == 422
    for path in ("lvm/vgempty", "zfs/tankempty", "directory/dirempty", "lvmthin/pool1"):
        assert c.delete(f"/api/connections/{cid}/nodes/enzo/disks/{path}").status_code in (404, 405)
    assert not writes()


def test_unknown_fields_not_forwarded_and_vg_validated(api):
    c, cid = api
    rm(c, cid, "lvm", "vgempty", force=1, command="x", **{"vg": "vgthin"})
    assert writes()[0][2] == "cleanup-config=1&cleanup-disks=0"
    assert rm(c, cid, "lvmthin", "pool1", vg="a;b").status_code == 422


def test_requires_login(api):
    c, cid = api
    c.post("/api/auth/logout")
    assert rm(c, cid, "lvm", "vgempty").status_code == 401 and not CALLS


def test_audit_success_refusal_error_without_secret(api):
    c, cid = api
    rm(c, cid, "lvm", "vgempty")
    rm(c, cid, "lvm", "pve")
    ST["write_fail"] = True
    assert rm(c, cid, "directory", "dirempty").status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("disk-lvm-delete", "started"), ("disk-lvm-delete", "error"), ("disk-directory-delete", "error")]
    assert log[0]["upid"] == UPID and log[0]["target"] == "lvm/enzo:vgempty" and SECRET not in c.get("/api/audit").text


def test_matching_storages_unit():
    ss = [{"storage": "a", "type": "zfspool", "pool": "tank/x"}, {"storage": "b", "type": "zfspool", "pool": "tankX"}]
    assert [s["storage"] for s in DD.matching_storages("zfs", "tank", None, ss)] == ["a"]
