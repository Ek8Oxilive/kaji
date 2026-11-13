"""Réglages du datacenter en écriture (lot #365) : `ha`, `fencing`, `crs`, `bwlimit`, `replication`.

Faux Proxmox STRICT : méthode, chemin et paramètres exacts ; chaque chaîne de propriétés est validée avec les motifs du schéma de Proxmox VE 9 (`apidoc.js`, `PUT /cluster/options`),
sans clé en double ; `delete` limité aux noms connus. L'état est relu sous forme d'objets (comme Proxmox les renvoie pour ces propriétés) ou de chaînes.
RIEN de ce fichier n'a tourné sur un vrai cluster : voir la PR pour ce qui a été essayé en réel.
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.datacenterspec import BW_KEYS, parse_bwlimit, parse_crs, parse_ha, shape_options
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
PHRASE = "COUPURE POSSIBLE"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
PUT_KEYS = {"keyboard", "ha", "fencing", "crs", "bwlimit", "replication", "delete"}
DELETABLE = {"keyboard", "ha", "fencing", "crs", "bwlimit", "replication"}
PROP = {
    "ha": re.compile(r"shutdown_policy=(freeze|failover|conditional|migrate)"),
    "fencing": re.compile(r"watchdog|hardware|both"),
    "crs": re.compile(r"(ha=(basic|static)|ha-rebalance-on-start=[01])(,(ha=(basic|static)|ha-rebalance-on-start=[01]))*"),
    "bwlimit": re.compile(r"(clone|default|migration|move|restore)=[0-9]+(\.[0-9]+)?(,(clone|default|migration|move|restore)=[0-9]+(\.[0-9]+)?)*"),
    "replication": re.compile(r"(type=)?(secure|insecure)(,network=[0-9a-f:.]+/[0-9]+)?"),
}
CALLS: list[dict] = []
ST: dict = {}


def fresh():
    ST.clear()
    ST.update(opts={"keyboard": "fr"}, noapply=False, fail=False, as_string=False)


def _parse(k: str, v: str) -> dict:
    items = [x for x in v.split(",") if x]
    d: dict = {}
    for i, x in enumerate(items):
        name, _, val = x.partition("=")
        if k == "replication" and i == 0 and "=" not in x:
            name, val = "type", x
        if name in d:
            raise ValueError("clé en double")
        d[name] = int(val) if val.isdigit() else (float(val) if re.fullmatch(r"[0-9]+\.[0-9]+", val) else val)
    return d


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    if p != "/cluster/options":
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if request.method == "GET":
        o = dict(ST["opts"])
        if ST["as_string"]:
            for k in ("ha", "crs", "bwlimit", "replication"):
                if isinstance(o.get(k), dict):
                    o[k] = ",".join(f"{a}={b}" for a, b in o[k].items())
        return httpx.Response(200, json={"data": o})
    if ST["fail"]:
        return httpx.Response(403, json={"data": None, "message": SECRET})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if request.method != "PUT" or set(body) - PUT_KEYS:
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(set(body) - PUT_KEYS)}"})
    for k, rx in PROP.items():
        if k in body and not rx.fullmatch(body[k]):
            return httpx.Response(400, json={"data": None, "message": f"{k} invalide"})
        if k in ("crs", "bwlimit") and k in body and len({x.partition("=")[0] for x in body[k].split(",")}) != len(body[k].split(",")):
            return httpx.Response(400, json={"data": None, "message": f"{k} : clé en double"})
    dl = [x for x in body.get("delete", "").split(",") if x]
    if set(dl) - DELETABLE or (set(dl) & set(body)):
        return httpx.Response(400, json={"data": None, "message": "delete invalide"})
    CALLS.append(body)
    if not ST["noapply"]:
        for k, v in body.items():
            if k == "delete":
                continue
            ST["opts"][k] = _parse(k, v) if k in ("ha", "crs", "bwlimit", "replication") else v
        for k in dl:
            ST["opts"].pop(k, None)
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def put(c, cid, **b):
    return c.put(f"/api/connections/{cid}/datacenter/options", json=b)


def get(c, cid):
    return c.get(f"/api/connections/{cid}/datacenter/options").json()


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# --- lecture --------------------------------------------------------------------------------------------------------------------------------------------
def test_unset_settings_read_as_empty(api):
    c, cid = api
    j = get(c, cid)
    assert j["ha"] == {"shutdown_policy": None} and j["fencing"] is None and j["crs"] == {"ha": None, "ha_rebalance_on_start": None}
    assert j["bwlimit"] == {k: None for k in BW_KEYS} and j["replication"] == {"type": None, "network": None} and j["readonly"] == {}


@pytest.mark.parametrize("as_string", [False, True])
def test_reads_objects_and_strings(api, as_string):
    c, cid = api
    ST["as_string"] = as_string
    ST["opts"].update({"ha": {"shutdown_policy": "freeze"}, "fencing": "both", "crs": {"ha": "static", "ha-rebalance-on-start": 1},
                       "bwlimit": {"clone": 100, "default": 0, "migration": 2048.5, "move": 7, "restore": 9}, "replication": {"type": "insecure", "network": "10.9.0.0/24"}})
    j = get(c, cid)
    assert j["ha"] == {"shutdown_policy": "freeze"} and j["fencing"] == "both" and j["crs"] == {"ha": "static", "ha_rebalance_on_start": True}
    assert j["bwlimit"] == {"clone": 100, "default": 0, "migration": 2048.5, "move": 7, "restore": 9}            # 0 est une valeur, pas une absence
    assert j["replication"] == {"type": "insecure", "network": "10.9.0.0/24"} and j["readonly"] == {}


def test_hostile_values_are_dropped_and_unknown_subkeys_are_reported_not_leaked():
    s = shape_options({"ha": {"shutdown_policy": "<script>", "zz": SECRET}, "fencing": SECRET, "crs": "ha=wat,ha-rebalance-on-start=maybe,new-thing=1",
                       "bwlimit": {"default": -1, "clone": "x", "move": True, "restore": 10 ** 12, "migration": float("nan")}, "replication": {"type": "x", "network": "300.0.0.0/8"}})
    assert s["ha"] == {"shutdown_policy": None} and s["fencing"] is None and s["crs"] == {"ha": None, "ha_rebalance_on_start": None}
    assert all(v is None for v in s["bwlimit"].values()) and s["replication"] == {"type": None, "network": None}
    assert s["readonly"]["ha"] == "zz" and s["readonly"]["crs"] == "new-thing" and s["readonly"]["fencing"] == SECRET[:200]
    assert SECRET not in repr({k: v for k, v in s.items() if k not in ("readonly",)}) and "<script>" not in repr(s)


def test_parsers_accept_both_forms():
    assert parse_ha("shutdown_policy=migrate") == parse_ha({"shutdown_policy": "migrate"}) == {"shutdown_policy": "migrate"}
    assert parse_crs("ha=basic,ha-rebalance-on-start=0") == {"ha": "basic", "ha_rebalance_on_start": False}
    assert parse_crs({"ha-rebalance-on-start": "1"}) == {"ha": None, "ha_rebalance_on_start": True}
    assert parse_bwlimit("default=5,move=1.5")["move"] == 1.5 and parse_bwlimit(None) == {k: None for k in BW_KEYS}


# --- ha ---------------------------------------------------------------------------------------------------------------------------------------------------
def test_ha_shutdown_policy_needs_confirm_then_is_written_and_read_back(api):
    c, cid = api
    r = put(c, cid, ha={"shutdown_policy": "freeze"})
    assert r.status_code == 409 and "haute disponibilité" in r.json()["detail"] and not CALLS
    r = put(c, cid, ha={"shutdown_policy": "freeze"}, confirm=True)
    assert r.status_code == 200 and CALLS == [{"ha": "shutdown_policy=freeze"}] and r.json()["ha"] == {"shutdown_policy": "freeze"} and r.json()["changed"] == ["ha"]


def test_ha_dry_run_writes_nothing_and_reports_the_lock(api):
    c, cid = api
    r = put(c, cid, ha={"shutdown_policy": "migrate"}, dry_run=True)
    assert r.status_code == 200 and r.json()["params"] == {"ha": "shutdown_policy=migrate"} and r.json()["locks"]["ha"] is True and not CALLS


@pytest.mark.parametrize("name", ["ha", "fencing", "crs"])
def test_removing_a_ha_setting_needs_confirm(api, name):
    c, cid = api
    ST["opts"].update({"ha": {"shutdown_policy": "freeze"}, "fencing": "watchdog", "crs": {"ha": "static"}})
    assert put(c, cid, clear=[name]).status_code == 409 and not CALLS
    r = put(c, cid, clear=[name], confirm=True)
    assert r.status_code == 200 and CALLS == [{"delete": name}] and name not in ST["opts"]


def test_unknown_ha_policy_is_refused_without_a_call(api):
    c, cid = api
    assert put(c, cid, ha={"shutdown_policy": "reboot"}, confirm=True).status_code == 422 and not CALLS


# --- fencing -----------------------------------------------------------------------------------------------------------------------------------------------
def test_fencing_watchdog_needs_confirm_only(api):
    c, cid = api
    ST["opts"]["fencing"] = "both"
    assert put(c, cid, fencing="watchdog").status_code == 409 and not CALLS
    r = put(c, cid, fencing="watchdog", confirm=True)
    assert r.status_code == 200 and CALLS == [{"fencing": "watchdog"}] and r.json()["fencing"] == "watchdog" and r.json()["locks"]["fencing_experimental"] is False


@pytest.mark.parametrize("mode", ["hardware", "both"])
def test_experimental_fencing_needs_confirm_the_acknowledgement_and_the_phrase(api, mode):
    c, cid = api
    for extra in ({}, {"confirm": True}, {"confirm": True, "acknowledge_cut_access": True}, {"confirm": True, "type_name": PHRASE},
                  {"confirm": True, "acknowledge_cut_access": True, "type_name": "coupure possible"}, {"acknowledge_cut_access": True, "type_name": PHRASE}):
        r = put(c, cid, fencing=mode, **extra)
        assert r.status_code == 409, extra
    assert not CALLS
    r = put(c, cid, fencing=mode, confirm=True, acknowledge_cut_access=True, type_name=PHRASE)
    assert r.status_code == 200 and CALLS == [{"fencing": mode}] and ST["opts"]["fencing"] == mode


def test_experimental_fencing_dry_run_flags_the_lock_and_writes_nothing(api):
    c, cid = api
    d = put(c, cid, fencing="hardware", dry_run=True).json()
    assert d["locks"]["fencing_experimental"] is True and d["locks"]["ha"] is True and not CALLS


def test_experimental_fencing_already_in_place_is_not_a_new_risk(api):
    c, cid = api
    ST["opts"]["fencing"] = "hardware"
    r = put(c, cid, fencing="hardware", confirm=True)
    assert r.status_code == 200                                                         # déjà en place : pas de phrase, mais la confirmation HA reste exigée
    assert put(c, cid, fencing="hardware").status_code == 409


@pytest.mark.parametrize("bad", ["Watchdog", "off", "", 1, True, None])
def test_fencing_value_is_a_strict_choice(api, bad):
    c, cid = api
    r = put(c, cid, fencing=bad, confirm=True, keyboard="de") if bad is not None else put(c, cid, fencing=None, keyboard="de")
    assert (r.status_code == 422) == (bad is not None) and all("fencing" not in x for x in CALLS)


# --- crs --------------------------------------------------------------------------------------------------------------------------------------------------
def test_crs_mode_keeps_the_rebalance_flag_and_the_reverse(api):
    c, cid = api
    ST["opts"]["crs"] = {"ha": "basic", "ha-rebalance-on-start": 1}
    assert put(c, cid, crs={"ha": "static"}).status_code == 409 and not CALLS
    assert put(c, cid, crs={"ha": "static"}, confirm=True).status_code == 200
    assert CALLS[-1] == {"crs": "ha=static,ha-rebalance-on-start=1"}
    assert put(c, cid, crs={"ha_rebalance_on_start": False}, confirm=True).status_code == 200
    assert CALLS[-1] == {"crs": "ha=static,ha-rebalance-on-start=0"} and get(c, cid)["crs"] == {"ha": "static", "ha_rebalance_on_start": False}


def test_crs_from_nothing_writes_only_what_was_given(api):
    c, cid = api
    assert put(c, cid, crs={"ha_rebalance_on_start": True}, confirm=True).status_code == 200 and CALLS == [{"crs": "ha-rebalance-on-start=1"}]
    assert put(c, cid, crs={"ha": "basic"}, confirm=True).status_code == 200 and CALLS[-1] == {"crs": "ha=basic,ha-rebalance-on-start=1"}


@pytest.mark.parametrize("crs", [{"ha": "dynamic"}, {"ha": 1}, {"ha_rebalance_on_start": "1"}, {"ha_rebalance_on_start": 1}, {"ha_rebalance_on_start": "true"}])
def test_crs_values_are_strict(api, crs):
    c, cid = api
    assert put(c, cid, crs=crs, confirm=True).status_code == 422 and not CALLS


# --- bwlimit ----------------------------------------------------------------------------------------------------------------------------------------------
def test_bwlimit_is_written_without_confirm_and_merged_with_the_current_value(api):
    c, cid = api
    ST["opts"]["bwlimit"] = {"default": 1000, "move": 500}
    r = put(c, cid, bwlimit={"migration": 20480, "move": 0})
    assert r.status_code == 200 and CALLS == [{"bwlimit": "default=1000,migration=20480,move=0"}]          # ordre du schéma, clés gardées, 0 écrit
    assert r.json()["bwlimit"] == {"clone": None, "default": 1000, "migration": 20480, "move": 0, "restore": None} and r.json()["locks"]["ha"] is False


def test_bwlimit_remove_one_key_then_all_keys_removes_the_setting(api):
    c, cid = api
    ST["opts"]["bwlimit"] = {"default": 1000, "move": 500}
    assert put(c, cid, bwlimit={"remove": ["move"]}).status_code == 200 and CALLS[-1] == {"bwlimit": "default=1000"}
    assert put(c, cid, bwlimit={"remove": ["default"]}).status_code == 200 and CALLS[-1] == {"delete": "bwlimit"} and "bwlimit" not in ST["opts"]


def test_bwlimit_modified_and_removed_at_once_is_refused(api):
    c, cid = api
    ST["opts"]["bwlimit"] = {"default": 1000}
    r = put(c, cid, bwlimit={"default": 5, "remove": ["default"]})
    assert r.status_code == 422 and "à la fois" in r.json()["detail"] and not CALLS


def test_bwlimit_clear_needs_no_confirm(api):
    c, cid = api
    ST["opts"]["bwlimit"] = {"default": 1000}
    assert put(c, cid, clear=["bwlimit"]).status_code == 200 and CALLS == [{"delete": "bwlimit"}]


@pytest.mark.parametrize("bw", [{"default": -1}, {"default": 1.5}, {"default": "10"}, {"default": True}, {"default": 10 ** 9 + 1}, {"remove": ["bogus"]}, {"remove": ["default"] * 6}])
def test_bwlimit_values_are_strict(api, bw):
    c, cid = api
    assert put(c, cid, bwlimit=bw).status_code == 422 and not CALLS


def test_bwlimit_upper_bound_is_accepted(api):
    c, cid = api
    assert put(c, cid, bwlimit={"default": 10 ** 9}).status_code == 200 and CALLS == [{"bwlimit": "default=1000000000"}]


def test_a_remaining_zero_limit_is_not_mistaken_for_a_removed_setting(api):
    c, cid = api
    ST["opts"]["bwlimit"] = {"default": 0}
    ST["noapply"] = True                                                                # Proxmox « oublie » de retirer le réglage
    r = put(c, cid, clear=["bwlimit"])
    assert r.status_code == 502 and "n'a pas retiré" in r.json()["detail"]


# --- replication -------------------------------------------------------------------------------------------------------------------------------------------
def test_replication_secure_with_network_needs_no_confirm_and_keeps_the_network(api):
    c, cid = api
    ST["opts"]["replication"] = {"type": "secure", "network": "10.1.0.0/24"}
    assert put(c, cid, replication={"type": "secure"}).status_code == 200 and CALLS[-1] == {"replication": "type=secure,network=10.1.0.0/24"}
    assert put(c, cid, replication={"network": ""}).status_code == 200 and CALLS[-1] == {"replication": "type=secure"}
    assert put(c, cid, replication={"network": "10.2.0.0/16"}).status_code == 200 and CALLS[-1] == {"replication": "type=secure,network=10.2.0.0/16"}


def test_insecure_replication_needs_confirm_only_when_it_becomes_insecure(api):
    c, cid = api
    r = put(c, cid, replication={"type": "insecure"})
    assert r.status_code == 409 and "Réplication non chiffrée" in r.json()["detail"] and not CALLS
    assert put(c, cid, replication={"type": "insecure"}, dry_run=True).json()["locks"]["replication_insecure"] is True
    assert put(c, cid, replication={"type": "insecure"}, confirm=True).status_code == 200 and CALLS == [{"replication": "type=insecure"}]
    assert put(c, cid, replication={"network": "10.3.0.0/24"}).status_code == 200                      # déjà non chiffrée : pas de nouvelle confirmation
    assert CALLS[-1] == {"replication": "type=insecure,network=10.3.0.0/24"}


@pytest.mark.parametrize("rep", [{"type": "bogus"}, {"network": "10.0.0.1/24"}, {"network": "abc"}, {"network": "10.0.0.0/33"}, "secure"])
def test_replication_values_are_strict(api, rep):
    c, cid = api
    assert put(c, cid, replication=rep, confirm=True).status_code == 422 and not CALLS


def test_clearing_replication_is_allowed_without_confirm(api):
    c, cid = api
    ST["opts"]["replication"] = {"type": "insecure"}
    assert put(c, cid, clear=["replication"]).status_code == 200 and CALLS == [{"delete": "replication"}]


# --- sous-clés inconnues -----------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,body", [
    ("ha", {"ha": {"shutdown_policy": "freeze"}}), ("crs", {"crs": {"ha": "static"}}), ("bwlimit", {"bwlimit": {"default": 1}}),
    ("replication", {"replication": {"type": "secure"}}), ("crs", {"clear": ["crs"]}), ("bwlimit", {"clear": ["bwlimit"]}),
])
def test_a_setting_with_keys_kaji_does_not_know_is_never_rewritten(api, name, body):
    c, cid = api
    ST["opts"][name] = {"future-key": 1, **({"shutdown_policy": "migrate"} if name == "ha" else {})}
    assert get(c, cid)["readonly"][name] == "future-key"
    r = put(c, cid, confirm=True, **body)
    assert r.status_code == 422 and "future-key" in r.json()["detail"] and not CALLS and ST["opts"][name]["future-key"] == 1


def test_other_settings_stay_writable_when_one_setting_is_blocked(api):
    c, cid = api
    ST["opts"]["crs"] = {"future-key": 1}
    assert put(c, cid, keyboard="de", bwlimit={"default": 5}).status_code == 200 and CALLS == [{"keyboard": "de", "bwlimit": "default=5"}]


# --- relecture, digest, audit, erreurs ------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("body", [{"ha": {"shutdown_policy": "freeze"}}, {"bwlimit": {"default": 5}}, {"replication": {"type": "secure"}}, {"crs": {"ha": "static"}}])
def test_a_change_proxmox_did_not_apply_is_reported_as_a_bad_gateway(api, body):
    c, cid = api
    ST["noapply"] = True
    r = put(c, cid, confirm=True, **body)
    assert r.status_code == 502 and "n'a pas appliqué" in r.json()["detail"]
    assert ("datacenter-options", "error") in audit_pairs(c)


def test_stale_digest_refuses_with_409_and_writes_nothing(api):
    c, cid = api
    d0 = get(c, cid)["digest"]
    ST["opts"]["bwlimit"] = {"default": 7}                                                # modifié ailleurs entre-temps
    r = put(c, cid, bwlimit={"default": 5}, digest=d0)
    assert r.status_code == 409 and not CALLS
    assert put(c, cid, bwlimit={"default": 5}, digest=get(c, cid)["digest"]).status_code == 200


def test_the_digest_covers_the_new_settings(api):
    c, cid = api
    d0 = get(c, cid)["digest"]
    for k, v in (("fencing", "both"), ("ha", {"shutdown_policy": "freeze"}), ("crs", {"ha": "static"}), ("bwlimit", {"move": 3}), ("replication", {"type": "insecure"})):
        ST["opts"][k] = v
        d1 = get(c, cid)["digest"]
        assert d1 != d0
        d0 = d1


def test_audit_names_the_change_without_secrets_and_records_refusals(api):
    c, cid = api
    assert put(c, cid, ha={"shutdown_policy": "freeze"}).status_code == 409
    assert put(c, cid, ha={"shutdown_policy": "freeze"}, confirm=True).status_code == 200
    log = c.get("/api/audit").text
    assert "ha=shutdown_policy=freeze" in log and SECRET not in log and PWD not in log
    pairs = audit_pairs(c)
    assert ("datacenter-options", "error") in pairs and ("datacenter-options", "started") in pairs


def test_proxmox_refusal_is_passed_on_without_leaking_its_message(api):
    c, cid = api
    ST["fail"] = True
    r = put(c, cid, bwlimit={"default": 5})
    assert r.status_code in (403, 502) and SECRET not in r.text and SECRET not in c.get("/api/audit").text


def test_a_request_with_only_empty_new_settings_is_an_empty_request(api):
    c, cid = api
    assert put(c, cid, ha={}, crs={}, bwlimit={}, replication={}).status_code == 422 and not CALLS
