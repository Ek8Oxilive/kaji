import httpx
import pytest

from app import diskspec as D
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[httpx.Request] = []
ST: dict = {}

DATA = {
    "/disks/list": [
        {"devpath": "/dev/nvme0n1", "type": "nvme", "size": 512, "used": "partitions", "gpt": 1, "model": "SSD", "health": "PASSED", "wearout": 98, "serial": "SERIAL-SECRET", "wwn": "WWN-SECRET"},
        {"devpath": "/dev/nvme0n1p1", "type": "partition", "size": 1, "used": "BIOS boot"}, {"devpath": "/dev/nvme0n1p3", "type": "partition", "size": 5, "used": "LVM"},
        {"devpath": "/dev/sda", "type": "hdd", "size": 500, "used": "partitions", "wearout": "N/A", "health": "PASSED"},
        {"devpath": "/dev/sda1", "type": "partition", "size": 2}, {"devpath": "/dev/sdab1", "type": "partition", "size": 9},     # sdab1 n'est pas une partition de sda
        {"devpath": "/dev/../etc", "type": "hdd"}, {"devpath": "sda;rm", "type": "hdd"}, "illisible", None,
    ],
    "/disks/lvm": {"leaf": 0, "children": [{"name": "pve", "size": 100, "free": 5, "lvcount": 16, "children": [{"name": "/dev/nvme0n1p3", "leaf": 1}]}, {"size": 1}]},
    "/disks/lvmthin": [{"lv": "data", "vg": "pve", "lv_size": 300, "used": 100, "metadata_size": 4, "metadata_used": 1}, {"vg": "x"}],
    "/disks/directory": [{"path": "/mnt/pve/d", "device": "/dev/sdb1", "type": "ext4", "options": "defaults"}, {"device": "x"}],
    "/disks/zfs": [{"name": "tank", "size": 10, "alloc": 4, "free": 6, "health": "ONLINE", "frag": 3}, {"name": "bad", "frag": 500}],
    "/disks/smart": {"health": "PASSED", "type": "text", "wearout": 98, "text": "SMART ok\n" + "x" * 20000, "serial": "SERIAL-SECRET"},
}


def _handler(request: httpx.Request) -> httpx.Response:
    CALLS.append(request)
    p = request.url.path.removeprefix("/api2/json").removeprefix("/nodes/enzo")
    if ST.get("down"):
        return httpx.Response(500, json={"data": None})
    if p in ST.get("forbid", ()):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    if p in DATA:
        return httpx.Response(200, json={"data": ST.get("smart") if p == "/disks/smart" and "smart" in ST else DATA[p]})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def get(c, cid, path="", node="enzo"):
    return c.get(f"/api/connections/{cid}/nodes/{node}/disks{path}")


def test_everything_shaped(api):
    c, cid = api
    d = get(c, cid).json()
    assert all(v["state"] == "ok" for v in d.values())
    disks = d["disks"]["data"]
    assert [x["device"] for x in disks] == ["/dev/nvme0n1", "/dev/sda"]
    assert [p["device"] for p in disks[0]["partitions"]] == ["/dev/nvme0n1p1", "/dev/nvme0n1p3"]
    assert [p["device"] for p in disks[1]["partitions"]] == ["/dev/sda1"]                      # sdab1 n'appartient pas à sda
    assert disks[1]["wearout"] is None and disks[0]["wearout"] == 98
    assert d["lvm"]["data"] == [{"name": "pve", "size": 100, "free": 5, "volumes": 16, "devices": ["/dev/nvme0n1p3"]}]
    assert d["lvmthin"]["data"][0]["name"] == "data" and len(d["lvmthin"]["data"]) == 1
    assert d["directory"]["data"] == [{"path": "/mnt/pve/d", "device": "/dev/sdb1", "type": "ext4", "options": "defaults"}]
    assert [z["name"] for z in d["zfs"]["data"]] == ["bad", "tank"] and d["zfs"]["data"][0]["fragmentation"] is None


def test_no_serial_or_secret_leaks(api):
    c, cid = api
    body = get(c, cid).text + get(c, cid, "/smart?disk=/dev/sda").text
    for leak in ("SERIAL-SECRET", "WWN-SECRET", SECRET):
        assert leak not in body


def test_forbidden_section_is_isolated(api):
    c, cid = api
    ST["forbid"] = ("/disks/zfs",)
    d = get(c, cid).json()
    assert d["zfs"] == {"state": "forbidden", "data": None} and d["disks"]["state"] == "ok"
    assert SECRET not in str(d)


def test_all_down_is_502(api):
    c, cid = api
    ST["down"] = True
    assert get(c, cid).status_code == 502


def test_only_get_and_constant_parameters(api):
    c, cid = api
    get(c, cid)
    get(c, cid, "/smart?disk=/dev/sda")
    assert CALLS and all(r.method == "GET" for r in CALLS)
    assert {r.url.params.get("include-partitions") for r in CALLS if r.url.path.endswith("/disks/list")} == {"1"}


def test_smart_text_is_bounded_and_disk_passed(api):
    c, cid = api
    r = get(c, cid, "/smart?disk=/dev/nvme0n1").json()
    assert r["health"] == "PASSED" and len(r["text"]) == D.MAX_SMART_TEXT and r["attributes"] == []
    assert CALLS[-1].url.params["disk"] == "/dev/nvme0n1"


def test_smart_ata_attributes(api):
    c, cid = api
    ST["smart"] = {"type": "ata", "health": "PASSED", "attributes": [{"id": 5, "name": "Reallocated_Sector_Ct", "value": 100, "worst": 100, "threshold": 10, "raw": "0", "fail": "-"},
                                                                       {"id": 9, "name": "Power_On_Hours", "value": 90, "worst": 90, "threshold": 0, "raw": "9999", "fail": "FAILING_NOW"}, {"id": 1}]}
    a = get(c, cid, "/smart?disk=/dev/sda").json()["attributes"]
    assert [x["name"] for x in a] == ["Reallocated_Sector_Ct", "Power_On_Hours"] and [x["failing"] for x in a] == [False, True]


@pytest.mark.parametrize("disk", ["/dev/../etc/passwd", "/dev/sda;rm", "sda", "/dev/sda/x", "/dev/", "x/dev/sda", "/dev/sda\n", "/etc/passwd", "/dev/" + "a" * 40])
def test_smart_disk_is_validated(api, disk):
    c, cid = api
    assert c.get(f"/api/connections/{cid}/nodes/enzo/disks/smart", params={"disk": disk}).status_code == 422
    assert not CALLS


def test_node_validated_and_login_required(api):
    c, cid = api
    assert get(c, cid, node="a;b").status_code == 422 and not CALLS
    c.post("/api/auth/logout")
    assert get(c, cid).status_code == 401 and get(c, cid, "/smart?disk=/dev/sda").status_code == 401


def test_shapes_tolerate_garbage():
    for f in (D.shape_disks, D.shape_lvm, D.shape_lvmthin, D.shape_directories, D.shape_zfs, D.shape_smart):
        for junk in (None, 5, "x", [], {}, [None, 3, "x"], {"children": "x", "attributes": 3, "type": "ata"}):
            f(junk)
