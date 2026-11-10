"""Correspondances de ressources (PCI, USB, répertoires) : faux Proxmox STRICT (formats lus sur le vrai nœud, paramètres autorisés par type, digest, 400 sinon)."""
import re
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from app.deps import get_client_factory
from app.main import app
from app.mappingspec import MapEntry, MappingCreate, MappingUpdate, build_map, build_params, digest_of, parse_entry, shape_hardware, shape_list, shape_mapping
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}
PCI_PATH = re.compile(r"^(?:[0-9a-f]{4,}:[0-9a-f]{2}:[0-9a-f]{2}(?:\.[0-9a-f])?;)*[0-9a-f]{4,}:[0-9a-f]{2}:[0-9a-f]{2}(?:\.[0-9a-f])?$")
HEX = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$")
USB_PATH = re.compile(r"^\d+-\d+(\.\d+)*$")
ENTRY_KEYS = {"pci": {"node", "path", "id", "iommugroup", "subsystem-id", "description"}, "usb": {"node", "id", "path", "description"}, "dir": {"node", "path"}}
TOP = {"pci": {"id", "map", "description", "mdev", "live-migration-capable"}, "usb": {"id", "map", "description"}, "dir": {"id", "map", "description"}}
PUT_KEYS = {"pci": {"map", "description", "mdev", "live-migration-capable", "delete", "digest"}, "usb": {"map", "description", "delete", "digest"}, "dir": {"map", "description", "delete", "digest"}}
PCI1 = "node=enzo,path=0000:00:04.0,id=8086:1903,iommugroup=2,subsystem-id=103c:8767"
USB1 = "node=enzo,id=0bda:b00a,path=1-13"
DIR1 = "node=enzo,path=/srv/share"


def fresh():
    CALLS.clear(); ST.clear()
    ST.update(maps={"pci": {}, "usb": {}, "dir": {}}, digest="d" * 40, fail_get_config=None,
              guests=[{"vmid": 100, "node": "enzo", "type": "qemu"}, {"vmid": 101, "node": "enzo2", "type": "qemu"}, {"vmid": 105, "node": "enzo", "type": "lxc"}],
              configs={100: {"name": "web", "hostpci0": "mapping=gpu,pcie=1", "usb0": "host=0bda:b00a"}, 101: {"name": "db", "virtiofs0": "dirid=share"}})


def bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def _check_entry(mtype, s):
    kv = dict(p.partition("=")[::2] for p in s.split(","))
    if not set(kv) <= ENTRY_KEYS[mtype] or "node" not in kv:
        return f"entrée invalide : {s}"
    if mtype == "pci" and (not PCI_PATH.fullmatch(kv.get("path", "")) or not HEX.fullmatch(kv.get("id", ""))):
        return "pci : path et id obligatoires"
    if mtype == "usb" and (not HEX.fullmatch(kv.get("id", "")) or ("path" in kv and not USB_PATH.fullmatch(kv["path"]))):
        return "usb : id obligatoire"
    if mtype == "dir" and not kv.get("path", "").startswith("/"):
        return "dir : path absolu obligatoire"
    return None


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    m, q = request.method, dict(request.url.params)
    body = {k: (v if k == "map" else v[0]) for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if m == "GET":
        if p == "/cluster/resources":
            assert q == {"type": "vm"}
            return httpx.Response(200, json={"data": [{**g, "id": f"{g['type']}/{g['vmid']}"} for g in ST["guests"]]})
        mm = re.fullmatch(r"/nodes/(enzo2?)/qemu/(\d+)/config", p)
        if mm:
            if ST["fail_get_config"] == int(mm[2]):
                return httpx.Response(403, json={"data": None})
            return httpx.Response(200, json={"data": ST["configs"][int(mm[2])]})
        mm = re.fullmatch(r"/nodes/enzo/hardware/(pci|usb)", p)
        if mm:
            return httpx.Response(200, json={"data": ST["hw"][mm[1]]})
        mm = re.fullmatch(r"/cluster/mapping/(pci|usb|dir)", p)
        if mm:
            assert set(q) <= {"check-node"}
            rows = [{k: v for k, v in r.items() if k != "digest"} for r in ST["maps"][mm[1]].values()]
            if "check-node" in q:
                rows = [{**r, "checks": [{"severity": "warning", "message": "device not found"}]} for r in rows]
            return httpx.Response(200, json={"data": rows})
        mm = re.fullmatch(r"/cluster/mapping/(pci|usb|dir)/([A-Za-z0-9_\-]+)", p)
        if mm:
            r = ST["maps"][mm[1]].get(mm[2])
            return httpx.Response(200, json={"data": {**r, "digest": ST["digest"]}}) if r else httpx.Response(404, json={"data": None})
        return httpx.Response(404, json={"data": None})
    mm = re.fullmatch(r"/cluster/mapping/(pci|usb|dir)(?:/([A-Za-z0-9_\-]+))?", p)
    assert mm, p
    t, mid = mm[1], mm[2]
    if m == "POST":
        if not set(body) <= TOP[t] or "id" not in body or not body.get("map"):
            return bad("paramètres invalides")
        for s in body["map"]:
            if (e := _check_entry(t, s)):
                return bad(e)
        if body["id"] in ST["maps"][t]:
            return bad("already exists")
        for k in ("mdev", "live-migration-capable"):
            if k in body and body[k] not in ("0", "1"):
                return bad(f"{k} doit être 0/1")
        CALLS.append(("POST", p, body))
        ST["maps"][t][body["id"]] = {"id": body["id"], "map": body["map"], **{k: v for k, v in body.items() if k in ("description", "mdev", "live-migration-capable")}}
        return httpx.Response(200, json={"data": None})
    if m == "PUT":
        if not set(body) <= PUT_KEYS[t]:
            return bad("paramètre inconnu")
        if t == "usb" and "map" not in body:
            return bad("map est obligatoire")
        if "digest" in body and body["digest"] != ST["digest"]:
            return bad("detected modified configuration")
        for s in body.get("map", []):
            if (e := _check_entry(t, s)):
                return bad(e)
        CALLS.append(("PUT", p, body))
        row = ST["maps"][t][mid]
        for k, v in body.items():
            if k == "delete":
                for d in v.split(","):
                    row.pop(d, None)
            elif k != "digest":
                row[k] = v
        return httpx.Response(200, json={"data": None})
    CALLS.append(("DELETE", p, body))
    ST["maps"][t].pop(mid, None)
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    fresh()
    ST["hw"] = {"pci": [], "usb": []}
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, suffix=""):
    return f"/api/connections/{cid}/mappings{suffix}"


def entry(**kw):
    return {"node": "enzo", **kw}


def add(t, mid, entries, **extra):
    ST["maps"][t][mid] = {"id": mid, "map": entries, **extra}


# ---------- fonctions pures ----------

def test_entry_strings_per_type_in_canonical_order():
    assert build_map("pci", [MapEntry(node="enzo", path="0000:00:04.0", id="8086:1903", iommugroup=2, subsystem_id="103C:8767", description="carte video")]) == \
        ["node=enzo,path=0000:00:04.0,id=8086:1903,iommugroup=2,subsystem-id=103c:8767,description=carte video"]
    assert build_map("usb", [MapEntry(node="enzo", id="0BDA:B00A", path="1-13"), MapEntry(node="enzo2", id="0bda:b00a")]) == ["node=enzo,id=0bda:b00a,path=1-13", "node=enzo2,id=0bda:b00a"]
    assert build_map("dir", [MapEntry(node="enzo", path="/srv/share")]) == ["node=enzo,path=/srv/share"]


@pytest.mark.parametrize("mtype,e", [
    ("pci", dict(node="enzo", id="8086:1903")), ("pci", dict(node="enzo", path="0000:00:04.0")), ("pci", dict(node="enzo", path="xx", id="8086:1903")),
    ("pci", dict(node="enzo", path="0000:00:04.0;pas-une-adresse", id="8086:1903")), ("usb", dict(node="enzo")), ("usb", dict(node="enzo", id="0bda:b00a", path="13")),
    ("usb", dict(node="enzo", id="0bda:b00a", iommugroup=3)), ("dir", dict(node="enzo")), ("dir", dict(node="enzo", path="relatif")), ("dir", dict(node="enzo", path="/srv/../etc")),
    ("dir", dict(node="enzo", path="/srv/x", id="8086:1903")), ("pci", dict(node="enzo", path="0000:00:04.0", id="8086:1903", description="a,node=evil")),
])
def test_invalid_entries_are_refused_for_their_type(mtype, e):
    with pytest.raises(ValueError):
        build_map(mtype, [MapEntry(**e)])


@pytest.mark.parametrize("bad", [
    dict(node="x;y"), dict(node="enzo", id="zzzz:0000"), dict(node="enzo", id="8086:19033"), dict(node="enzo", iommugroup=-1), dict(node="enzo", iommugroup=70000),
    dict(node="enzo", subsystem_id="1:2"), dict(node="enzo", description="a=b"), dict(node="enzo", description="a\nb"), dict(node="enzo", description='a"b'), dict(node="enzo", path="x" * 301),
])
def test_entry_model_rejects_hostile_values(bad):
    with pytest.raises(ValidationError):
        MapEntry(**bad)


def test_duplicate_entries_and_foreign_properties_are_refused():
    e = MapEntry(node="enzo", path="/srv/share")
    with pytest.raises(ValueError):
        build_map("dir", [e, e])
    with pytest.raises(ValueError):
        build_params("usb", MappingCreate(id="u", map=[MapEntry(node="enzo", id="0bda:b00a")], mdev=True), [])
    with pytest.raises(ValueError):
        build_params("dir", MappingUpdate(clear=["mdev"]), ["mdev"])
    with pytest.raises(ValueError):
        build_params("pci", MappingUpdate(mdev=True), ["mdev"])                                    # modifié ET retiré


@pytest.mark.parametrize("bad", [{"id": "1abc"}, {"id": "a b"}, {"id": "x" * 65}, {"id": "ok", "map": []}, {"id": "ok", "map": [{"node": "enzo"}] * 33}, {"id": "ok", "description": "a\nb"},
                                 {"id": "ok", "description": "x" * 501}])
def test_create_body_validation(bad):
    with pytest.raises(ValidationError):
        MappingCreate(**{"map": [{"node": "enzo", "path": "/a"}], **bad})


def test_parse_and_shape_drop_hostile_or_unknown_parts():
    s = parse_entry("pci", "node=enzo,path=0000:00:04.0,id=8086:1903,iommugroup=2,subsystem-id=103C:8767,evil=1,description=ok")
    assert s == {"node": "enzo", "path": "0000:00:04.0", "id": "8086:1903", "iommugroup": 2, "subsystem_id": "103c:8767", "description": "ok"}
    assert parse_entry("pci", "node=x;y,path=0000:00:04.0") is None and parse_entry("pci", 5) is None and parse_entry("pci", "path=0000:00:04.0") is None
    assert parse_entry("dir", "node=enzo,path=/srv/../etc")["path"] is None and parse_entry("usb", "node=enzo,id=zz,path=bad")["id"] is None
    raw = {"id": "gpu", "description": "d\x00", "map": [PCI1, "junk", 5], "checks": [{"message": "m"}, "x", {"message": 5}], "mdev": 1, "live-migration-capable": "0", "digest": "d" * 70, "evil": SECRET}
    d = shape_mapping(raw, "pci")
    assert d["description"] is None and len(d["map"]) == 1 and d["checks"] == ["m"] and d["mdev"] is True and d["live_migration_capable"] is False and d["digest"] is None and SECRET not in str(d)
    assert shape_mapping({"id": "../x"}, "pci") is None and shape_mapping([], "pci") is None
    assert [r["id"] for r in shape_list([{"id": "b"}, {"id": "a"}, "junk", {"id": "1x"}], "usb")] == ["a", "b"]
    assert digest_of({"a": 1, "digest": "x"}) == digest_of({"a": 1, "digest": "y", "checks": ["z"]})


def test_hardware_shaping():
    pci = shape_hardware([{"id": "0000:00:04.0", "iommugroup": 2, "vendor": "0x8086", "device": "0x1903", "subsystem_vendor": "0x103c", "subsystem_device": "0x8767", "device_name": "N"},
                          {"id": "bad", "vendor": "0x8086", "device": "0x1903"}, {"id": "0000:00:05.0", "vendor": "0x80861", "device": "0x1903"}, "junk"], "pci")
    assert pci == [{"id": "0000:00:04.0", "iommugroup": 2, "map_id": "8086:1903", "subsystem_id": "103c:8767", "vendor_name": None, "device_name": "N", "mdev": None, "class": None}]
    usb = shape_hardware([{"busnum": 1, "port": 13, "vendid": "0bda", "prodid": "b00a", "product": "Bluetooth", "class": 224, "speed": "12"},
                          {"busnum": 1, "port": 0, "vendid": "1d6b", "prodid": "0002", "product": "xHCI"}, {"busnum": 1, "port": 1, "vendid": "zz", "prodid": "0002"}], "usb")
    assert [(r["map_id"], r["map_path"]) for r in usb] == [("0bda:b00a", "1-13"), ("1d6b:0002", None)]


# ---------- API ----------

def test_requires_auth(client):
    for method, path in (("get", "/pci"), ("post", "/pci"), ("put", "/pci/x"), ("delete", "/pci/x")):
        assert getattr(client, method)(u(1, path)).status_code == 401
    assert client.get("/api/connections/1/nodes/enzo/hardware/pci").status_code == 401


def test_unknown_type_is_refused(api):
    c, cid = api
    assert c.get(u(cid, "/gpu")).status_code == 422 and c.post(u(cid, "/gpu"), json={"id": "a", "map": [entry(path="/a")]}).status_code == 422 and not CALLS


@pytest.mark.parametrize("mtype,e,extra", [("pci", dict(path="0000:00:04.0", id="8086:1903", iommugroup=2, subsystem_id="103c:8767"), {"mdev": True, "live_migration_capable": False}),
                                           ("usb", dict(id="0bda:b00a", path="1-13"), {}), ("dir", dict(path="/srv/share"), {})])
def test_create_sends_exact_params_and_reads_back(api, mtype, e, extra):
    c, cid = api
    r = c.post(u(cid, f"/{mtype}"), json={"id": "m1", "description": "essai", "map": [entry(**e)], **extra})
    assert r.status_code == 201 and r.json()["id"] == "m1" and r.json()["description"] == "essai" and len(r.json()["map"]) == 1
    sent = CALLS[0][2]
    assert CALLS[0][:2] == ("POST", f"/cluster/mapping/{mtype}") and sent["id"] == "m1" and sent["description"] == "essai" and isinstance(sent["map"], list) and len(sent["map"]) == 1
    if mtype == "pci":
        assert sent["mdev"] == "1" and sent["live-migration-capable"] == "0" and r.json()["mdev"] is True and r.json()["live_migration_capable"] is False


def test_create_with_several_entries_sends_repeated_map(api):
    c, cid = api
    assert c.post(u(cid, "/dir"), json={"id": "d", "map": [entry(path="/a"), {"node": "enzo2", "path": "/b"}]}).status_code == 201
    assert CALLS[0][2]["map"] == ["node=enzo,path=/a", "node=enzo2,path=/b"]


def test_create_dry_run_writes_nothing_and_refusals_never_reach_proxmox(api):
    c, cid = api
    r = c.post(u(cid, "/usb"), json={"id": "u", "map": [entry(id="0bda:b00a")], "dry_run": True})
    assert r.status_code == 200 and r.json() == {"dry_run": True, "params": {"id": "u", "map": ["node=enzo,id=0bda:b00a"]}} and not CALLS
    for body in ({"id": "u", "map": [entry(path="1-13")]}, {"id": "u", "map": [entry(id="0bda:b00a", iommugroup=1)]}, {"id": "u", "map": [entry(id="0bda:b00a")], "mdev": True}):
        assert c.post(u(cid, "/usb"), json=body).status_code == 422
    assert c.post(u(cid, "/usb"), json={"id": "1bad", "map": [entry(id="0bda:b00a")]}).status_code == 422 and not CALLS


def test_create_existing_id_is_a_conflict(api):
    c, cid = api
    add("dir", "d", [DIR1])
    assert c.post(u(cid, "/dir"), json={"id": "d", "map": [entry(path="/x")]}).status_code == 409 and not CALLS


def test_list_and_get_are_shaped_with_checks(api):
    c, cid = api
    add("pci", "gpu", [PCI1, "node=enzo,path=0000:00:05.0,id=8086:1911"], description="GPU", mdev="1")
    add("pci", "bad", ["junk"])
    r = c.get(u(cid, "/pci"))
    assert [x["id"] for x in r.json()] == ["bad", "gpu"] and r.json()[1]["map"][0]["iommugroup"] == 2 and r.json()[1]["mdev"] is True and r.json()[0]["map"] == [] and r.json()[1]["checks"] == []
    assert c.get(u(cid, "/pci?check_node=enzo")).json()[1]["checks"] == ["device not found"]
    assert c.get(u(cid, "/pci?check_node=a;b")).status_code == 422
    g = c.get(u(cid, "/pci/gpu")).json()
    assert g["digest"] and len(g["digest"]) == 40 and g["description"] == "GPU" and c.get(u(cid, "/pci/absent")).status_code == 404


def test_update_replaces_entries_and_description_keeping_digest_check(api):
    c, cid = api
    add("pci", "gpu", [PCI1], description="old", mdev="1")
    d = c.get(u(cid, "/pci/gpu")).json()["digest"]
    r = c.put(u(cid, "/pci/gpu"), json={"description": "new", "map": [entry(path="0000:00:05.0", id="8086:1911")], "digest": d})
    assert r.status_code == 200 and r.json()["description"] == "new" and r.json()["map"][0]["id"] == "8086:1911"
    assert CALLS[0][2] == {"description": "new", "map": ["node=enzo,path=0000:00:05.0,id=8086:1911"], "digest": "d" * 40}
    assert c.put(u(cid, "/pci/gpu"), json={"description": "x", "digest": "0" * 40}).status_code == 409


def test_usb_update_without_map_resends_current_entries(api):
    """Proxmox exige `map` au PUT d'une correspondance USB (lu dans l'API) : les entrées actuelles sont renvoyées telles quelles."""
    c, cid = api
    add("usb", "bt", [USB1])
    assert c.put(u(cid, "/usb/bt"), json={"description": "radio"}).status_code == 200
    assert CALLS[0][2]["map"] == [USB1] and CALLS[0][2]["description"] == "radio" and ST["maps"]["usb"]["bt"]["map"] == [USB1]


def test_update_clear_goes_in_delete_and_is_verified(api):
    c, cid = api
    add("pci", "gpu", [PCI1], description="d", mdev="1", **{"live-migration-capable": "1"})
    r = c.put(u(cid, "/pci/gpu"), json={"clear": ["description", "mdev"]})
    assert r.status_code == 200 and CALLS[0][2]["delete"] == "description,mdev" and r.json()["description"] is None and r.json()["mdev"] is None and r.json()["live_migration_capable"] is True


def test_update_refusals(api):
    c, cid = api
    add("dir", "d", [DIR1])
    assert c.put(u(cid, "/dir/d"), json={}).status_code == 400
    assert c.put(u(cid, "/dir/d"), json={"mdev": True}).status_code == 422
    assert c.put(u(cid, "/dir/d"), json={"description": "x", "clear": ["description"]}).status_code == 422
    assert c.put(u(cid, "/dir/absent"), json={"description": "x"}).status_code == 404
    assert c.put(u(cid, "/dir/d"), json={"description": "x", "dry_run": True}).json() == {"dry_run": True, "params": {"description": "x"}, "remove": []} and not CALLS


def test_delete_needs_confirm_and_retyped_id_and_dry_run_reports_users(api):
    c, cid = api
    add("dir", "d", [DIR1])
    r = c.delete(u(cid, "/dir/d?dry_run=true"))
    assert r.json() == {"dry_run": True, "remove": ["d"], "retype": "d", "used_by": []} and not CALLS
    assert c.delete(u(cid, "/dir/d")).status_code == 400
    assert c.delete(u(cid, "/dir/d?confirm=true")).status_code == 400
    assert c.delete(u(cid, "/dir/d?confirm=true&type_name=autre")).status_code == 400 and not CALLS
    assert c.delete(u(cid, "/dir/d?confirm=true&type_name=d")).json() == {"deleted": "d"} and CALLS[0][:2] == ("DELETE", "/cluster/mapping/dir/d") and "d" not in ST["maps"]["dir"]
    assert c.delete(u(cid, "/dir/d?confirm=true&type_name=d")).status_code == 404


@pytest.mark.parametrize("mtype,mid,users", [("pci", "gpu", ["vm:100"]), ("usb", "host", []), ("dir", "share", ["vm:101"])])
def test_delete_is_refused_while_a_vm_uses_the_mapping(api, mtype, mid, users):
    c, cid = api
    add(mtype, mid, [{"pci": PCI1, "usb": USB1, "dir": DIR1}[mtype]])
    ST["configs"][100]["usb0"] = "host=0bda:b00a,mapping=other"                                  # `mapping=other` : un autre identifiant ne compte pas
    assert c.delete(u(cid, f"/{mtype}/{mid}?dry_run=true")).json()["used_by"] == users
    r = c.delete(u(cid, f"/{mtype}/{mid}?confirm=true&type_name={mid}"))
    if users:
        assert r.status_code == 409 and ", ".join(users) in r.json()["detail"] and not CALLS
    else:
        assert r.status_code == 200


def test_delete_is_refused_when_a_vm_config_is_unreadable_or_too_many_vms(api):
    c, cid = api
    add("pci", "gpu", [PCI1])
    ST["fail_get_config"] = 101
    r = c.delete(u(cid, "/pci/gpu?confirm=true&type_name=gpu"))
    assert r.status_code == 409 and "vm:101" in r.json()["detail"] and not CALLS
    ST["fail_get_config"] = None
    ST["guests"] = [{"vmid": 1000 + i, "node": "enzo", "type": "qemu"} for i in range(65)]
    assert c.delete(u(cid, "/pci/gpu?confirm=true&type_name=gpu")).status_code == 409 and not CALLS


def test_hardware_listing_is_shaped(api):
    c, cid = api
    ST["hw"]["pci"] = [{"id": "0000:00:04.0", "iommugroup": 2, "vendor": "0x8086", "device": "0x1903", "subsystem_vendor": "0x103c", "subsystem_device": "0x8767", "device_name": "N", "evil": SECRET}]
    ST["hw"]["usb"] = [{"busnum": 1, "port": 13, "vendid": "0bda", "prodid": "b00a", "product": "Bluetooth"}]
    p = c.get(f"/api/connections/{cid}/nodes/enzo/hardware/pci")
    assert p.status_code == 200 and p.json()[0]["map_id"] == "8086:1903" and p.json()[0]["subsystem_id"] == "103c:8767" and SECRET not in p.text
    assert c.get(f"/api/connections/{cid}/nodes/enzo/hardware/usb").json()[0]["map_path"] == "1-13"
    assert c.get(f"/api/connections/{cid}/nodes/enzo/hardware/gpu").status_code == 422 and c.get(f"/api/connections/{cid}/nodes/a;b/hardware/pci").status_code == 422


def test_audit_records_writes_and_refusals_without_descriptions(api):
    c, cid = api
    c.post(u(cid, "/dir"), json={"id": "d", "description": "texte-prive", "map": [entry(path="/a")]})
    c.post(u(cid, "/dir"), json={"id": "d", "map": [entry(path="/a")]})
    c.delete(u(cid, "/dir/d?confirm=true&type_name=d"))
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("mapping-create", "started"), ("mapping-create", "error"), ("mapping-delete", "started")]
    assert "texte-prive" not in c.get("/api/audit").text and "map=1 entrée(s)" in log[0]["detail"] and SECRET not in c.get("/api/audit").text


def test_a_write_proxmox_did_not_apply_is_reported_as_an_error(api):
    """Proxmox répond 200 sans rien enregistrer : la relecture le détecte (502), rien n'est annoncé comme réussi."""
    c, cid = api
    orig = _handler

    def lazy(request):
        r = orig(request)
        if request.method in ("POST", "PUT") and r.status_code == 200:
            t = request.url.path.removeprefix("/api2/json").split("/")[3]
            if request.method == "POST":
                for row in ST["maps"][t].values():
                    row["description"] = "autre"                       # la création n'a pas été appliquée telle que demandée
            else:
                ST["maps"][t]["gpu"]["description"] = "ancienne"        # la modification non plus
        return r
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(lazy)))
    assert c.post(u(cid, "/dir"), json={"id": "d", "description": "voulue", "map": [entry(path="/a")]}).status_code == 502
    add("pci", "gpu", [PCI1], description="ancienne")
    assert c.put(u(cid, "/pci/gpu"), json={"description": "nouvelle"}).status_code == 502
    assert [(e["action"], e["status"]) for e in c.get("/api/audit").json()[::-1]] == [("mapping-create", "error"), ("mapping-update", "error")]
