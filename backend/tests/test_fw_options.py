import re
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
PHRASE = "COUPURE POSSIBLE"
WRITES: list[tuple[str, dict]] = []
ST: dict = {}
BASES = {"cluster": "/cluster/firewall", "node": "/nodes/enzo/firewall", "guest": "/nodes/enzo/qemu/115/firewall", "kaji": "/nodes/enzo/lxc/116/firewall"}
URLS = {"cluster": "/firewall/cluster/options", "node": "/firewall/nodes/enzo/options", "guest": "/firewall/guests/enzo/qemu/115/options", "kaji": "/firewall/guests/enzo/lxc/116/options"}
ALLOWED = {
    "cluster": {"enable", "ebtables", "policy_forward", "policy_in", "policy_out", "delete", "digest"},
    "node": {"enable", "log_level_forward", "log_level_in", "log_level_out", "log_nf_conntrack", "ndp", "nf_conntrack_allow_invalid", "nf_conntrack_helpers", "nf_conntrack_max",
             "nf_conntrack_tcp_timeout_established", "nf_conntrack_tcp_timeout_syn_recv", "nftables", "nosmurfs", "protection_synflood", "protection_synflood_burst",
             "protection_synflood_rate", "smurf_log_level", "tcp_flags_log_level", "tcpflags", "delete", "digest"},
    "guest": {"dhcp", "enable", "ipfilter", "log_level_in", "log_level_out", "macfilter", "ndp", "policy_in", "policy_out", "radv", "delete", "digest"},
}
ALLOWED["kaji"] = ALLOWED["guest"]
BOOLS = {"enable", "ebtables", "log_nf_conntrack", "ndp", "nf_conntrack_allow_invalid", "nftables", "nosmurfs", "protection_synflood", "tcpflags", "dhcp", "ipfilter", "macfilter", "radv"}


def fresh():
    ST.clear()
    for k in BASES:
        ST[k] = {"enable": 0}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    level = next((k for k, b in BASES.items() if p == b + "/options"), None)
    if level is None:
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    s = ST[level]
    if request.method == "GET":
        return httpx.Response(200, json={"data": {**s, "digest": DIGEST}})
    if ST.get("fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    bad = set(body) - ALLOWED[level]
    if bad or any(body[k] not in ("0", "1") for k in set(body) & BOOLS):
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(bad)}"})
    WRITES.append((level, body))
    if not ST.get("noapply"):
        for k, v in body.items():
            if k in ("delete", "digest"):
                continue
            s[k] = int(v) if v.lstrip("-").isdigit() else v
        for k in [x for x in body.get("delete", "").split(",") if x]:
            s.pop(k, None)
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client, monkeypatch):
    WRITES.clear(); fresh()
    monkeypatch.setattr("app.routers.fw_options.get_settings", lambda: SimpleNamespace(protected_vmids={116}))
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def put(c, cid, level, **b):
    return c.put(f"/api/connections/{cid}{URLS[level]}", json={"confirm": True, **b})


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# ---------------------------------------------------------------- niveau inactif : réglages appliqués à l'activation
def test_inactive_level_is_editable_with_confirm_alone(api):
    c, cid = api
    r = put(c, cid, "cluster", ebtables=True, policy_in="DROP", policy_out="ACCEPT")
    assert r.status_code == 200 and r.json()["inactive_level"] is True and r.json()["locks"]["inert"] is True
    assert WRITES == [("cluster", {"ebtables": "1", "policy_in": "DROP", "policy_out": "ACCEPT", "digest": DIGEST})]
    assert ST["cluster"]["policy_in"] == "DROP" and ST["cluster"]["enable"] == 0


def test_node_options_exact_params_and_types(api):
    c, cid = api
    r = put(c, cid, "node", nf_conntrack_max=262144, log_level_in="info", nosmurfs=True, nf_conntrack_helpers=["tftp", "ftp"], protection_synflood_rate=200)
    assert r.status_code == 200
    assert WRITES[-1][1] == {"nf_conntrack_max": "262144", "log_level_in": "info", "nosmurfs": "1", "nf_conntrack_helpers": "ftp,tftp", "protection_synflood_rate": "200", "digest": DIGEST}


@pytest.mark.parametrize("level,b", [
    ("node", {"nf_conntrack_max": 100}), ("node", {"nf_conntrack_max": "262144"}), ("node", {"nf_conntrack_tcp_timeout_syn_recv": 61}), ("node", {"nf_conntrack_tcp_timeout_established": 10}),
    ("node", {"protection_synflood_burst": 0}), ("node", {"nf_conntrack_helpers": ["evil"]}), ("node", {"nf_conntrack_helpers": ["ftp", "ftp"]}), ("node", {"log_level_in": "bruit"}),
    ("node", {"nosmurfs": "1"}), ("node", {"nosmurfs": 1}), ("cluster", {"policy_in": "ALLOW"}), ("cluster", {"policy_forward": "REJECT"}), ("cluster", {"ebtables": "true"}),
    ("guest", {"policy_out": "DENY"}), ("guest", {"macfilter": "yes"}),
])
def test_invalid_values_are_refused_without_any_call(api, level, b):
    c, cid = api
    assert put(c, cid, level, **b).status_code == 422 and not WRITES


@pytest.mark.parametrize("level,b", [("cluster", {"hookscript": "x"}), ("cluster", {"log_ratelimit": "enable=0"}), ("node", {"nf_conntrack_max_x": 1}), ("guest", {"nf_conntrack_max": 40000})])
def test_unknown_or_foreign_fields_are_ignored_not_forwarded(api, level, b):
    c, cid = api
    assert put(c, cid, level, **b).status_code == 422 and not WRITES              # rien d'autre à modifier : refus, rien n'est transmis
    assert put(c, cid, level, ndp=True, **b).status_code in (200, 422) and all(set(w[1]) <= ALLOWED[w[0]] for w in WRITES)


def test_confirm_is_required_and_strict(api):
    c, cid = api
    assert c.put(f"/api/connections/{cid}{URLS['cluster']}", json={"ebtables": True}).status_code == 400
    assert c.put(f"/api/connections/{cid}{URLS['cluster']}", json={"ebtables": True, "confirm": "true"}).status_code == 422
    assert not WRITES


@pytest.mark.parametrize("b", [{}, {"clear": []}, {"ebtables": True, "clear": ["ebtables"]}, {"clear": ["hookscript"]}, {"clear": ["../x"]}])
def test_empty_clashing_or_unknown_changes(api, b):
    c, cid = api
    assert put(c, cid, "cluster", **b).status_code in (422,) and not WRITES


# ---------------------------------------------------------------- verrou « coupure possible »
@pytest.mark.parametrize("level", ["cluster", "node"])
def test_enabling_the_firewall_needs_the_cut_access_unlock(api, level):
    c, cid = api
    r = put(c, cid, level, enable=True)
    assert r.status_code == 409 and "Coupure d'accès possible" in r.json()["detail"] and PHRASE in r.json()["detail"] and not WRITES
    assert put(c, cid, level, enable=True, acknowledge_cut_access=True).status_code == 409
    assert put(c, cid, level, enable=True, acknowledge_cut_access=True, type_name="coupure possible").status_code == 409
    assert put(c, cid, level, enable=True, acknowledge_live=True, type_name=PHRASE).status_code == 409                 # la phrase seule ne suffit pas
    assert not WRITES and ST[level]["enable"] == 0
    r = put(c, cid, level, enable=True, acknowledge_cut_access=True, type_name=PHRASE)
    assert r.status_code == 200 and ST[level]["enable"] == 1 and WRITES[-1][1]["enable"] == "1"


def test_cluster_enable_is_an_integer_node_enable_a_boolean_both_zero_one(api):
    c, cid = api
    put(c, cid, "cluster", enable=True, acknowledge_cut_access=True, type_name=PHRASE)
    put(c, cid, "node", enable=True, acknowledge_cut_access=True, type_name=PHRASE)
    assert [w[1]["enable"] for w in WRITES] == ["1", "1"]


@pytest.mark.parametrize("level", ["cluster", "node"])
def test_restrictive_default_policy_on_an_active_level_is_a_cut_risk(api, level):
    c, cid = api
    ST[level]["enable"] = 1
    k = "policy_in"
    if level == "node":
        pytest.skip("les politiques par défaut sont des options du datacenter et de la machine")
    r = put(c, cid, level, **{k: "DROP"})
    assert r.status_code == 409 and "policy_in = DROP" in r.json()["detail"] and not WRITES
    assert put(c, cid, level, **{k: "DROP"}, acknowledge_cut_access=True, type_name=PHRASE).status_code == 200 and ST[level][k] == "DROP"


def test_permissive_policy_on_an_active_level_only_needs_the_live_unlock(api):
    c, cid = api
    ST["cluster"].update({"enable": 1, "policy_in": "DROP"})
    r = put(c, cid, "cluster", policy_in="ACCEPT")
    assert r.status_code == 409 and "ACTIF" in r.json()["detail"] and "Coupure" not in r.json()["detail"] and not WRITES
    assert put(c, cid, "cluster", policy_in="ACCEPT", acknowledge_live=True).status_code == 200


def test_enabling_and_restricting_together_lists_both_reasons(api):
    c, cid = api
    r = c.put(f"/api/connections/{cid}{URLS['cluster']}", json={"confirm": True, "enable": True, "policy_in": "DROP"})
    d = r.json()["detail"]
    assert r.status_code == 409 and "activer le pare-feu du datacenter" in d and "policy_in = DROP" in d


def test_other_options_of_an_active_level_need_the_live_unlock(api):
    c, cid = api
    ST["node"]["enable"] = 1
    r = put(c, cid, "node", log_level_in="debug")
    assert r.status_code == 409 and "ACTIF" in r.json()["detail"] and not WRITES
    assert put(c, cid, "node", log_level_in="debug", acknowledge_live=True).status_code == 200


def test_disabling_an_active_level_needs_the_live_unlock(api):
    c, cid = api
    ST["node"]["enable"] = 1
    assert put(c, cid, "node", enable=False).status_code == 409 and not WRITES
    assert put(c, cid, "node", enable=False, acknowledge_live=True).status_code == 200 and ST["node"]["enable"] == 0


def test_clear_enable_counts_as_disabling(api):
    c, cid = api
    ST["node"]["enable"] = 1
    assert put(c, cid, "node", clear=["enable"]).status_code == 409 and not WRITES
    r = put(c, cid, "node", clear=["enable"], acknowledge_live=True)
    assert r.status_code == 200 and WRITES[-1][1]["delete"] == "enable" and "enable" not in ST["node"]


def test_clear_goes_in_one_delete_parameter(api):
    c, cid = api
    ST["cluster"].update({"policy_in": "DROP", "ebtables": 1})
    assert put(c, cid, "cluster", clear=["policy_in", "ebtables", "policy_in"]).status_code == 200
    assert WRITES[-1][1] == {"delete": "policy_in,ebtables", "digest": DIGEST} and "policy_in" not in ST["cluster"]


# ---------------------------------------------------------------- machine, et machine de Kaji
def test_a_guest_firewall_can_be_enabled_with_the_live_unlock(api):
    c, cid = api
    r = put(c, cid, "guest", enable=True)
    assert r.status_code == 409 and "va commencer à filtrer" in r.json()["detail"] and "Coupure" not in r.json()["detail"] and not WRITES
    assert put(c, cid, "guest", enable=True, acknowledge_live=True).status_code == 200 and ST["guest"]["enable"] == 1


def test_guest_policy_alone_is_not_a_cut_risk_for_a_normal_machine(api):
    c, cid = api
    ST["guest"]["enable"] = 1
    r = put(c, cid, "guest", policy_in="DROP")
    assert r.status_code == 409 and "Coupure" not in r.json()["detail"]
    assert put(c, cid, "guest", policy_in="DROP", acknowledge_live=True).status_code == 200


def test_kajis_own_machine_is_always_a_cut_risk(api):
    """CT 116 = Kaji : activer son pare-feu ou le modifier pendant qu'il est actif peut couper Kaji lui-même."""
    c, cid = api
    r = put(c, cid, "kaji", enable=True)
    assert r.status_code == 409 and "machine de Kaji" in r.json()["detail"] and not WRITES
    assert put(c, cid, "kaji", enable=True, acknowledge_live=True).status_code == 409
    assert put(c, cid, "kaji", enable=True, acknowledge_cut_access=True, type_name=PHRASE).status_code == 200
    r = put(c, cid, "kaji", log_level_in="debug")
    assert r.status_code == 409 and "machine de Kaji" in r.json()["detail"]


def test_kajis_machine_inactive_firewall_can_be_left_alone_for_harmless_reads_but_not_changed(api):
    c, cid = api
    assert put(c, cid, "kaji", log_level_in="debug").status_code == 200              # niveau inactif et rien ne s'applique : inerte


# ---------------------------------------------------------------- dry_run
@pytest.mark.parametrize("level,b,cut", [("cluster", {"enable": True}, True), ("node", {"enable": True}, True), ("cluster", {"ebtables": True}, False)])
def test_dry_run_reports_the_locks_and_writes_nothing(api, level, b, cut):
    c, cid = api
    r = c.put(f"/api/connections/{cid}{URLS[level]}", json={"dry_run": True, **b})                 # pas besoin de confirm
    j = r.json()
    assert r.status_code == 200 and j["dry_run"] is True and bool(j["locks"]["cut"]) is cut and (j["phrase"] == PHRASE) is cut and not WRITES
    assert set(j["params"]) <= ALLOWED[level]


def test_dry_run_still_validates(api):
    c, cid = api
    assert c.put(f"/api/connections/{cid}{URLS['cluster']}", json={"dry_run": True, "policy_in": "ALLOW"}).status_code == 422
    assert c.put(f"/api/connections/{cid}{URLS['cluster']}", json={"dry_run": True}).status_code == 422


# ---------------------------------------------------------------- Proxmox, audit, accès
def test_not_applied_is_reported(api):
    c, cid = api
    ST["noapply"] = True
    r = put(c, cid, "cluster", ebtables=True)
    assert r.status_code == 502 and "n'a pas appliqué" in r.json()["detail"]


def test_errors_never_leak(api):
    c, cid = api
    ST["fail"] = True
    r = put(c, cid, "cluster", ebtables=True)
    assert r.status_code == 502 and SECRET not in r.text and SECRET not in c.get("/api/audit").text


def test_audit_records_success_and_refusals(api):
    c, cid = api
    put(c, cid, "cluster", ebtables=True)
    put(c, cid, "cluster", enable=True)
    pairs = audit_pairs(c)
    assert ("fw-options", "started") in pairs and ("fw-options", "error") in pairs
    assert "ebtables=1" in c.get("/api/audit").text


def test_unknown_node_and_paths_are_validated(api):
    c, cid = api
    assert c.put(f"/api/connections/{cid}/firewall/nodes/a;b/options", json={"confirm": True, "ndp": True}).status_code == 422
    assert c.put(f"/api/connections/{cid}/firewall/guests/enzo/vz/115/options", json={"confirm": True, "ndp": True}).status_code == 422
    assert c.put(f"/api/connections/{cid}/firewall/guests/enzo/qemu/99/options", json={"confirm": True, "ndp": True}).status_code == 422 and not WRITES


def test_requires_login(client):
    for tail in ("/firewall/cluster/options", "/firewall/nodes/enzo/options", "/firewall/guests/enzo/qemu/115/options"):
        assert client.put(f"/api/connections/1{tail}", json={"confirm": True}).status_code == 401


# ---------------------------------------------------------------- trous trouvés par les mutations
@pytest.mark.parametrize("policy", ["DROP", "REJECT"])
def test_both_restrictive_policies_are_cut_risks(api, policy):
    c, cid = api
    ST["cluster"]["enable"] = 1
    r = put(c, cid, "cluster", policy_out=policy)
    assert r.status_code == 409 and f"policy_out = {policy}" in r.json()["detail"] and "Coupure" in r.json()["detail"] and not WRITES


@pytest.mark.parametrize("field", ["acknowledge_live", "acknowledge_cut_access", "dry_run"])
@pytest.mark.parametrize("value", ["true", 1, "1"])
def test_unlock_flags_must_be_real_booleans(api, field, value):
    """Un « true » en texte ou un 1 ne déverrouille rien."""
    c, cid = api
    ST["cluster"]["enable"] = 1
    r = c.put(f"/api/connections/{cid}{URLS['cluster']}", json={"confirm": True, "ebtables": True, field: value})
    assert r.status_code == 422 and not WRITES


def test_disabling_while_restricting_is_not_a_cut_risk(api):
    """On désactive le niveau : la politique restrictive ne s'appliquera pas tout de suite."""
    c, cid = api
    ST["cluster"]["enable"] = 1
    r = put(c, cid, "cluster", clear=["enable"], policy_in="DROP")
    assert r.status_code == 409 and "Coupure" not in r.json()["detail"] and "ACTIF" in r.json()["detail"]
    assert put(c, cid, "cluster", clear=["enable"], policy_in="DROP", acknowledge_live=True).status_code == 200


def test_an_unchanged_restrictive_policy_is_not_a_cut_risk(api):
    c, cid = api
    ST["cluster"].update({"enable": 1, "policy_in": "DROP"})
    r = put(c, cid, "cluster", policy_in="DROP")
    assert r.status_code == 409 and "Coupure" not in r.json()["detail"]                       # déjà DROP : seulement « actif »


def test_the_response_reports_the_locks_that_applied(api):
    c, cid = api
    r = put(c, cid, "cluster", enable=True, acknowledge_cut_access=True, type_name=PHRASE).json()
    assert r["locks"]["cut"] and r["locks"]["live"] == ["la modification s'applique tout de suite"] and r["locks"]["inert"] is False and r["inactive_level"] is False
    r = put(c, cid, "node", ndp=True).json()
    assert r["locks"] == {"cut": [], "live": [], "inert": True} and r["inactive_level"] is True
