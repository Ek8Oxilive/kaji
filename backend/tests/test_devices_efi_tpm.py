"""BIOS, disque EFI et TPM d'une VM (lot #268) : faux Proxmox STRICT (méthode, chemin, paramètres et formats exacts ; 400 sinon).

Les formats (`efidisk0=STOCKAGE:1,efitype=4m,pre-enrolled-keys=1`, `tpmstate0=STOCKAGE:1,version=v2.0`) sont ceux que Kaji utilise déjà à la création
d'une VM UEFI. AJOUT seulement si absent ; retrait avec confirmation.
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import get_settings
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "b" * 40
ALLOWED = {"bios", "efidisk0", "tpmstate0", "delete", "digest"}
FORMATS = {
    "bios": re.compile(r"^(seabios|ovmf)$"),
    "efidisk0": re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,39}:1,efitype=(2m|4m)(,pre-enrolled-keys=1)?$"),
    "tpmstate0": re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,39}:1,version=(v1\.2|v2\.0)$"),
}
CFG0 = {"name": "kaji-sandbox", "digest": DIGEST, "memory": 256}
CALLS: list[dict] = []
STATE: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
    CALLS.append({"method": request.method, "path": p, "form": form})
    if request.method == "GET" and p == "/nodes/enzo/qemu/115/config":
        return httpx.Response(200, json={"data": STATE.get("cfg", CFG0)})
    if request.method == "GET" and p == "/nodes/enzo/qemu/115/pending":
        return httpx.Response(200, json={"data": STATE.get("pending", [])})
    if request.method == "PUT" and p == "/nodes/enzo/qemu/115/config":
        if set(form) - ALLOWED:
            return httpx.Response(400, json={"data": None})
        for k, rx in FORMATS.items():
            if k in form and not rx.fullmatch(form[k]):
                return httpx.Response(400, json={"data": None})
        if set(filter(None, form.get("delete", "").split(","))) - {"bios", "efidisk0", "tpmstate0"}:
            return httpx.Response(400, json={"data": None})
        if STATE.get("fail"):
            return httpx.Response(403, json={"data": None, "message": SECRET})
        return httpx.Response(200, json={"data": None})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.delenv("KAJI_PROTECTED_VMIDS", raising=False)
    get_settings.cache_clear()
    CALLS.clear()
    STATE.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()
    monkeypatch.undo()
    get_settings.cache_clear()


def u(cid):
    return f"/api/connections/{cid}/guests/enzo/qemu/115/devices"


def patch(c, cid, **b):
    return c.patch(u(cid), json=b)


def writes():
    return [x for x in CALLS if x["method"] != "GET"]


def cfg(**kw):
    return {**CFG0, **kw}


# --- lecture ----------------------------------------------------------------------------------------------------------------------------------------

def test_read_bios_efidisk_and_tpm_without_leaking_volume_names(api):
    c, cid = api
    STATE["cfg"] = cfg(bios="ovmf", efidisk0="local-lvm:vm-115-disk-1,efitype=4m,pre-enrolled-keys=1,size=4M", tpmstate0="local-lvm:vm-115-disk-2,size=4M,version=v2.0")
    r = c.get(u(cid))
    d = r.json()["devices"]
    assert d["bios"] == "ovmf"
    assert d["efidisk"] == {"storage": "local-lvm", "efitype": "4m", "pre_enrolled_keys": True}
    assert d["tpm"] == {"storage": "local-lvm", "version": "v2.0"}
    assert "vm-115-disk" not in r.text                                              # le nom du volume n'est pas renvoyé


def test_read_garbage_is_tolerated(api):
    c, cid = api
    STATE["cfg"] = cfg(bios="uefi;x", efidisk0="n'importe quoi", tpmstate0="local:1,version=v9")
    d = c.get(u(cid)).json()["devices"]
    assert d["bios"] is None and d["efidisk"] == {"storage": None, "efitype": None, "pre_enrolled_keys": False} and d["tpm"] == {"storage": "local", "version": None}


def test_read_unknown_efitype_and_unreadable_storage_are_not_trusted(api):
    c, cid = api
    STATE["cfg"] = cfg(efidisk0="local:1,efitype=9m", tpmstate0="a b;c:vol,version=v2.0")
    d = c.get(u(cid)).json()["devices"]
    assert d["efidisk"]["efitype"] is None and d["efidisk"]["storage"] == "local"
    assert d["tpm"]["storage"] is None and d["tpm"]["version"] == "v2.0"


def test_pending_lists_the_new_keys_only_when_managed(api):
    c, cid = api
    STATE["pending"] = [{"key": "efidisk0", "pending": "local-lvm:1,efitype=4m"}, {"key": "bios", "value": "seabios", "pending": "ovmf"},
                        {"key": "tpmstate0", "delete": 1}, {"key": "memory", "pending": 512}]
    j = c.get(u(cid)).json()
    assert [p["key"] for p in j["pending"]] == ["efidisk0", "bios", "tpmstate0"] and j["reboot_required"] is True


# --- ajout ------------------------------------------------------------------------------------------------------------------------------------------

def test_add_efidisk_exact_param_defaults_and_options(api):
    c, cid = api
    assert patch(c, cid, efidisk={"storage": "local-lvm"}).status_code == 200
    assert writes()[-1]["form"] == {"efidisk0": "local-lvm:1,efitype=4m", "digest": DIGEST}
    assert patch(c, cid, efidisk={"storage": "fast", "efitype": "2m", "pre_enrolled_keys": True}).status_code == 200
    assert writes()[-1]["form"]["efidisk0"] == "fast:1,efitype=2m,pre-enrolled-keys=1"


def test_add_tpm_exact_param_and_versions(api):
    c, cid = api
    assert patch(c, cid, tpm={"storage": "local-lvm"}).status_code == 200
    assert writes()[-1]["form"]["tpmstate0"] == "local-lvm:1,version=v2.0"
    assert patch(c, cid, tpm={"storage": "local-lvm", "version": "v1.2"}).status_code == 200
    assert writes()[-1]["form"]["tpmstate0"] == "local-lvm:1,version=v1.2"


def test_existing_efidisk_or_tpm_is_never_replaced(api):
    c, cid = api
    STATE["cfg"] = cfg(efidisk0="local-lvm:vm-115-disk-1,efitype=4m", tpmstate0="local-lvm:vm-115-disk-2,version=v2.0")
    r = patch(c, cid, efidisk={"storage": "local-lvm"})
    assert r.status_code == 422 and "existe déjà" in r.json()["detail"]
    assert patch(c, cid, tpm={"storage": "local-lvm"}).status_code == 422
    assert not writes()


@pytest.mark.parametrize("body", [
    {"efidisk": {"storage": ""}}, {"efidisk": {"storage": "a:b"}}, {"efidisk": {"storage": "x;y"}}, {"efidisk": {"storage": "a,b=1"}}, {"efidisk": {"storage": "x" * 41}},
    {"efidisk": {"storage": "-a"}}, {"efidisk": {"storage": "ok", "efitype": "8m"}}, {"efidisk": {"storage": "ok", "pre_enrolled_keys": "yes"}}, {"efidisk": {}},
    {"tpm": {"storage": "a b"}}, {"tpm": {"storage": "ok", "version": "v3"}}, {"tpm": {"storage": "ok", "version": "2.0"}}, {"tpm": {"version": "v2.0"}},
    {"bios": "uefi"}, {"bios": "OVMF"}, {"bios": ""},
])
def test_invalid_input_is_refused_without_any_write(api, body):
    c, cid = api
    assert patch(c, cid, **body).status_code == 422 and not writes()


# --- BIOS et confirmations ---------------------------------------------------------------------------------------------------------------------------

def test_changing_bios_needs_confirmation_but_not_when_unchanged(api):
    c, cid = api
    r = patch(c, cid, bios="ovmf")
    assert r.status_code == 400 and "Confirmation requise" in r.json()["detail"] and "bios=ovmf" in r.json()["detail"] and not writes()
    assert patch(c, cid, bios="ovmf", confirm=True).status_code == 200 and writes()[-1]["form"]["bios"] == "ovmf"
    CALLS.clear()
    assert patch(c, cid, bios="seabios").status_code == 200                       # seabios = défaut : aucun changement, pas de confirmation
    STATE["cfg"] = cfg(bios="ovmf")
    assert patch(c, cid, bios="ovmf").status_code == 200                          # déjà ovmf
    assert patch(c, cid, bios="seabios").status_code == 400                       # ovmf -> seabios : confirmation


def test_removing_efidisk_tpm_or_ovmf_needs_confirmation(api):
    c, cid = api
    STATE["cfg"] = cfg(bios="ovmf", efidisk0="local-lvm:vm-115-disk-1,efitype=4m", tpmstate0="local-lvm:vm-115-disk-2,version=v2.0")
    for key in ("efidisk0", "tpmstate0", "bios"):
        r = patch(c, cid, clear=[key])
        assert r.status_code == 400 and "Confirmation requise" in r.json()["detail"], key
    assert not writes()
    assert patch(c, cid, clear=["efidisk0", "tpmstate0"], confirm=True).status_code == 200
    assert writes()[-1]["form"]["delete"] == "efidisk0,tpmstate0"
    assert "non utilisé" in patch(c, cid, clear=["efidisk0"]).json()["detail"]


def test_removing_what_is_absent_needs_no_confirmation(api):
    c, cid = api
    assert patch(c, cid, clear=["efidisk0", "tpmstate0", "bios"]).status_code == 200
    assert writes()[-1]["form"]["delete"] == "efidisk0,tpmstate0,bios"


def test_added_and_cleared_at_once_is_refused(api):
    c, cid = api
    assert patch(c, cid, efidisk={"storage": "local-lvm"}, clear=["efidisk0"]).status_code == 422
    assert patch(c, cid, tpm={"storage": "local-lvm"}, clear=["tpmstate0"]).status_code == 422
    assert patch(c, cid, bios="ovmf", clear=["bios"], confirm=True).status_code == 422
    assert not writes()


# --- garde-fous communs ------------------------------------------------------------------------------------------------------------------------------

def test_protected_machine_is_refused(api, monkeypatch):
    c, cid = api
    monkeypatch.setenv("KAJI_PROTECTED_VMIDS", "115")
    get_settings.cache_clear()
    for body in ({"efidisk": {"storage": "local-lvm"}}, {"tpm": {"storage": "local-lvm"}}, {"bios": "ovmf", "confirm": True}, {"clear": ["efidisk0"], "confirm": True}):
        assert patch(c, cid, **body).status_code == 409
    assert not writes()


def test_proxmox_refusal_is_audited_and_leaks_no_secret(api):
    c, cid = api
    STATE["fail"] = True
    r = patch(c, cid, tpm={"storage": "local-lvm"})
    assert r.status_code >= 400 and SECRET not in r.text
    log = c.get("/api/audit")
    assert SECRET not in log.text and ("devices", "error") in {(a["action"], a["status"]) for a in log.json()}


def test_success_is_audited(api):
    c, cid = api
    assert patch(c, cid, efidisk={"storage": "local-lvm"}).status_code == 200
    log = c.get("/api/audit").json()
    assert any(a["action"] == "devices" and a["status"] == "started" and "efidisk0" in (a["detail"] or "") for a in log)


def test_unknown_fields_are_ignored_and_never_sent(api):
    c, cid = api
    assert patch(c, cid, efidisk={"storage": "local-lvm", "size": "9999", "path": "/dev/sda"}, bridge="vmbr0", args="-x").status_code == 200
    assert set(writes()[-1]["form"]) == {"efidisk0", "digest"}
