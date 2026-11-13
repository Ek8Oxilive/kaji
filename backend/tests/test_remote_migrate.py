"""Migration distante (lot #390) : faux Proxmox STRICT (`remote_migrate` de qemu et lxc : clés autorisées, `target-endpoint` au format du schéma, correspondances validées).

RIEN de ce fichier n'a tourné sur un vrai cluster : un seul cluster, et la fonction est « EXPERIMENTAL » chez Proxmox.
"""
import re
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.remotemigrate import RemoteMigrate, check_pairs, clean_error

PWD = "un-mot-de-passe-solide"
PERM_SECRET = "s3cr3t-value-xyz"
REMOTE_SECRET = "5f1c2d3e-4a5b-4c6d-8e7f-90a1b2c3d4e5"
FP = ":".join(f"{i:02X}" for i in range(32))
BODY_CONN = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": PERM_SECRET}
UPID = "UPID:enzo:000A1B2C:00D3E4F5:6735A8C0:qmigrate:115:kaji@pve!kaji:"
WRITES: list[tuple[str, str, dict]] = []
ST: dict = {}
PHRASE = "COUPURE POSSIBLE"
ENDPOINT = re.compile(r"apitoken=PVEAPIToken=[A-Za-z0-9._\-]+@[A-Za-z][A-Za-z0-9._\-]*![A-Za-z][A-Za-z0-9._\-]*=[0-9a-f\-]{36},host=[A-Za-z0-9.\-]+,fingerprint=([0-9A-F]{2}:){31}[0-9A-F]{2}(,port=[0-9]+)?")
PAIRS = re.compile(r"1|[A-Za-z0-9_\-]+|[A-Za-z0-9_\-]+:[A-Za-z0-9_\-]+(,[A-Za-z0-9_\-]+:[A-Za-z0-9_\-]+)*")
KEYS = {"qemu": {"target-endpoint", "target-storage", "target-bridge", "target-vmid", "online", "bwlimit", "delete"},
        "lxc": {"target-endpoint", "target-storage", "target-bridge", "target-vmid", "online", "restart", "timeout", "bwlimit", "delete"}}


def fresh():
    ST.clear()
    ST.update(status="stopped", name="kaji-sandbox", echo=False, fail=False, missing=False)


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    mm = re.fullmatch(r"/nodes/([^/]+)/(qemu|lxc)/([0-9]+)/(status/current|remote_migrate)", p)
    if not mm:
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    _, gtype, vmid, what = mm.groups()
    if what == "status/current" and request.method == "GET":
        if ST["missing"]:
            return httpx.Response(500, json={"data": None, "message": "Configuration file does not exist"})
        if ST.get("null"):
            return httpx.Response(200, json={"data": None})                 # réponse vide : l'état de la machine est inconnu
        return httpx.Response(200, json={"data": {"status": ST["status"], "name": ST["name"]}})
    if what == "remote_migrate" and request.method == "POST":
        extra = set(body) - KEYS[gtype]
        if extra or {"target-endpoint", "target-storage", "target-bridge"} - set(body):
            return httpx.Response(400, json={"data": None, "message": f"paramètres refusés ou manquants {sorted(extra)}"})
        if not ENDPOINT.fullmatch(body["target-endpoint"]) or not PAIRS.fullmatch(body["target-storage"]) or not PAIRS.fullmatch(body["target-bridge"]):
            return httpx.Response(400, json={"data": None, "message": "format invalide"})
        if ST["echo"]:                                                  # le vrai Proxmox met l'erreur dans la LIGNE D'ÉTAT HTTP (constaté avec les webhooks) : on y recopie le paramètre
            return httpx.Response(500, json={"data": None}, extensions={"reason_phrase": f"Value '{body['target-endpoint']}' is invalid".encode()})
        if ST["fail"]:
            return httpx.Response(403, json={"data": None, "message": PERM_SECRET})
        WRITES.append((request.method, p, body))
        return httpx.Response(200, json={"data": UPID})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client):
    WRITES.clear(); fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY_CONN).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, gtype="qemu", vmid=115, node="enzo"):
    return f"/api/connections/{cid}/guests/{node}/{gtype}/{vmid}/remote-migrate"


OK = {"target_host": "pve.autre.example.org", "target_token_id": "migrate@pve!kaji", "target_secret": REMOTE_SECRET, "target_fingerprint": FP.lower(),
      "target_storage": "local-lvm", "target_bridge": "vmbr0", "confirm": True}


def go(c, cid, gtype="qemu", vmid=115, **over):
    return c.post(u(cid, gtype, vmid), json={k: v for k, v in {**OK, **over}.items() if v is not None})


def audit_text(c):
    return c.get("/api/audit").text


def no_secret(*texts):
    return all(s not in t for t in texts for s in (REMOTE_SECRET, PERM_SECRET, PWD, "apitoken=", "PVEAPIToken"))


# ---------------------------------------------------------------- migration
def test_stopped_vm_exact_params_and_nothing_secret_back(api):
    c, cid = api
    r = go(c, cid, target_port=8007, target_vmid=900, bwlimit=10240)
    assert r.status_code == 202, r.text
    assert WRITES == [("POST", "/nodes/enzo/qemu/115/remote_migrate", {"target-endpoint": f"apitoken=PVEAPIToken=migrate@pve!kaji={REMOTE_SECRET},host=pve.autre.example.org,fingerprint={FP},port=8007",
                                                                       "target-storage": "local-lvm", "target-bridge": "vmbr0", "target-vmid": "900", "bwlimit": "10240"})]
    assert r.json() == {"upid": UPID, "node": "enzo", "target_host": "pve.autre.example.org"} and no_secret(r.text, audit_text(c))
    log = audit_text(c)
    assert "pve.autre.example.org:8007" in log and "00:01:02:03" in log and "remote-migrate" in log


def test_fingerprint_is_normalized_to_upper_case(api):
    c, cid = api
    assert go(c, cid, target_fingerprint=FP.lower()).status_code == 202 and f"fingerprint={FP}" in WRITES[-1][2]["target-endpoint"]


def test_running_vm_needs_online(api):
    c, cid = api
    ST["status"] = "running"
    r = go(c, cid)
    assert r.status_code == 422 and "à chaud" in r.json()["detail"] and not WRITES
    assert go(c, cid, online=True).status_code == 202 and WRITES[-1][2]["online"] == "1"


def test_running_container_needs_restart_or_online_and_restart_timeout_are_container_only(api):
    c, cid = api
    ST["status"] = "running"
    assert go(c, cid, "lxc").status_code == 422 and not WRITES
    assert go(c, cid, "lxc", restart=True, timeout=60).status_code == 202 and WRITES[-1][2]["restart"] == "1" and WRITES[-1][2]["timeout"] == "60"
    assert go(c, cid, "lxc", online=True).status_code == 202
    ST["status"] = "stopped"
    for over in ({"restart": True}, {"timeout": 60}):
        n = len(WRITES)
        assert go(c, cid, "qemu", **over).status_code == 422 and len(WRITES) == n


def test_confirm_is_required_but_not_for_a_dry_run(api):
    c, cid = api
    r = go(c, cid, confirm=False)
    assert r.status_code == 400 and not WRITES
    assert ("remote-migrate", "error") in [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


def test_dry_run_reports_everything_masks_the_token_and_writes_nothing(api):
    c, cid = api
    ST["status"] = "running"
    r = go(c, cid, confirm=False, dry_run=True, online=True, delete=True)
    j = r.json()
    assert r.status_code == 202 and j["dry_run"] is True and j["running"] is True and j["name"] == "kaji-sandbox" and not WRITES
    assert j["target"] == {"host": "pve.autre.example.org", "port": None, "token_id": "migrate@pve!kaji", "fingerprint": FP} and j["params"]["target-endpoint"] == "défini (jeton masqué)"
    assert j["locks"] == {"delete": True, "cut": True, "running": True} and no_secret(r.text)


def test_delete_needs_the_exact_name_retyped_and_the_phrase(api):
    c, cid = api
    assert go(c, cid, delete=True).status_code == 400 and go(c, cid, delete=True, type_name="autre").status_code == 400 and not WRITES
    r = go(c, cid, delete=True, type_name="kaji-sandbox")
    assert r.status_code == 409 and "données seront perdues" in r.json()["detail"] and not WRITES
    assert go(c, cid, delete=True, type_name="kaji-sandbox", acknowledge_cut_access=True).status_code == 409
    assert go(c, cid, delete=True, type_name="kaji-sandbox", phrase=PHRASE).status_code == 409
    assert go(c, cid, delete=True, type_name="kaji-sandbox", acknowledge_cut_access=True, phrase="coupure possible").status_code == 409
    r = go(c, cid, delete=True, type_name="kaji-sandbox", acknowledge_cut_access=True, phrase=PHRASE)
    assert r.status_code == 202 and WRITES[-1][2]["delete"] == "1" and "ORIGINAL SUPPRIMÉ" in audit_text(c)


def test_delete_false_never_sends_delete(api):
    c, cid = api
    assert go(c, cid, delete=False).status_code == 202 and "delete" not in WRITES[-1][2]


def test_a_protected_machine_never_migrates(api, monkeypatch):
    c, cid = api
    monkeypatch.setattr("app.routers.remote_migrate.get_settings", lambda: SimpleNamespace(protected_vmids={116}))
    r = go(c, cid, "lxc", 116)
    assert r.status_code == 409 and "protégée" in r.json()["detail"] and not WRITES
    assert go(c, cid, "lxc", 116, dry_run=True).status_code == 409


def test_a_machine_without_a_name_uses_its_id_for_the_retyped_name(api):
    c, cid = api
    ST["name"] = None
    assert go(c, cid, delete=True, type_name="115", acknowledge_cut_access=True, phrase=PHRASE).status_code == 202


def test_an_empty_state_from_proxmox_is_a_404_not_a_crash(api):
    c, cid = api
    ST["null"] = True
    r = go(c, cid)
    assert r.status_code == 404 and "introuvable" in r.json()["detail"] and not WRITES


def test_unknown_machine_is_an_error_without_a_write(api):
    c, cid = api
    ST["missing"] = True
    assert go(c, cid).status_code in (404, 502) and not WRITES


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize("over", [
    {"target_host": "127.0.0.1"}, {"target_host": "localhost"}, {"target_host": "x.localhost"}, {"target_host": "0.0.0.0"}, {"target_host": "169.254.1.1"}, {"target_host": ""}, {"target_host": "a b"},
    {"target_host": "a,host=evil"}, {"target_host": "a/b"}, {"target_host": "x" * 254},
    {"target_port": 0}, {"target_port": 70000}, {"target_port": "8006"}, {"target_port": True}, {"target_port": 1.5},
    {"target_token_id": "migrate@pve"}, {"target_token_id": "migrate@pvekaji"}, {"target_token_id": "migrate!kaji"}, {"target_token_id": "a b@pve!x"}, {"target_token_id": "m@pve!x,host=evil"}, {"target_token_id": "m@pve!1x"}, {"target_token_id": ""},
    {"target_secret": "pas-un-uuid"}, {"target_secret": REMOTE_SECRET + "x"}, {"target_secret": REMOTE_SECRET.replace("-", "")}, {"target_secret": ""}, {"target_secret": REMOTE_SECRET + ",host=x"},
    {"target_fingerprint": FP[:-3]}, {"target_fingerprint": FP.replace(":", "")}, {"target_fingerprint": "ZZ:" + FP[3:]}, {"target_fingerprint": ""}, {"target_fingerprint": FP + ",port=1"},
    {"target_storage": ""}, {"target_storage": "../x"}, {"target_storage": "a:b:c"}, {"target_storage": "a,b"}, {"target_storage": "a:b,c"}, {"target_storage": ",a:b"}, {"target_storage": ",".join(["a:b"] * 21)},
    {"target_storage": "a b"}, {"target_storage": "a:b,host=evil"},
    {"target_bridge": ""}, {"target_bridge": "vm br"}, {"target_bridge": "a:b:c"}, {"target_bridge": "a,b"}, {"target_bridge": "x" * 16}, {"target_bridge": "vmbr0:"},
    {"target_vmid": 99}, {"target_vmid": 1_000_000_000}, {"target_vmid": True}, {"target_vmid": "900"},
    {"bwlimit": -1}, {"bwlimit": 1_000_000_001}, {"bwlimit": "1"}, {"timeout": 0}, {"timeout": 3601},
    {"online": "oui"}, {"delete": "true"}, {"delete": 1}, {"confirm": "true"}, {"dry_run": "x"},
])
def test_values_are_validated_before_anything_is_sent(api, over):
    c, cid = api
    assert go(c, cid, **over).status_code == 422 and not WRITES


@pytest.mark.parametrize("missing", ["target_host", "target_token_id", "target_secret", "target_fingerprint", "target_storage", "target_bridge"])
def test_every_connection_and_mapping_field_is_required_notably_the_fingerprint(api, missing):
    c, cid = api
    assert go(c, cid, **{missing: None}).status_code == 422 and not WRITES


@pytest.mark.parametrize("storage", ["local-lvm", "1", "local-lvm:ceph", "a:b,c:d", "src_1:dst-2"])
def test_valid_mappings_are_accepted(api, storage):
    c, cid = api
    assert go(c, cid, target_storage=storage, target_bridge=storage if ":" not in storage else "vmbr0:vmbr1").status_code == 202


def test_the_mapping_helper_directly():
    from app.hardware import BRIDGE
    assert check_pairs("1", BRIDGE, "ponts") == "1" and check_pairs("vmbr0:vmbr1,vmbr2:vmbr3", BRIDGE, "ponts")
    for bad in ("", "a:b:c", "a,b", ":a", "a:"):
        with pytest.raises(ValueError):
            check_pairs(bad, BRIDGE, "ponts")


# ---------------------------------------------------------------- erreurs et secrets
def test_proxmox_error_that_echoes_the_endpoint_never_leaks_the_token(api):
    c, cid = api
    ST["echo"] = True
    r = go(c, cid)
    assert r.status_code in (500, 502) and no_secret(r.text, audit_text(c)) and "détail masqué" in r.json()["detail"]


def test_a_harmless_proxmox_error_still_reaches_the_user(api):
    c, cid = api
    ST["fail"] = True
    r = go(c, cid)
    assert no_secret(r.text, audit_text(c)) and r.status_code in (403, 502)


def test_the_error_cleaner_directly():
    body = RemoteMigrate(**{k: v for k, v in OK.items() if k != "confirm"})
    assert REMOTE_SECRET not in clean_error(f"jeton {REMOTE_SECRET} refusé", body) and "détail masqué" in clean_error("apitoken=PVEAPIToken=x", body)
    assert clean_error("pas de place sur le stockage", body) == "pas de place sur le stockage"


def test_the_token_never_appears_in_the_request_repr_or_logs(api):
    body = RemoteMigrate(**{k: v for k, v in OK.items() if k != "confirm"})
    assert REMOTE_SECRET not in repr(body) and REMOTE_SECRET not in str(body) and REMOTE_SECRET not in body.model_dump_json()


def test_requires_a_session(client):
    assert client.post(u(1), json=OK).status_code == 401
