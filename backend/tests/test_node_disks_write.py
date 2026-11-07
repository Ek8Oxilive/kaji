import httpx
import pytest

from app import diskwrite as W
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:diskinit:sdb:kaji@pve!kaji:"
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}


def disk(dev, used=None, osd=-1, typ="ssd"):
    return {"devpath": dev, "type": typ, "size": 100, "used": used, "gpt": 1, "osdid": osd, "model": "M", "health": "PASSED"}


def part(dev, used=None):
    return {"devpath": dev, "type": "partition", "size": 1, "used": used}


LIST = [
    disk("/dev/nvme0n1", "partitions", typ="nvme"), part("/dev/nvme0n1p1", "BIOS boot"), part("/dev/nvme0n1p2", "EFI"), part("/dev/nvme0n1p3", "LVM"),
    disk("/dev/sdb"),                                                                  # libre
    disk("/dev/sdc", "partitions"), part("/dev/sdc1"), part("/dev/sdc2"),               # restes inutilisés
    disk("/dev/sdd"), disk("/dev/sde"), disk("/dev/sdf"), disk("/dev/sdg"),
    disk("/dev/sdh", osd=3), disk("/dev/sdi", "ZFS"), disk("/dev/sdj", "partitions"), part("/dev/sdj1", "ext4"), disk("/dev/sdk", "mounted"),
]
EXIST = {"lvm": {"children": [{"name": "pve", "size": 1, "free": 0, "lvcount": 3, "children": []}, {"name": "vgdata", "size": 1, "free": 1, "lvcount": 0, "children": []}]},
         "lvmthin": [{"lv": "data", "vg": "pve"}], "directory": [{"path": "/mnt/pve/dirpris", "device": "/dev/sdx", "type": "ext4"}], "zfs": [{"name": "tank"}]}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json").removeprefix("/nodes/enzo")
    CALLS.append((request.method, p, request.content.decode()))
    if ST.get("read_down") and request.method == "GET":
        return httpx.Response(500, json={"data": None, "message": SECRET})
    if request.method == "GET":
        if p == "/disks/list":
            return httpx.Response(200, json={"data": ST.get("list", LIST)})
        kind = p.removeprefix("/disks/")
        return httpx.Response(200, json={"data": EXIST.get(kind, [])})
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


def post(c, cid, kind, **b):
    return c.post(f"/api/connections/{cid}/nodes/enzo/disks/{kind}", json=b)


def writes():
    return [x for x in CALLS if x[0] != "GET"]


# ---------------------------------------------------------------- GPT / effacer
def test_initgpt_on_free_disk(api):
    c, cid = api
    r = post(c, cid, "initgpt", disk="/dev/sdb", confirm=True, type_name="/dev/sdb")
    assert r.status_code == 202 and r.json() == {"upid": UPID, "node": "enzo"}
    assert writes() == [("POST", "/disks/initgpt", "disk=%2Fdev%2Fsdb")]


def test_wipe_uses_put_on_wipedisk(api):
    c, cid = api
    assert post(c, cid, "wipe", disk="/dev/sdc", confirm=True, type_name="/dev/sdc").status_code == 202      # restes inutilisés : permis
    assert writes() == [("PUT", "/disks/wipedisk", "disk=%2Fdev%2Fsdc")]


@pytest.mark.parametrize("dev", ["/dev/nvme0n1", "/dev/sdh", "/dev/sdi", "/dev/sdj", "/dev/sdk"])
@pytest.mark.parametrize("kind", ["initgpt", "wipe"])
def test_busy_disks_are_never_touched(api, dev, kind):
    """Système, OSD Ceph, ZFS, partition utilisée, monté : refus absolu, même avec toutes les confirmations."""
    c, cid = api
    r = post(c, cid, kind, disk=dev, confirm=True, type_name=dev)
    assert r.status_code == 422 and "refus" in r.json()["detail"] and not writes()


def test_initgpt_refuses_leftover_partitions(api):
    c, cid = api
    r = post(c, cid, "initgpt", disk="/dev/sdc", confirm=True, type_name="/dev/sdc")
    assert r.status_code == 422 and not writes()


def test_unknown_disk_404(api):
    c, cid = api
    assert post(c, cid, "wipe", disk="/dev/sdz", confirm=True, type_name="/dev/sdz").status_code == 404 and not writes()


@pytest.mark.parametrize("kind", ["initgpt", "wipe"])
def test_confirm_and_retyped_disk_required(api, kind):
    c, cid = api
    assert post(c, cid, kind, disk="/dev/sdb", confirm=False, type_name="/dev/sdb").status_code == 400
    for typed in (None, "", "sdb", "/dev/sdc", "/dev/sdb "):
        assert post(c, cid, kind, disk="/dev/sdb", confirm=True, type_name=typed).status_code == 400
    assert not writes()


@pytest.mark.parametrize("disk", ["/dev/../etc", "/dev/sdb;rm", "sdb", "/dev/sdb/x", "/dev/sdb\n", "/dev/" + "a" * 40])
def test_disk_path_validated(api, disk):
    c, cid = api
    assert post(c, cid, "wipe", disk=disk, confirm=True, type_name=disk).status_code == 422
    assert not CALLS


# ---------------------------------------------------------------- volumes
def test_create_lvm(api):
    c, cid = api
    r = post(c, cid, "lvm", name="vgnew", device="/dev/sdb", confirm=True, type_name="vgnew")
    assert r.status_code == 202
    assert writes() == [("POST", "/disks/lvm", "name=vgnew&device=%2Fdev%2Fsdb&add_storage=0")]


def test_create_lvmthin_and_directory(api):
    c, cid = api
    assert post(c, cid, "lvmthin", name="thin1", device="/dev/sdb", add_storage=True, confirm=True, type_name="thin1").status_code == 202
    assert writes()[-1] == ("POST", "/disks/lvmthin", "name=thin1&device=%2Fdev%2Fsdb&add_storage=1")
    assert post(c, cid, "directory", name="dir1", device="/dev/sdd", filesystem="xfs", confirm=True, type_name="dir1").status_code == 202
    assert writes()[-1] == ("POST", "/disks/directory", "name=dir1&device=%2Fdev%2Fsdd&filesystem=xfs&add_storage=0")
    assert post(c, cid, "directory", name="dir2", device="/dev/sde", filesystem="btrfs", confirm=True, type_name="dir2").status_code == 422


@pytest.mark.parametrize("kind", ["lvm", "lvmthin", "directory"])
def test_create_refuses_busy_leftover_and_reserved_and_existing(api, kind):
    c, cid = api
    ok = dict(name="nouveau", device="/dev/sdb", confirm=True, type_name="nouveau")
    for dev in ("/dev/nvme0n1", "/dev/sdh", "/dev/sdi", "/dev/sdj", "/dev/sdk"):
        assert post(c, cid, kind, **{**ok, "device": dev}).status_code == 422
    assert post(c, cid, kind, **{**ok, "device": "/dev/sdc"}).status_code == 422                 # restes : effacer d'abord
    for name in ("pve", "PVE", "rpool", "data", "local-lvm"):
        assert post(c, cid, kind, **{**ok, "name": name, "type_name": name}).status_code == 422
    assert not writes()


def test_create_refuses_existing_names(api):
    c, cid = api
    assert post(c, cid, "lvm", name="vgdata", device="/dev/sdb", confirm=True, type_name="vgdata").status_code == 409
    assert post(c, cid, "lvmthin", name="data", device="/dev/sdb", confirm=True, type_name="data").status_code == 422     # réservé
    assert post(c, cid, "directory", name="dirpris", device="/dev/sdb", confirm=True, type_name="dirpris").status_code == 409
    assert not writes()


def test_create_confirm_and_name_retyped(api):
    c, cid = api
    assert post(c, cid, "lvm", name="vgnew", device="/dev/sdb", confirm=False, type_name="vgnew").status_code == 400
    for typed in (None, "", "vgnewx", "VGNEW", "/dev/sdb"):
        assert post(c, cid, "lvm", name="vgnew", device="/dev/sdb", confirm=True, type_name=typed).status_code == 400
    assert not writes()


@pytest.mark.parametrize("name", ["-x", "a b", "a;b", "a/b", "x" * 41, "", ".a"])
def test_name_validated(api, name):
    c, cid = api
    assert post(c, cid, "lvm", name=name, device="/dev/sdb", confirm=True, type_name=name).status_code == 422
    assert not CALLS


# ---------------------------------------------------------------- ZFS
def zfs(c, cid, **b):
    base = dict(name="pool1", devices=["/dev/sdb"], raidlevel="single", confirm=True, type_name=b.get("name", "pool1"))
    return post(c, cid, "zfs", **{**base, **b})


def test_zfs_single_and_mirror(api):
    c, cid = api
    assert zfs(c, cid).status_code == 202
    assert writes()[-1] == ("POST", "/disks/zfs", "name=pool1&devices=%2Fdev%2Fsdb&raidlevel=single&compression=on&ashift=12&add_storage=0")
    assert zfs(c, cid, name="mir", devices=["/dev/sdd", "/dev/sde"], raidlevel="mirror", compression="zstd", ashift=13, add_storage=True).status_code == 202
    assert writes()[-1][2] == "name=mir&devices=%2Fdev%2Fsdd%2C%2Fdev%2Fsde&raidlevel=mirror&compression=zstd&ashift=13&add_storage=1"


@pytest.mark.parametrize("level,devs,ok", [("single", 2, False), ("mirror", 1, False), ("mirror", 2, True), ("raid10", 3, False), ("raid10", 4, True), ("raid10", 5, False),
                                          ("raidz", 2, False), ("raidz", 3, True), ("raidz2", 3, False), ("raidz2", 4, True), ("raidz3", 4, False)])
def test_zfs_raid_rules(api, level, devs, ok):
    c, cid = api
    devices = ["/dev/sdb", "/dev/sdd", "/dev/sde", "/dev/sdf", "/dev/sdg"][:devs]
    assert (zfs(c, cid, devices=devices, raidlevel=level).status_code == 202) is ok


def test_zfs_every_device_must_be_free(api):
    c, cid = api
    for bad in ("/dev/nvme0n1", "/dev/sdh", "/dev/sdc", "/dev/sdi"):
        assert zfs(c, cid, devices=["/dev/sdb", bad], raidlevel="mirror").status_code == 422
    assert not writes()


def test_zfs_names_and_duplicates(api):
    c, cid = api
    assert zfs(c, cid, name="tank").status_code == 409
    assert zfs(c, cid, name="rpool").status_code == 422
    for bad in ("mirror", "raidz1", "c0", "spare", "draid2"):
        assert zfs(c, cid, name=bad).status_code == 422
    assert zfs(c, cid, devices=["/dev/sdb", "/dev/sdb"], raidlevel="mirror").status_code == 422
    assert zfs(c, cid, ashift=8).status_code == 422 and zfs(c, cid, ashift=17).status_code == 422
    assert zfs(c, cid, compression="gzip-9").status_code == 422 and zfs(c, cid, raidlevel="stripe").status_code == 422
    assert zfs(c, cid, devices=[]).status_code == 422 and zfs(c, cid, devices=[f"/dev/sd{chr(97 + i)}" for i in range(13)], raidlevel="raidz").status_code == 422
    assert zfs(c, cid, devices=["/dev/sdb;x"]).status_code == 422
    assert not writes()


def test_zfs_confirm(api):
    c, cid = api
    assert zfs(c, cid, confirm=False).status_code == 400 and zfs(c, cid, type_name="autre").status_code == 400
    assert not writes()


# ---------------------------------------------------------------- transverse
def test_unreadable_state_refuses_everything(api):
    c, cid = api
    ST["read_down"] = True
    for kind, body in (("initgpt", dict(disk="/dev/sdb", type_name="/dev/sdb")), ("lvm", dict(name="v", device="/dev/sdb", type_name="v"))):
        r = post(c, cid, kind, confirm=True, **body)
        assert r.status_code == 502 and SECRET not in r.text
    assert not writes()


def test_requires_login(api):
    c, cid = api
    c.post("/api/auth/logout")
    assert post(c, cid, "wipe", disk="/dev/sdb", confirm=True, type_name="/dev/sdb").status_code == 401
    assert not CALLS


def test_no_delete_or_arbitrary_route(api):
    c, cid = api
    for m in ("delete", "put", "patch"):
        for path in ("lvm/vgdata", "zfs/tank", "directory/dirpris", "lvmthin/data", "wipe"):
            assert getattr(c, m)(f"/api/connections/{cid}/nodes/enzo/disks/{path}").status_code in (404, 405)
    assert not writes()


def test_unknown_fields_are_ignored_not_forwarded(api):
    c, cid = api
    post(c, cid, "lvm", name="vgnew", device="/dev/sdb", confirm=True, type_name="vgnew", **{"cleanup-config": 1, "command": "rm -rf /", "vgname": "x"})
    assert "cleanup" not in writes()[0][2] and "command" not in writes()[0][2] and "vgname" not in writes()[0][2]


def test_audit_success_refusal_error_without_secret(api):
    c, cid = api
    post(c, cid, "wipe", disk="/dev/sdc", confirm=True, type_name="/dev/sdc")
    post(c, cid, "wipe", disk="/dev/nvme0n1", confirm=True, type_name="/dev/nvme0n1")
    ST["write_fail"] = True
    assert post(c, cid, "lvm", name="vgnew", device="/dev/sdb", confirm=True, type_name="vgnew").status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("disk-wipe", "started"), ("disk-wipe", "error"), ("disk-lvm-create", "error")]
    assert log[0]["upid"] == UPID and log[0]["target"] == "disk/enzo:/dev/sdc" and SECRET not in c.get("/api/audit").text


def test_disk_state_rules():
    assert W.disk_state({"used": None, "partitions": []}) == "free"
    assert W.disk_state({"used": "partitions", "partitions": [{"used": None}]}) == "leftover"
    assert W.disk_state({"used": "partitions", "partitions": [{"used": None}, {"used": "LVM"}]}) == "busy"
    assert W.disk_state({"used": "partitions", "partitions": []}) == "busy"                  # état incohérent : prudence
    assert W.disk_state({"used": None, "partitions": [], "osd": True}) == "busy"
    assert W.disk_state({"used": None, "partitions": [{"used": None}]}) == "busy"
    assert W.disk_state({}) == "free"
