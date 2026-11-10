"""Lien machine -> stockages pour le regroupement « par stockage » (lot #252) : faux Proxmox STRICT, lecture seule (tout appel non GET répond 405)."""
import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}


def res(storage, node="enzo", content="images,rootdir", status="available", shared=0):
    return {"type": "storage", "id": f"storage/{node}/{storage}", "storage": storage, "node": node, "plugintype": "lvmthin", "status": status, "content": content, "shared": shared,
            "disk": 1, "maxdisk": 10}


def vol(volid, content="images", vmid=None):
    v = {"volid": volid, "content": content, "format": "raw", "size": 1}
    if vmid is not None:
        v["vmid"] = vmid
    return v


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, dict(request.url.params)))
    if request.method != "GET":
        return httpx.Response(405, json={"data": None, "message": "lecture seule"})
    if p == "/cluster/resources":
        if dict(request.url.params) != {"type": "storage"} or ST.get("resources_down"):
            return httpx.Response(500 if ST.get("resources_down") else 400, json={"data": None, "message": SECRET})
        return httpx.Response(200, json={"data": ST["storages"]})
    parts = p.strip("/").split("/")
    if len(parts) == 5 and parts[0] == "nodes" and parts[2] == "storage" and parts[4] == "content":
        key = (parts[1], parts[3])
        if key in ST.get("down", set()):
            return httpx.Response(500, json={"data": None, "message": SECRET})
        if key not in ST["volumes"]:
            return httpx.Response(404, json={"data": None, "message": "stockage inconnu du faux Proxmox"})
        return httpx.Response(200, json={"data": ST["volumes"][key]})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    ST.update(storages=[], volumes={}, down=set())
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def get(c, cid):
    return c.get(f"/api/connections/{cid}/guest-storages")


def content_calls():
    return [x for x in CALLS if x[1].endswith("/content")]


def test_maps_each_machine_to_the_storages_holding_its_disks(api):
    c, cid = api
    ST["storages"] = [res("local-lvm"), res("fast", node="enzo2")]
    ST["volumes"] = {("enzo", "local-lvm"): [vol("local-lvm:vm-102-disk-0", vmid=102), vol("local-lvm:vm-103-disk-0", vmid=103), vol("local-lvm:vm-103-disk-1", vmid=103)],
                     ("enzo2", "fast"): [vol("fast:vm-103-disk-2", vmid=103), vol("fast:subvol-104-disk-0", content="rootdir", vmid=104)]}
    j = get(c, cid).json()
    assert j["by_vmid"] == {"102": ["local-lvm"], "103": ["fast", "local-lvm"], "104": ["fast"]}
    assert j["storages"] == ["fast", "local-lvm"] and j["errors"] == 0


def test_only_disk_volumes_count_and_volumes_without_vmid_are_ignored(api):
    c, cid = api
    ST["storages"] = [res("local", content="images,iso,backup,vztmpl")]
    ST["volumes"] = {("enzo", "local"): [vol("local:iso/x.iso", content="iso"), vol("local:backup/vzdump-qemu-100.vma", content="backup", vmid=100),
                                         vol("local:vztmpl/t.tar.zst", content="vztmpl", vmid=101), vol("local:100/vm-100-disk-0.qcow2", content="images", vmid=100),
                                         vol("local:100/orphan.qcow2", content="images")]}
    assert get(c, cid).json()["by_vmid"] == {"100": ["local"]}                                   # la sauvegarde de 100 et le modèle 101 ne comptent pas


def test_storages_that_cannot_hold_disks_or_are_inactive_are_not_even_read(api):
    c, cid = api
    ST["storages"] = [res("isos", content="iso,vztmpl"), res("backups", content="backup"), res("off", status="unknown"), res("ok")]
    ST["volumes"] = {("enzo", "ok"): [vol("ok:vm-100-disk-0", vmid=100)]}
    j = get(c, cid).json()
    assert j["by_vmid"] == {"100": ["ok"]} and j["storages"] == ["ok"]
    assert [x[1] for x in content_calls()] == ["/nodes/enzo/storage/ok/content"]


def test_a_shared_storage_is_read_once(api):
    c, cid = api
    ST["storages"] = [res("nfs", node="enzo", shared=1), res("nfs", node="enzo2", shared=1), res("local-lvm", node="enzo"), res("local-lvm", node="enzo2")]
    ST["volumes"] = {("enzo", "nfs"): [vol("nfs:100/vm-100-disk-0.raw", vmid=100)], ("enzo", "local-lvm"): [vol("local-lvm:vm-101-disk-0", vmid=101)],
                     ("enzo2", "local-lvm"): [vol("local-lvm:vm-102-disk-0", vmid=102)]}
    j = get(c, cid).json()
    assert j["by_vmid"] == {"100": ["nfs"], "101": ["local-lvm"], "102": ["local-lvm"]}
    assert len([x for x in content_calls() if "/storage/nfs/" in x[1]]) == 1                      # nfs lu une seule fois ; local-lvm lu sur chaque nœud
    assert len([x for x in content_calls() if "/storage/local-lvm/" in x[1]]) == 2


def test_an_unreadable_storage_is_counted_without_failing_the_rest_or_leaking(api):
    c, cid = api
    ST["storages"] = [res("a"), res("b")]
    ST["volumes"] = {("enzo", "a"): [vol("a:vm-100-disk-0", vmid=100)], ("enzo", "b"): []}
    ST["down"] = {("enzo", "b")}
    r = get(c, cid)
    assert r.status_code == 200 and r.json()["by_vmid"] == {"100": ["a"]} and r.json()["errors"] == 1 and SECRET not in r.text


def test_the_number_of_calls_is_bounded(api):
    c, cid = api
    ST["storages"] = [res(f"s{i:02d}") for i in range(45)]
    ST["volumes"] = {("enzo", f"s{i:02d}"): [] for i in range(45)}
    j = get(c, cid).json()
    assert len(content_calls()) == 40 and j["errors"] == 5 and len(j["storages"]) == 40


def test_garbage_in_proxmox_data_is_ignored(api):
    c, cid = api
    ST["storages"] = [res("ok"), {"storage": "", "node": "enzo"}, {"node": "enzo"}, "x", {"storage": "noprobe", "node": None, "status": "available", "content": "images"}]
    ST["volumes"] = {("enzo", "ok"): [vol("ok:vm-100-disk-0", vmid=100), {"volid": ""}, "x", {"volid": "ok:vm-abc", "content": "images", "vmid": "abc"}]}
    j = get(c, cid).json()
    assert j["by_vmid"] == {"100": ["ok"]} and j["errors"] == 0 and len(content_calls()) == 1          # la ligne sans nœud n'est même pas lue


def test_read_only_and_proxmox_failure_gives_an_error_without_secret(api):
    c, cid = api
    ST["storages"] = [res("ok")]
    ST["volumes"] = {("enzo", "ok"): []}
    assert get(c, cid).status_code == 200 and all(x[0] == "GET" for x in CALLS)
    ST["resources_down"] = True
    r = get(c, cid)
    assert r.status_code >= 400 and SECRET not in r.text


def test_requires_login(client):
    assert client.get("/api/connections/1/guest-storages").status_code == 401
