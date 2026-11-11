"""Périphériques d'une VM (lot #225) : faux Proxmox STRICT. RIEN n'a tourné sur un vrai cluster.

Le faux n'accepte, sur `PUT …/qemu/{vmid}/config`, que les paramètres du lot ET vérifie le format de chaque valeur comme le fait Proxmox : tout autre
paramètre ou format invalide répond 400.
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.devicespec import DevicesUpdate, build_params

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "a" * 40
ALLOWED = {"vga", "serial0", "serial1", "serial2", "serial3", "audio0", "rng0", "watchdog", "bios", "efidisk0", "tpmstate0", "delete", "digest"}
VGA = re.compile(r"^(type=)?(cirrus|none|qxl[234]?|serial[0-3]|std|virtio|virtio-gl|vmware)(,memory=\d{1,3})?(,clipboard=vnc)?(,[A-Za-z0-9_-]+=[A-Za-z0-9_.-]*)*$|^type=[a-z0-9-]+(,.*)?$")
FORMATS = {
    "vga": VGA,
    "audio0": re.compile(r"^device=(ich9-intel-hda|intel-hda|AC97)(,driver=(spice|none))?$"),
    "rng0": re.compile(r"^source=/dev/urandom(,max_bytes=\d+)?(,period=\d+)?$"),
    "watchdog": re.compile(r"^model=(i6300esb|ib700)(,action=(reset|shutdown|poweroff|pause|debug|none))?$"),
}
DELETABLE = ALLOWED - {"delete", "digest"}
CFG0 = {"name": "kaji-sandbox", "digest": DIGEST, "memory": 256, "scsi0": "local-lvm:vm-115-disk-0,size=1G", "hookscript": "local:snippets/h.pl",
        "args": "-x", "lock": "backup"}
CALLS: list[dict] = []
STATE: dict = {}


def _json(code, body, reason="OK"):
    return httpx.Response(code, json=body, extensions={"reason_phrase": reason.encode()})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
    CALLS.append({"method": request.method, "path": p, "params": dict(request.url.params), "form": form})
    if STATE.get("fail") and (request.method, p) == STATE["fail"][:2]:
        return _json(STATE["fail"][2], {"data": None}, "Internal Server Error")
    if request.method == "GET" and p == "/nodes/enzo/qemu/115/config":
        return _json(200, {"data": STATE.get("cfg", CFG0)})
    if request.method == "GET" and p == "/nodes/enzo/qemu/115/pending":
        return _json(200, {"data": STATE.get("pending", [])})
    if request.method == "PUT" and p == "/nodes/enzo/qemu/115/config":
        if set(form) - ALLOWED:
            return _json(400, {"data": None})
        for k, rx in FORMATS.items():
            if k in form and not rx.fullmatch(form[k]):
                return _json(400, {"data": None})
        if any(re.fullmatch(r"serial[0-3]", k) and form[k] != "socket" for k in form):
            return _json(400, {"data": None})
        if set(filter(None, form.get("delete", "").split(","))) - DELETABLE:
            return _json(400, {"data": None})
        return _json(200, {"data": None})
    return _json(404, {"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    STATE.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, vmid=115, node="enzo"):
    return f"/api/connections/{cid}/guests/{node}/qemu/{vmid}/devices"


def patch(c, cid, **body):
    return c.patch(u(cid), json=body)


def writes():
    return [x for x in CALLS if x["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()


def cfg(**kw):
    return {**CFG0, **kw}


# ------------------------------------------------------------------ lecture

def test_requires_auth(client):
    assert client.get("/api/connections/1/guests/enzo/qemu/115/devices").status_code == 401
    assert client.patch("/api/connections/1/guests/enzo/qemu/115/devices", json={"vga": {"type": "std"}}).status_code == 401


def test_read_defaults_are_null_and_never_writes(api):
    c, cid = api
    r = c.get(u(cid))
    assert r.status_code == 200
    assert r.json() == {"type": "qemu", "pending": [], "reboot_required": False, "devices": {
        "vga": None, "audio": None, "rng": None, "watchdog": None, "serial0": None, "serial1": None, "serial2": None, "serial3": None,
        "bios": None, "efidisk": None, "tpm": None}}
    assert writes() == []


def test_read_parses_every_device_and_hides_host_paths(api):
    c, cid = api
    STATE["cfg"] = cfg(vga="type=vmware,memory=32,clipboard=vnc", serial0="socket", serial1="/dev/ttyS0", audio0="device=AC97,driver=none",
                       rng0="source=/dev/urandom,max_bytes=2048,period=500", watchdog="model=i6300esb,action=reset")
    d = c.get(u(cid)).json()["devices"]
    assert d["vga"] == {"type": "vmware", "memory": 32, "clipboard": "vnc"}
    assert d["serial0"] == "socket" and d["serial1"] == "device" and "ttyS0" not in c.get(u(cid)).text
    assert d["audio"] == {"device": "AC97", "driver": "none"}
    assert d["rng"] == {"source": "/dev/urandom", "max_bytes": 2048, "period": 500}
    assert d["watchdog"] == {"model": "i6300esb", "action": "reset"}


def test_read_short_forms_and_garbage_are_tolerated(api):
    c, cid = api
    STATE["cfg"] = cfg(vga="std", rng0="/dev/urandom", watchdog="ib700", audio0="device=evil;rm", serial2="peu importe")
    d = c.get(u(cid)).json()["devices"]
    assert d["vga"]["type"] == "std" and d["rng"]["source"] == "/dev/urandom" and d["watchdog"]["model"] == "ib700"
    assert d["audio"]["device"] is None and d["serial2"] == "device"


def test_read_unknown_vga_type_is_not_trusted(api):
    c, cid = api
    STATE["cfg"] = cfg(vga="type=inconnu;x,memory=64")
    assert c.get(u(cid)).json()["devices"]["vga"]["type"] is None


def test_clear_list_is_bounded(api):
    c, cid = api
    assert patch(c, cid, clear=["vga"] * 12).status_code == 422 and not writes()
    assert patch(c, cid, clear=["vga"] * 11).status_code == 200


def test_read_rng_source_is_filtered(api):
    """Une source illisible ou piégée n'est jamais renvoyée telle quelle ; une source d'hôte normale l'est (lecture seule)."""
    c, cid = api
    STATE["cfg"] = cfg(rng0="source=/dev/../etc/passwd;x,max_bytes=5")
    assert c.get(u(cid)).json()["devices"]["rng"] == {"source": None, "max_bytes": 5, "period": None}
    STATE["cfg"] = cfg(rng0="source=/dev/hwrng")
    assert c.get(u(cid)).json()["devices"]["rng"]["source"] == "/dev/hwrng"


def test_read_pending_only_managed_keys(api):
    c, cid = api
    STATE["pending"] = [{"key": "vga", "value": "std", "pending": "vmware"}, {"key": "memory", "value": 256, "pending": 512},
                        {"key": "serial0", "delete": 1}, {"key": "args", "pending": "-x"}]
    r = c.get(u(cid)).json()
    assert [p["key"] for p in r["pending"]] == ["vga", "serial0"] and r["reboot_required"] is True


def test_read_invalid_path_params(api):
    c, cid = api
    assert c.get(u(cid, vmid=99)).status_code == 422 and c.get(u(cid, node="-x")).status_code == 422 and CALLS == []


# ------------------------------------------------------------------ écriture : réglages valides

def test_set_all_devices_exact_call_and_audit(api):
    c, cid = api
    r = patch(c, cid, vga={"type": "vmware", "memory": 32, "clipboard": "vnc"}, serial0="socket", serial3="socket", audio={"device": "ich9-intel-hda", "driver": "none"},
              rng={"max_bytes": 1024, "period": 1000}, watchdog={"model": "i6300esb", "action": "reset"}, inconnu=1, hookscript="x")
    assert r.status_code == 200
    assert r.json()["changed"] == ["audio0", "rng0", "serial0", "serial3", "vga", "watchdog"]
    assert writes()[0]["form"] == {
        "vga": "type=vmware,memory=32,clipboard=vnc", "serial0": "socket", "serial3": "socket", "audio0": "device=ich9-intel-hda,driver=none",
        "rng0": "source=/dev/urandom,max_bytes=1024,period=1000", "watchdog": "model=i6300esb,action=reset", "digest": DIGEST}
    last = audit(c)[0]
    assert (last["action"], last["status"]) == ("devices", "started") and "vga=type=vmware" in last["detail"] and SECRET not in last["detail"]


def test_minimal_forms(api):
    c, cid = api
    assert patch(c, cid, audio={"device": "AC97"}, watchdog={"model": "ib700"}, rng={}).status_code == 200
    f = writes()[0]["form"]
    assert (f["audio0"], f["watchdog"], f["rng0"]) == ("device=AC97", "model=ib700", "source=/dev/urandom")


def test_vga_merges_with_current_and_keeps_unknown_properties(api):
    c, cid = api
    STATE["cfg"] = cfg(vga="type=qxl,memory=64,xyz=1")
    assert patch(c, cid, vga={"memory": 128}).status_code == 200
    assert writes()[0]["form"]["vga"] == "type=qxl,memory=128,xyz=1"


def test_vga_short_form_is_rebuilt(api):
    c, cid = api
    STATE["cfg"] = cfg(vga="std")
    assert patch(c, cid, vga={"memory": 16}).status_code == 200
    assert writes()[0]["form"]["vga"] == "type=std,memory=16"


def test_vga_with_unreadable_extra_property_is_refused(api):
    c, cid = api
    STATE["cfg"] = cfg(vga="type=std,bad=a;b")
    assert patch(c, cid, vga={"memory": 16}).status_code == 422 and writes() == []


def test_rng_merge_keeps_current_values(api):
    c, cid = api
    STATE["cfg"] = cfg(rng0="source=/dev/urandom,max_bytes=2048,period=500")
    assert patch(c, cid, rng={"period": 900}).status_code == 200
    assert writes()[0]["form"]["rng0"] == "source=/dev/urandom,max_bytes=2048,period=900"


def test_clear_devices(api):
    c, cid = api
    r = patch(c, cid, clear=["serial1", "audio0", "serial1"])
    assert r.status_code == 200 and r.json()["removed"] == ["serial1", "audio0"]
    assert writes()[0]["form"] == {"delete": "serial1,audio0", "digest": DIGEST}


def test_digest_omitted_when_absent_or_malformed(api):
    c, cid = api
    STATE["cfg"] = {k: v for k, v in CFG0.items() if k != "digest"}
    assert patch(c, cid, watchdog={"model": "ib700"}).status_code == 200 and "digest" not in writes()[0]["form"]
    STATE["cfg"] = cfg(digest="pas-un-digest;rm")
    assert patch(c, cid, watchdog={"model": "ib700"}).status_code == 200 and "digest" not in writes()[1]["form"]


# ------------------------------------------------------------------ garde-fous

@pytest.mark.parametrize("body", [
    {"serial0": "/dev/ttyS0"}, {"serial0": "/dev/ttyUSB0"}, {"serial0": "SOCKET"}, {"serial0": ""},
    {"vga": {"type": "evil"}}, {"vga": {"type": "std;rm"}}, {"vga": {"memory": 3}}, {"vga": {"memory": 513}}, {"vga": {"memory": "32"}}, {"vga": {"memory": True}},
    {"vga": {"clipboard": "spice"}},
    {"audio": {"device": "evil"}}, {"audio": {"device": "AC97", "driver": "x"}}, {"audio": {}},
    {"rng": {"max_bytes": -1}}, {"rng": {"max_bytes": 1_000_001}}, {"rng": {"period": 0}}, {"rng": {"period": "5"}},
    {"watchdog": {"model": "evil"}}, {"watchdog": {"model": "ib700", "action": "format"}}, {"watchdog": {}},
    {"clear": ["hookscript"]}, {"clear": ["args"]}, {"clear": ["lock"]}, {"clear": ["scsi0"]}, {"clear": ["vga;x"]}, {"clear": "vga"},
    {"confirm": "true", "vga": {"type": "none"}},
])
def test_invalid_input_is_refused_422_without_any_call(api, body):
    c, cid = api
    r = patch(c, cid, **body)
    assert r.status_code == 422 and CALLS == [] and SECRET not in r.text


def test_rng_source_is_never_forwarded_even_if_sent(api):
    """`source` n'est pas un champ : /dev/hwrng est ignoré et la source reste /dev/urandom."""
    c, cid = api
    assert patch(c, cid, rng={"source": "/dev/hwrng", "period": 10}).status_code == 200
    assert writes()[0]["form"]["rng0"] == "source=/dev/urandom,period=10" and "hwrng" not in str(writes())


def test_empty_request_is_400(api):
    c, cid = api
    assert patch(c, cid).status_code == 400 and CALLS == []
    assert patch(c, cid, confirm=True).status_code == 400 and CALLS == []
    assert patch(c, cid, hookscript="x").status_code == 400 and CALLS == []


def test_set_and_clear_same_key_is_refused(api):
    c, cid = api
    r = patch(c, cid, watchdog={"model": "ib700"}, clear=["watchdog"])
    assert r.status_code == 422 and writes() == []
    r = patch(c, cid, serial0="socket", clear=["serial0"])
    assert r.status_code == 422 and writes() == []


def test_host_serial_device_cannot_be_overwritten_or_cleared(api):
    """Un port série posé par root sur un périphérique de l'hôte n'est ni réécrit ni retiré par Kaji."""
    c, cid = api
    STATE["cfg"] = cfg(serial0="/dev/ttyS0")
    assert patch(c, cid, serial0="socket").status_code == 422 and writes() == []
    assert patch(c, cid, clear=["serial0"]).status_code == 422 and writes() == []
    assert patch(c, cid, serial1="socket").status_code == 200                       # un autre port reste modifiable


def test_rng_on_host_source_cannot_be_rewritten_or_cleared(api):
    c, cid = api
    STATE["cfg"] = cfg(rng0="source=/dev/hwrng")
    assert patch(c, cid, rng={"period": 10}).status_code == 422 and writes() == []
    assert patch(c, cid, clear=["rng0"]).status_code == 422 and writes() == []


@pytest.mark.parametrize("vga", ["none", "serial0", "serial2"])
def test_vga_none_or_serial_needs_confirmation_decided_by_server(api, vga):
    c, cid = api
    r = patch(c, cid, vga={"type": vga})
    assert r.status_code == 400 and r.json()["detail"].startswith("Confirmation requise (renvoie la requête avec confirm=true) : ") and writes() == []
    assert patch(c, cid, vga={"type": vga}, confirm=True).status_code == 200 and "type=" + vga in writes()[0]["form"]["vga"]


def test_confirmation_not_needed_when_already_none_or_for_normal_types(api):
    c, cid = api
    assert patch(c, cid, vga={"type": "std"}).status_code == 200
    STATE["cfg"] = cfg(vga="type=none")
    assert patch(c, cid, vga={"type": "none", "memory": 16}).status_code == 200


def test_protected_vmid_refuses_every_change_even_confirmed(api, monkeypatch):
    c, cid = api
    monkeypatch.setattr("app.routers.devices.get_settings", lambda: type("S", (), {"protected_vmids": {115}})())
    for body in ({"watchdog": {"model": "ib700"}}, {"clear": ["vga"]}, {"vga": {"type": "std"}, "confirm": True}):
        assert patch(c, cid, **body).status_code == 409
    assert CALLS == []
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("devices", "error")
    assert c.get(u(cid)).status_code == 200                                         # la lecture reste permise


def test_unreadable_config_is_502_and_nothing_written(api):
    c, cid = api
    STATE["cfg"] = ["pas", "un", "dict"]
    assert patch(c, cid, watchdog={"model": "ib700"}).status_code == 502 and writes() == []


@pytest.mark.parametrize("code", [403, 500])
def test_proxmox_error_is_translated_audited_without_leak(api, code):
    c, cid = api
    STATE["fail"] = ("PUT", "/nodes/enzo/qemu/115/config", code)
    r = patch(c, cid, watchdog={"model": "ib700"})
    assert r.status_code == 502 and SECRET not in r.text and "10.0.0.5" not in r.text
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("devices", "error") and SECRET not in c.get("/api/audit").text


def test_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    patch(c, cid, watchdog={"model": "ib700"})                                      # succès
    patch(c, cid)                                                                   # rien à faire
    patch(c, cid, vga={"type": "none"})                                             # confirmation requise
    STATE["fail"] = ("PUT", "/nodes/enzo/qemu/115/config", 500)
    patch(c, cid, serial0="socket")                                                 # erreur Proxmox
    log = audit(c)[::-1]
    assert [(e["action"], e["status"], e["target"]) for e in log] == [("devices", s, "qemu/115@enzo") for s in ("started", "error", "error", "error")]
    assert "Confirmation requise" in log[2]["detail"] and SECRET not in c.get("/api/audit").text


def test_build_params_is_pure_and_ignores_unknown_fields():
    p, d = build_params(DevicesUpdate.model_validate({"watchdog": {"model": "ib700"}, "inconnu": 1}), {})
    assert p == {"watchdog": "model=ib700"} and d == []
