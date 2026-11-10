"""Passthrough PCI, USB et répertoires d'une VM par correspondance : faux Proxmox STRICT (formats des propriétés, non-root refusé pour un hôte brut, digest, 400/403 sinon)."""
import re
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from app.deps import get_client_factory
from app.main import app
from app.passthroughspec import Device, build, free_key, parse, shape_devices
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}
VAL = {"hostpci": re.compile(r"^mapping=[A-Za-z][A-Za-z0-9_\-]*(,(pcie|rombar|x-vga)=[01]|,mdev=[A-Za-z0-9_\-]+)*$"), "usb": re.compile(r"^mapping=[A-Za-z][A-Za-z0-9_\-]*(,usb3=[01])?$"),
       "virtiofs": re.compile(r"^dirid=[A-Za-z][A-Za-z0-9_\-]*(,cache=(always|auto|metadata|never)|,(direct-io|expose-acl|expose-xattr)=[01])*$")}
KEYS = re.compile(r"^(hostpci([0-9]|1[0-5])|usb([0-9]|1[0-3])|virtiofs[0-9])$")


def fresh():
    CALLS.clear(); ST.clear()
    ST.update(status="stopped", digest="d" * 40, pending=[], fail=None, lazy=False,
              cfg={"name": "kaji-sandbox", "machine": "q35", "memory": "256", "hostpci1": "0000:01:00.0,pcie=1", "usb2": "host=0bda:b00a", "digest": "d" * 40},
              maps={"pci": [{"id": "gpu", "map": ["node=enzo,path=0000:01:00.0,id=10de:21c4"], "mdev": "1"}, {"id": "smbus", "map": ["node=enzo,path=0000:00:1f.4,id=8086:06a3"]},
                           {"id": "elsewhere", "map": ["node=enzo2,path=0000:00:02.0,id=8086:1903"]}],
                    "usb": [{"id": "bt", "map": ["node=enzo,id=0bda:b00a,path=1-13"]}], "dir": [{"id": "share", "map": ["node=enzo,path=/srv/share"]}]})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    q = dict(request.url.params)
    if ST["fail"] and request.method != "GET":
        return httpx.Response(ST["fail"], json={"data": None, "message": "Permission check failed"})
    if request.method == "GET":
        if p == "/nodes/enzo/qemu/115/config":
            assert "current" not in q                                                  # configuration fusionnée avec les changements en attente
            return httpx.Response(200, json={"data": ST["cfg"]})
        if p == "/nodes/enzo/qemu/115/status/current":
            return httpx.Response(200, json={"data": {"status": ST["status"]}})
        if p == "/nodes/enzo/qemu/115/pending":
            return httpx.Response(200, json={"data": ST["pending"]})
        mm = re.fullmatch(r"/cluster/mapping/(pci|usb|dir)", p)
        if mm:
            return httpx.Response(200, json={"data": ST["maps"][mm[1]]})
        return httpx.Response(404, json={"data": None})
    assert request.method == "PUT" and p == "/nodes/enzo/qemu/115/config", (request.method, p)
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if "digest" in body and body.pop("digest") != ST["cfg"]["digest"]:
        return httpx.Response(400, json={"data": None, "message": "detected modified configuration"})
    for k, v in body.items():
        if k == "delete":
            if not all(KEYS.fullmatch(d) for d in v.split(",")):
                return httpx.Response(400, json={"data": None, "message": "delete: invalid key"})
            continue
        m = KEYS.fullmatch(k)
        base = re.sub(r"\d+$", "", k)
        if not m or base not in VAL:
            return httpx.Response(400, json={"data": None, "message": f"unknown parameter {k}"})
        if not v.startswith(("mapping=", "dirid=")):
            return httpx.Response(403, json={"data": None, "message": f"only root can set '{k}' config for non-mapped devices"})
        if not VAL[base].fullmatch(v):
            return httpx.Response(400, json={"data": None, "message": f"{k}: invalid format"})
    CALLS.append(("PUT", p, body))
    if ST["lazy"]:
        return httpx.Response(200, json={"data": None})                               # répond 200 sans rien enregistrer
    for k, v in body.items():
        if k == "delete":
            for d in v.split(","):
                ST["cfg"].pop(d, None)
        else:
            ST["cfg"][k] = v
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, suffix="", vmid=115):
    return f"/api/connections/{cid}/guests/enzo/qemu/{vmid}/passthrough{suffix}"


# ---------- fonctions pures ----------

def test_build_is_canonical_per_type():
    assert build("pci", Device(mapping="gpu", pcie=True, rombar=False, x_vga=True, mdev="nvidia-63")) == "mapping=gpu,pcie=1,rombar=0,x-vga=1,mdev=nvidia-63"
    assert build("pci", Device(mapping="smbus")) == "mapping=smbus"
    assert build("usb", Device(mapping="bt", usb3=True)) == "mapping=bt,usb3=1"
    assert build("dir", Device(mapping="share", cache="never", direct_io=False, expose_acl=True, expose_xattr=True)) == "dirid=share,cache=never,direct-io=0,expose-acl=1,expose-xattr=1"


@pytest.mark.parametrize("ptype,kw", [("usb", dict(pcie=True)), ("usb", dict(mdev="x")), ("pci", dict(usb3=True)), ("pci", dict(cache="auto")), ("dir", dict(pcie=False)), ("dir", dict(mdev="nvidia-1"))])
def test_options_of_another_type_are_refused(ptype, kw):
    with pytest.raises(ValueError):
        build(ptype, Device(mapping="m", **kw))


@pytest.mark.parametrize("bad", [{"mapping": "1abc"}, {"mapping": "a,host=0000:00:02.0"}, {"mapping": "a b"}, {"mapping": "x" * 65}, {"mapping": "ok", "mdev": "a,b"}, {"mapping": "ok", "mdev": "../x"},
                                 {"mapping": "ok", "cache": "evil"}, {"mapping": "ok", "pcie": "peut-etre"}, {"mapping": ""}])
def test_hostile_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        Device(**bad)


def test_parse_flags_raw_devices_and_drops_hostile_parts():
    m = parse("pci", "hostpci0", "mapping=gpu,pcie=1,rombar=0,x-vga=1,mdev=nvidia-63,evil=1")
    assert m == {"key": "hostpci0", "type": "pci", "mapping": "gpu", "raw": False, "host": None, "pcie": True, "rombar": False, "x_vga": True, "mdev": "nvidia-63", "other": ["evil"]}
    raw = parse("pci", "hostpci1", "0000:01:00.0;0000:01:00.1,pcie=1")
    assert raw["raw"] is True and raw["mapping"] is None and raw["host"] == "0000:01:00.0;0000:01:00.1" and raw["pcie"] is True
    assert parse("usb", "usb2", "host=0bda:b00a")["host"] == "0bda:b00a" and parse("usb", "usb0", "mapping=bt,usb3=1")["usb3"] is True
    assert parse("dir", "virtiofs0", "dirid=share,cache=evil")["cache"] is None
    for key, val in (("hostpci99", "mapping=a"), ("hostpci0", 5), ("usb0", "x" * 2000), ("virtiofs", "dirid=a")):
        assert parse("pci" if key.startswith("hostpci") else "usb" if key.startswith("usb") else "dir", key, val) is None
    assert parse("pci", "hostpci0", "mapping=../x")["mapping"] is None and parse("pci", "hostpci0", "host=a;rm -rf /")["host"] is None


def test_shape_and_free_key():
    cfg = {"hostpci10": "mapping=a", "hostpci2": "mapping=b", "hostpci0": "mapping=c", "usb0": "mapping=d", "name": "x"}
    assert [r["key"] for r in shape_devices(cfg, "pci")] == ["hostpci0", "hostpci2", "hostpci10"]
    assert free_key(cfg, "pci") == "hostpci1" and free_key({f"usb{i}": "x" for i in range(14)}, "usb") is None and free_key({}, "dir") == "virtiofs0"


# ---------- API ----------

def test_requires_auth(client):
    assert client.get(u(1)).status_code == 401
    assert client.post(u(1, "/pci"), json={"mapping": "a"}).status_code == 401
    assert client.put(u(1, "/pci/hostpci0"), json={"mapping": "a"}).status_code == 401
    assert client.delete(u(1, "/pci/hostpci0?confirm=true")).status_code == 401


def test_get_lists_devices_pending_and_state(api):
    c, cid = api
    ST["pending"] = [{"key": "hostpci1", "pending": "mapping=gpu"}, {"key": "memory", "pending": "512"}, {"key": "usb2", "delete": 1}, "junk"]
    r = c.get(u(cid)).json()
    assert [d["key"] for d in r["pci"]] == ["hostpci1"] and r["pci"][0]["raw"] is True and r["usb"][0]["raw"] is True and r["dir"] == []
    assert r["pending"] == ["hostpci1", "usb2"] and r["machine"] == "q35" and r["running"] is False
    ST["status"] = "running"
    assert c.get(u(cid)).json()["running"] is True


def test_add_pci_uses_first_free_slot_digest_and_reads_back(api):
    c, cid = api
    r = c.post(u(cid, "/pci"), json={"mapping": "smbus", "pcie": True, "rombar": False})
    assert r.status_code == 201 and r.json()["key"] == "hostpci0" and r.json()["device"]["mapping"] == "smbus" and r.json()["pending"] is False and r.json()["warnings"] == []
    assert CALLS[0][2] == {"hostpci0": "mapping=smbus,pcie=1,rombar=0"}
    assert ST["cfg"]["hostpci0"] == "mapping=smbus,pcie=1,rombar=0"


def test_add_usb_and_dir(api):
    c, cid = api
    assert c.post(u(cid, "/usb"), json={"mapping": "bt", "usb3": True}).json()["key"] == "usb0" and CALLS[0][2] == {"usb0": "mapping=bt,usb3=1"}
    assert c.post(u(cid, "/dir"), json={"mapping": "share", "cache": "auto"}).json()["key"] == "virtiofs0" and CALLS[1][2] == {"virtiofs0": "dirid=share,cache=auto"}


def test_dry_run_writes_nothing_and_warns(api):
    c, cid = api
    ST["cfg"]["machine"] = "i440fx"
    r = c.post(u(cid, "/pci"), json={"mapping": "elsewhere", "pcie": True, "dry_run": True})
    assert r.status_code == 200 and r.json()["key"] == "hostpci0" and r.json()["value"] == "mapping=elsewhere,pcie=1" and r.json()["running"] is False and not CALLS
    assert len(r.json()["warnings"]) == 2 and "enzo" in r.json()["warnings"][0] and "q35" in r.json()["warnings"][1]


def test_add_refusals_never_reach_proxmox(api):
    c, cid = api
    assert c.post(u(cid, "/pci"), json={"mapping": "absent"}).status_code == 422
    ST["maps"]["pci"][0]["mdev"] = None
    assert c.post(u(cid, "/pci"), json={"mapping": "gpu", "mdev": "nvidia-1"}).status_code == 422                # la correspondance n'est pas médiée
    assert c.post(u(cid, "/usb"), json={"mapping": "bt", "pcie": True}).status_code == 422
    assert c.post(u(cid, "/pci"), json={"mapping": "a,host=0000:00:02.0"}).status_code == 422
    assert c.post(u(cid, "/gpu"), json={"mapping": "gpu"}).status_code == 422
    ST["cfg"]["hostpci0"] = "mapping=smbus"
    assert c.post(u(cid, "/pci"), json={"mapping": "smbus"}).status_code == 409                                    # déjà utilisée par hostpci0
    assert not CALLS


def test_mdev_is_accepted_only_for_a_mediated_mapping(api):
    c, cid = api
    r = c.post(u(cid, "/pci"), json={"mapping": "gpu", "mdev": "nvidia-63"})                                          # la correspondance « gpu » est médiée
    assert r.status_code == 201 and CALLS[0][2] == {"hostpci0": "mapping=gpu,mdev=nvidia-63"}


def test_add_refused_when_no_slot_is_free(api):
    c, cid = api
    for i in range(10):
        ST["cfg"][f"virtiofs{i}"] = "dirid=other"
    assert c.post(u(cid, "/dir"), json={"mapping": "share"}).status_code == 409 and not CALLS


def test_update_replaces_options(api):
    c, cid = api
    ST["cfg"]["hostpci0"] = "mapping=gpu,pcie=1,x-vga=1"
    r = c.put(u(cid, "/pci/hostpci0"), json={"mapping": "gpu", "pcie": False})
    assert r.status_code == 200 and CALLS[0][2] == {"hostpci0": "mapping=gpu,pcie=0"} and ST["cfg"]["hostpci0"] == "mapping=gpu,pcie=0" and r.json()["device"]["x_vga"] is None


def test_update_and_remove_refuse_raw_unknown_and_invalid_keys(api):
    c, cid = api
    assert c.put(u(cid, "/pci/hostpci1"), json={"mapping": "gpu"}).status_code == 409                               # hôte brut : réservé à root
    assert c.delete(u(cid, "/pci/hostpci1?confirm=true")).status_code == 409
    assert c.put(u(cid, "/pci/hostpci5"), json={"mapping": "gpu"}).status_code == 404
    assert c.delete(u(cid, "/pci/hostpci5?confirm=true")).status_code == 404
    for key in ("usb0", "hostpci16", "hostpci1;x"):
        assert c.put(u(cid, f"/pci/{key}"), json={"mapping": "gpu"}).status_code == 404
    assert not CALLS


def test_remove_needs_confirm_and_deletes_the_key(api):
    c, cid = api
    ST["cfg"]["usb0"] = "mapping=bt"
    assert c.delete(u(cid, "/usb/usb0")).status_code == 400 and not CALLS
    assert c.delete(u(cid, "/usb/usb0?dry_run=true")).json() == {"dry_run": True, "remove": "usb0", "mapping": "bt", "running": False} and not CALLS
    r = c.delete(u(cid, "/usb/usb0?confirm=true"))
    assert r.status_code == 200 and r.json() == {"removed": "usb0", "pending": False} and CALLS[0][2] == {"delete": "usb0"} and "usb0" not in ST["cfg"]


def test_running_vm_marks_changes_pending(api):
    c, cid = api
    ST["status"] = "running"
    assert c.post(u(cid, "/pci"), json={"mapping": "smbus"}).json()["pending"] is True
    assert c.delete(u(cid, "/pci/hostpci0?confirm=true")).json() == {"removed": "hostpci0", "pending": True}
    assert "en attente" in c.get("/api/audit").json()[0]["detail"]


def test_protected_vm_is_refused(api, monkeypatch):
    c, cid = api
    monkeypatch.setattr("app.routers.passthrough.get_settings", lambda: type("S", (), {"protected_vmids": {115}})())
    assert c.post(u(cid, "/pci"), json={"mapping": "smbus"}).status_code == 403
    assert c.put(u(cid, "/pci/hostpci0"), json={"mapping": "smbus"}).status_code == 403
    assert c.delete(u(cid, "/pci/hostpci0?confirm=true")).status_code == 403 and not CALLS
    assert c.get(u(cid)).status_code == 200                                                                          # la lecture reste permise


def test_stale_digest_and_proxmox_refusal_are_errors(api):
    c, cid = api
    orig = _handler

    def moved(request):
        if request.method == "PUT":
            ST["cfg"]["digest"] = "e" * 40
        return orig(request)
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(moved)))
    assert c.post(u(cid, "/pci"), json={"mapping": "smbus"}).status_code == 502 and not CALLS
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(orig)))
    ST["fail"] = 403
    assert c.post(u(cid, "/pci"), json={"mapping": "smbus"}).status_code == 502


def test_a_write_proxmox_did_not_apply_is_reported(api):
    c, cid = api
    ST["lazy"] = True
    assert c.post(u(cid, "/pci"), json={"mapping": "smbus"}).status_code == 502
    ST["cfg"]["usb0"] = "mapping=bt"
    assert c.delete(u(cid, "/usb/usb0?confirm=true")).status_code == 502


def test_audit_records_writes_and_refusals_without_secrets(api):
    c, cid = api
    c.post(u(cid, "/pci"), json={"mapping": "smbus"})
    c.post(u(cid, "/pci"), json={"mapping": "absent"})
    c.delete(u(cid, "/pci/hostpci0?confirm=true"))
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("passthrough-add", "started"), ("passthrough-add", "error"), ("passthrough-remove", "started")]
    assert log[0]["detail"] == "hostpci0 : mapping=smbus" and SECRET not in c.get("/api/audit").text
