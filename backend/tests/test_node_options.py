import re
from urllib.parse import parse_qs

import httpx
import pytest

from app import nodeoptspec as N
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
D1, D2 = "a1" * 20, "b2" * 20
MAC = "aa:bb:cc:dd:ee:ff"
SEEN: list[httpx.Request] = []
WRITES: list[dict] = []
ST: dict = {}
WOL_RX = re.compile(r"^mac=([0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5})(,bind-interface=[A-Za-z][A-Za-z0-9._-]{0,15})?(,broadcast-address=\d{1,3}(\.\d{1,3}){3})?$")


def fresh():
    ST.clear()
    ST["cfg"] = {"description": "notes du nœud", "acme": "account=default", "digest": D1}
    ST["flags"] = {}


def _bad(msg="Parameter verification failed."):
    return httpx.Response(400, json={"data": None, "message": msg})


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if p != "/nodes/enzo/config":
        return httpx.Response(404, json={"data": None, "message": "nœud inconnu"})
    if request.method == "GET":
        if ST["flags"].get("down"):
            return httpx.Response(500, json={"data": None, "message": SECRET})
        return httpx.Response(200, json={"data": dict(ST["cfg"])})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if ST["flags"].get("forbidden"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    if set(body) - {"wakeonlan", "startall-onboot-delay", "ballooning-target", "delete", "digest"}:
        return _bad("clé inconnue")
    if body.get("digest") not in (None, ST["cfg"].get("digest")):
        return _bad("detected modified configuration - file changed by other user! Try again.")
    if "wakeonlan" in body and not WOL_RX.fullmatch(body["wakeonlan"]):
        return _bad("wakeonlan : format")
    if "startall-onboot-delay" in body and not (body["startall-onboot-delay"].isdigit() and 0 <= int(body["startall-onboot-delay"]) <= 300):
        return _bad("startall-onboot-delay : bornes")
    if "ballooning-target" in body and not (body["ballooning-target"].isdigit() and 0 <= int(body["ballooning-target"]) <= 100):
        return _bad("ballooning-target : bornes")
    dele = body.get("delete", "").split(",") if body.get("delete") else []
    if set(dele) - {"wakeonlan", "startall-onboot-delay", "ballooning-target", "description", "acme"}:
        return _bad("delete : option inconnue")
    WRITES.append(body)
    if not ST["flags"].get("noapply"):
        skip = set(ST["flags"].get("noapply_keys", ()))                            # Proxmox qui « oublie » seulement ces options
        for k in ("wakeonlan", "startall-onboot-delay", "ballooning-target"):
            if k in body and k not in skip:
                ST["cfg"][k] = int(body[k]) if body[k].isdigit() and k != "wakeonlan" else body[k]
        for k in dele:
            if k not in skip:
                ST["cfg"].pop(k, None)
        ST["cfg"]["digest"] = D2
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    SEEN.clear(); WRITES.clear(); fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, node="enzo"):
    return f"/api/connections/{cid}/nodes/{node}/options"


def put(c, cid, **body):
    return c.put(u(cid), json={"digest": D1, "confirm": True, **body})


def audit_text(c):
    return c.get("/api/audit").text


# ------------------------------------------------------------------ lecture
def test_read_shapes_the_options_and_never_touches_notes(api):
    c, cid = api
    ST["cfg"].update({"wakeonlan": f"mac={MAC},bind-interface=vmbr0", "startall-onboot-delay": 30, "ballooning-target": 70})
    j = c.get(u(cid)).json()
    assert j["wakeonlan"] == {"mac": MAC, "bind_interface": "vmbr0", "broadcast_address": None} and j["wakeonlan_readable"] is True
    assert j["startall_onboot_delay"] == 30 and j["ballooning_target"] == 70 and j["digest"] == D1 and "notes" not in j and "description" not in j


def test_read_bare_mac_form_and_unreadable_values(api):
    c, cid = api
    ST["cfg"]["wakeonlan"] = MAC
    assert c.get(u(cid)).json()["wakeonlan"]["mac"] == MAC
    for bad in ("zz", "mac=zz", f"{MAC},{MAC}", f"mac={MAC},x=1", f"mac={MAC},broadcast-address=1.2.3", f"mac={MAC},bind-interface=1x", f"mac={MAC},mac={MAC}", "x" * 300):
        ST["cfg"]["wakeonlan"] = bad
        j = c.get(u(cid)).json()
        assert j["wakeonlan"] is None and j["wakeonlan_readable"] is False, bad


def test_read_error_does_not_leak(api):
    c, cid = api
    ST["flags"]["down"] = True
    r = c.get(u(cid))
    assert r.status_code >= 400 and SECRET not in r.text


# ------------------------------------------------------------------ écriture
def test_dry_run_writes_nothing_and_shows_the_params(api):
    c, cid = api
    r = put(c, cid, wakeonlan_mac=MAC, dry_run=True, confirm=False)
    assert r.status_code == 200 and r.json() == {"dry_run": True, "params": {"wakeonlan": f"mac={MAC}"}} and not WRITES


def test_write_requires_confirm_and_digest(api):
    c, cid = api
    assert c.put(u(cid), json={"digest": D1, "wakeonlan_mac": MAC}).status_code == 400
    assert c.put(u(cid), json={"confirm": True, "wakeonlan_mac": MAC}).status_code == 400
    assert not WRITES


def test_stale_digest_is_a_409_without_writing(api):
    c, cid = api
    r = c.put(u(cid), json={"digest": D2, "confirm": True, "wakeonlan_mac": MAC})
    assert r.status_code == 409 and not WRITES


def test_wakeonlan_write_sends_only_what_is_asked_and_reads_back(api):
    c, cid = api
    r = put(c, cid, wakeonlan_mac=MAC, wakeonlan_bind_interface="vmbr0", wakeonlan_broadcast_address="192.168.1.255")
    assert r.status_code == 200
    assert WRITES == [{"wakeonlan": f"mac={MAC},bind-interface=vmbr0,broadcast-address=192.168.1.255", "digest": D1}]
    assert r.json()["wakeonlan"] == {"mac": MAC, "bind_interface": "vmbr0", "broadcast_address": "192.168.1.255"}
    assert ST["cfg"]["description"] == "notes du nœud" and ST["cfg"]["acme"] == "account=default"       # notes et ACME intacts


def test_wakeonlan_partial_update_merges_with_the_current_value(api):
    c, cid = api
    ST["cfg"]["wakeonlan"] = f"mac={MAC},bind-interface=vmbr0"
    assert put(c, cid, wakeonlan_broadcast_address="10.0.0.255").status_code == 200
    assert WRITES[-1]["wakeonlan"] == f"mac={MAC},bind-interface=vmbr0,broadcast-address=10.0.0.255"


def test_wakeonlan_needs_a_mac(api):
    c, cid = api
    r = put(c, cid, wakeonlan_bind_interface="vmbr0")
    assert r.status_code == 422 and "MAC" in r.json()["detail"] and not WRITES


def test_unreadable_current_wakeonlan_refuses_to_overwrite(api):
    c, cid = api
    ST["cfg"]["wakeonlan"] = f"mac={MAC},futur=1"
    r = put(c, cid, wakeonlan_mac="11:22:33:44:55:66")
    assert r.status_code == 422 and "pas lisible" in r.json()["detail"] and not WRITES
    assert put(c, cid, ballooning_target=60).status_code == 200            # les autres options restent modifiables


def test_numbers_and_clear(api):
    c, cid = api
    ST["cfg"].update({"wakeonlan": f"mac={MAC}", "ballooning-target": 50})
    assert put(c, cid, startall_onboot_delay=45, clear=["wakeonlan", "ballooning-target"]).status_code == 200
    assert WRITES[-1] == {"startall-onboot-delay": "45", "delete": "wakeonlan,ballooning-target", "digest": D1}
    cfg = ST["cfg"]
    assert cfg["startall-onboot-delay"] == 45 and "wakeonlan" not in cfg and "ballooning-target" not in cfg


@pytest.mark.parametrize("body", [
    {"wakeonlan_mac": "zz:zz:zz:zz:zz:zz"}, {"wakeonlan_mac": MAC + "\n"}, {"wakeonlan_mac": "aabbccddeeff"}, {"wakeonlan_bind_interface": "1abc", "wakeonlan_mac": MAC},
    {"wakeonlan_bind_interface": "a b", "wakeonlan_mac": MAC}, {"wakeonlan_broadcast_address": "999.1.1.1", "wakeonlan_mac": MAC},
    {"wakeonlan_broadcast_address": "1.2.3", "wakeonlan_mac": MAC}, {"wakeonlan_broadcast_address": "01.2.3.4", "wakeonlan_mac": MAC},
    {"startall_onboot_delay": 301}, {"startall_onboot_delay": -1}, {"startall_onboot_delay": "30"}, {"startall_onboot_delay": True},
    {"ballooning_target": 101}, {"ballooning_target": -1}, {"ballooning_target": 1.5}, {"clear": ["description"]}, {"clear": ["acme"]}, {"clear": ["inconnu"]},
    {"clear": ["wakeonlan", "wakeonlan"]}, {"clear": ["wakeonlan"], "wakeonlan_mac": MAC}, {"clear": ["ballooning-target"], "ballooning_target": 50},
    {"clear": ["startall-onboot-delay"], "startall_onboot_delay": 5}, {}, {"digest": "pas-un-digest", "ballooning_target": 5},
])
def test_invalid_requests_never_reach_proxmox(api, body):
    c, cid = api
    r = c.put(u(cid), json={"digest": D1, "confirm": True, **body})
    assert r.status_code == 422 and not WRITES
    for v in body.values():
        assert not isinstance(v, str) or len(v) < 4 or v not in r.text         # la valeur saisie n'est jamais renvoyée


def test_unknown_field_is_ignored_not_forwarded(api):
    c, cid = api
    assert put(c, cid, ballooning_target=60, description="piraté", acme="x").status_code == 200
    assert WRITES[-1] == {"ballooning-target": "60", "digest": D1}


def test_not_applied_by_proxmox_is_a_502_and_audited(api):
    c, cid = api
    ST["flags"]["noapply"] = True
    r = put(c, cid, ballooning_target=60)
    assert r.status_code == 502 and "pas appliqué" in r.json()["detail"]
    assert ("node-options", "error") in {(a["action"], a["status"]) for a in c.get("/api/audit").json()}


def test_readback_checks_each_wakeonlan_change(api):
    c, cid = api
    ST["flags"]["noapply_keys"] = {"wakeonlan"}
    assert put(c, cid, wakeonlan_mac=MAC).status_code == 502                       # la MAC demandée n'est pas celle relue
    ST["cfg"]["wakeonlan"] = f"mac={MAC}"
    ST["cfg"]["digest"] = D1
    assert put(c, cid, clear=["wakeonlan"]).status_code == 502                     # l'option devait disparaître
    ST["cfg"]["digest"] = D1
    assert put(c, cid, wakeonlan_bind_interface="vmbr0").status_code == 502        # l'interface demandée n'est pas relue
    ST["flags"]["noapply_keys"] = {"startall-onboot-delay", "ballooning-target"}
    ST["cfg"]["digest"] = D1
    assert put(c, cid, startall_onboot_delay=30).status_code == 502
    ST["cfg"]["digest"] = D1
    assert put(c, cid, ballooning_target=30).status_code == 502
    ST["cfg"].update({"startall-onboot-delay": 10, "ballooning-target": 10, "digest": D1})
    assert put(c, cid, clear=["startall-onboot-delay"]).status_code == 502
    ST["cfg"]["digest"] = D1
    assert put(c, cid, clear=["ballooning-target"]).status_code == 502


def test_forbidden_by_proxmox_is_audited_without_leak(api):
    c, cid = api
    ST["flags"]["forbidden"] = True
    r = put(c, cid, ballooning_target=60)
    assert r.status_code >= 400 and SECRET not in r.text and SECRET not in audit_text(c)


def test_empty_config_can_be_written_without_digest(api):
    c, cid = api
    ST["cfg"] = {}
    r = c.put(u(cid), json={"confirm": True, "ballooning_target": 60})
    assert r.status_code == 200 and WRITES[-1] == {"ballooning-target": "60"}


def test_unreadable_config_is_refused(api):
    c, cid = api
    ST["cfg"] = {"description": "x", "digest": "pas-un-digest"}
    assert put(c, cid, ballooning_target=60).status_code == 502 and not WRITES


def test_audit_has_the_option_names_only(api):
    c, cid = api
    put(c, cid, wakeonlan_mac=MAC, ballooning_target=60, clear=["startall-onboot-delay"])
    t = audit_text(c)
    assert "node-options" in t and "wakeonlan" in t and MAC not in t


def test_bad_node_name_and_login(api, client):
    c, cid = api
    assert c.get(u(cid, node="a b")).status_code in (404, 422)
    assert put(c, cid, ballooning_target=5).status_code == 200
    client.cookies.clear()
    assert client.get(u(cid)).status_code == 401 and client.put(u(cid), json={"confirm": True, "ballooning_target": 5}).status_code == 401


def test_parse_wol_unit():
    assert N.parse_wol(None) == (None, True)
    assert N.parse_wol(f"mac={MAC}")[0]["mac"] == MAC
