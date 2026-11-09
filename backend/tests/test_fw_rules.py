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
BASES = {"cluster": "/cluster/firewall", "node": "/nodes/enzo/firewall", "guest": "/nodes/enzo/qemu/115/firewall", "kaji": "/nodes/enzo/lxc/116/firewall",
         "group": "/cluster/firewall/groups/web"}
URLS = {"cluster": "/firewall/cluster", "node": "/firewall/nodes/enzo", "guest": "/firewall/guests/enzo/qemu/115", "kaji": "/firewall/guests/enzo/lxc/116", "group": "/firewall/groups/web"}
ALLOWED = {"action", "type", "source", "dest", "proto", "sport", "dport", "iface", "macro", "log", "icmp-type", "comment", "enable", "pos", "digest", "moveto", "delete"}
WRITES: list[tuple[str, str, dict]] = []
ST: dict = {}


def fresh(cluster_on=False):
    ST.clear()
    ST["opts"] = {"cluster": {"enable": int(cluster_on)}, "node": {"enable": 0}, "guest": {"enable": 0}, "kaji": {"enable": 0}}
    ST["rules"] = {k: [] for k in BASES}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    m = request.method
    if p == "/cluster/firewall/groups":
        return httpx.Response(200, json={"data": [{"group": "web"}]})
    if p == "/cluster/firewall/macros":
        return httpx.Response(200, json={"data": [{"macro": "SSH"}, {"macro": "HTTPS"}, {"macro": "VNC"}, {"macro": "SPICEproxy"}]})
    for lvl, b in BASES.items():
        if p == b + "/options" and lvl != "group":
            return httpx.Response(200, json={"data": ST["opts"][lvl]})
    for lvl, b in sorted(BASES.items(), key=lambda x: -len(x[1])):
        if p == b + "/rules" or p.startswith(b + "/rules/"):
            break
    else:
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    rules = ST["rules"][lvl]
    pos = int(p.rsplit("/", 1)[1]) if p.startswith(b + "/rules/") else None
    if m == "GET":
        if pos is None:
            return httpx.Response(200, json={"data": [{**r, "pos": i} for i, r in enumerate(rules)]})
        if pos >= len(rules):
            return httpx.Response(500, json={"data": None, "message": "no such rule"})
        return httpx.Response(200, json={"data": {**rules[pos], "pos": pos, "digest": DIGEST}})
    if ST.get("fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    bad = set(body) - ALLOWED
    if bad or any(body.get("enable", "0") not in ("0", "1") for _ in [0]):
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(bad)}"})
    if m != "POST" and body.get("digest") not in (None, DIGEST):
        return httpx.Response(400, json={"data": None, "message": "digest"})
    WRITES.append((m, p, body))
    if ST.get("noapply"):
        return httpx.Response(200, json={"data": None})
    fields = {k.replace("-", "_") if k == "icmp-type" else k: (int(v) if k == "enable" else v) for k, v in body.items() if k not in ("pos", "digest", "moveto", "delete")}
    if m == "POST":
        if "type" not in body or "action" not in body:
            return httpx.Response(400, json={"data": None, "message": "type/action requis"})
        r = {k: v for k, v in fields.items()}
        rules.insert(int(body["pos"]) if "pos" in body else len(rules), r)
    elif m == "DELETE":
        rules.pop(pos)
    else:
        r = rules[pos]
        for k in [x for x in body.get("delete", "").split(",") if x]:
            r.pop(k.replace("-", "_"), None)
        r.update(fields)
        if "moveto" in body:
            rules.insert(int(body["moveto"]), rules.pop(pos))
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client, monkeypatch):
    WRITES.clear(); fresh()
    monkeypatch.setattr("app.routers.fw_rules.get_settings", lambda: SimpleNamespace(protected_vmids={116}))
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def post(c, cid, level, **b):
    return c.post(f"/api/connections/{cid}{URLS[level]}/rules", json={"confirm": True, **b})


def put(c, cid, level, pos, **b):
    return c.put(f"/api/connections/{cid}{URLS[level]}/rules/{pos}", json={"confirm": True, **b})


def move(c, cid, level, pos, to, **b):
    return c.put(f"/api/connections/{cid}{URLS[level]}/rules/{pos}/move", json={"confirm": True, "moveto": to, **b})


def delete(c, cid, level, pos, **q):
    return c.delete(f"/api/connections/{cid}{URLS[level]}/rules/{pos}", params={"confirm": True, **q})


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


ADMIN_DROP = {"type": "in", "action": "DROP", "dport": "8006", "proto": "tcp"}


def test_create_inert_levels_need_only_confirm(api):
    c, cid = api
    for lvl in ("cluster", "node", "guest", "group"):
        r = post(c, cid, lvl, type="in", action="ACCEPT", dport="443", proto="tcp", comment="web")
        assert r.status_code == 200, (lvl, r.text)
    assert all(len(ST["rules"][k]) == 1 for k in ("cluster", "node", "guest", "group"))
    assert ST["rules"]["guest"][0]["enable"] == 0                   # créée désactivée par défaut
    assert WRITES[0][2]["enable"] == "0"


def test_requires_confirm_and_dry_run_writes_nothing(api):
    c, cid = api
    r = c.post(f"/api/connections/{cid}{URLS['guest']}/rules", json={"type": "in", "action": "DROP"})
    assert r.status_code == 400 and not WRITES
    r = c.post(f"/api/connections/{cid}{URLS['guest']}/rules", json={"dry_run": True, "type": "in", "action": "DROP"})
    assert r.status_code == 200 and r.json()["dry_run"] and not WRITES


def test_live_lock_when_cluster_and_level_enabled(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1; ST["opts"]["guest"]["enable"] = 1
    r = post(c, cid, "guest", type="in", action="ACCEPT", dport="80", proto="tcp", enable=True)
    assert r.status_code == 409 and not WRITES
    assert post(c, cid, "guest", type="in", action="ACCEPT", dport="80", proto="tcp", enable=True, acknowledge_live=True).status_code == 200
    assert post(c, cid, "guest", type="in", action="ACCEPT", dport="80", proto="tcp", enable=True, acknowledge_live="true").status_code == 422


def test_disabled_rule_on_active_level_is_inert(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1; ST["opts"]["guest"]["enable"] = 1
    assert post(c, cid, "guest", type="in", action="DROP", dport="80", proto="tcp").status_code == 200


def test_cluster_enabled_but_level_disabled_is_inert(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1
    assert post(c, cid, "guest", type="in", action="ACCEPT", enable=True).status_code == 200


def test_cut_lock_blocking_admin_port(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1
    for body in (ADMIN_DROP, {**ADMIN_DROP, "dport": "22"}, {**ADMIN_DROP, "dport": "3128"}, {**ADMIN_DROP, "dport": "1000:9000"}, {**ADMIN_DROP, "dport": "80,8006"},
                 {"type": "in", "action": "REJECT", "proto": "tcp"}, {"type": "in", "action": "DROP", "macro": "SSH"}, {"type": "in", "action": "DROP", "dport": "ssh", "proto": "tcp"}):
        r = post(c, cid, "cluster", enable=True, acknowledge_live=True, **body)
        assert r.status_code == 409 and "Coupure" in r.json()["detail"], body
    assert not WRITES
    r = post(c, cid, "cluster", enable=True, acknowledge_cut_access=True, type_name=PHRASE, **ADMIN_DROP)
    assert r.status_code == 200
    r = post(c, cid, "cluster", enable=True, acknowledge_cut_access=True, type_name="coupure possible", **ADMIN_DROP)
    assert r.status_code == 409


def test_non_admin_drop_is_only_live(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1
    for body in ({"type": "in", "action": "DROP", "dport": "80", "proto": "tcp"}, {"type": "out", "action": "DROP", "dport": "8006", "proto": "tcp"},
                 {"type": "in", "action": "DROP", "dport": "8006", "proto": "udp"}, {"type": "in", "action": "ACCEPT", "dport": "8006", "proto": "tcp"}):
        r = post(c, cid, "cluster", enable=True, acknowledge_live=True, **body)
        assert r.status_code == 200, (body, r.text)


def test_removing_accept_admin_with_restrictive_policy(api):
    c, cid = api
    ST["opts"]["cluster"].update(enable=1, policy_in="DROP")
    ST["rules"]["cluster"].append({"type": "in", "action": "ACCEPT", "dport": "8006", "proto": "tcp", "enable": 1})
    assert delete(c, cid, "cluster", 0, acknowledge_live=True).status_code == 409
    assert put(c, cid, "cluster", 0, enable=False, acknowledge_live=True).status_code == 409
    assert len(ST["rules"]["cluster"]) == 1
    ST["opts"]["cluster"]["policy_in"] = "ACCEPT"
    assert delete(c, cid, "cluster", 0, acknowledge_live=True).status_code == 200


def test_moving_rules_checks_both_sides(api):
    c, cid = api
    ST["opts"]["cluster"].update(enable=1, policy_in="DROP")
    ST["rules"]["cluster"] += [{"type": "in", "action": "ACCEPT", "dport": "8006", "proto": "tcp", "enable": 1}, {"type": "in", "action": "DROP", "dport": "8006", "proto": "tcp", "enable": 1}]
    assert move(c, cid, "cluster", 1, 0, acknowledge_live=True).status_code == 409
    assert move(c, cid, "cluster", 1, 0, acknowledge_cut_access=True, type_name=PHRASE).status_code == 200
    assert ST["rules"]["cluster"][0]["action"] == "DROP"


def test_protected_guest_cut_lock_when_active(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1; ST["opts"]["kaji"]["enable"] = 1
    r = post(c, cid, "kaji", type="in", action="ACCEPT", dport="80", proto="tcp", enable=True, acknowledge_live=True)
    assert r.status_code == 409 and "Kaji" in r.json()["detail"]
    assert post(c, cid, "kaji", type="in", action="ACCEPT", dport="80", proto="tcp", enable=True, acknowledge_cut_access=True, type_name=PHRASE).status_code == 200
    ST["opts"]["kaji"]["enable"] = 0
    assert post(c, cid, "kaji", type="in", action="ACCEPT", enable=True).status_code == 200


def test_group_rules_and_group_action(api):
    c, cid = api
    assert post(c, cid, "group", type="group", action="web").status_code == 422          # pas de groupe dans un groupe
    assert post(c, cid, "guest", type="group", action="web").status_code == 200
    assert post(c, cid, "guest", type="group", action="nope").status_code == 422
    assert post(c, cid, "guest", type="in", action="web").status_code == 422
    assert post(c, cid, "guest", type="forward", action="ACCEPT").status_code == 422
    assert post(c, cid, "group", type="forward", action="ACCEPT").status_code == 422
    assert post(c, cid, "group", type="in", action="DROP", dport="8006", proto="tcp").status_code == 200   # cluster inactif


def test_group_rules_cut_lock_when_cluster_active(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1
    r = post(c, cid, "group", type="in", action="DROP", dport="22", proto="tcp", enable=True, acknowledge_live=True)
    assert r.status_code == 409 and "Coupure" in r.json()["detail"]


@pytest.mark.parametrize("bad", [
    {"source": "999.1.1.1"}, {"source": "10.0.0.1,"}, {"source": "a" * 513}, {"source": "10.0.0.5-10.0.0.1"}, {"source": "bad name!"}, {"dest": "+"}, {"dport": "70000"},
    {"dport": "80;rm"}, {"dport": "a,,b"}, {"sport": "1:2:3"}, {"proto": "tcp;x"}, {"proto": "999"}, {"iface": "net0 x"}, {"iface": "x" * 21}, {"macro": "SSH;x"}, {"macro": "Inconnue"},
    {"log": "loud"}, {"icmp_type": "a b"}, {"comment": "x" * 101}, {"comment": "a\nb"}, {"action": "ACCEPT; DROP"}, {"enable": "yes"}, {"enable": 1}, {"pos": -1}, {"pos": 5},
    {"type": "bogus"},
])
def test_invalid_fields_rejected_without_echo(api, bad):
    c, cid = api
    base = {"type": "in", "action": "ACCEPT"}
    r = post(c, cid, "guest", **{**base, **bad})
    assert r.status_code in (422, 409) and not WRITES, (bad, r.text)
    assert SECRET not in r.text


def test_accepted_address_forms(api):
    c, cid = api
    for src in ("10.0.0.0/24", "10.0.0.1-10.0.0.9", "+management", "dc/lan", "guest/ssh_ok", "10.0.0.1,fe80::1,myalias", "2001:db8::/32"):
        assert post(c, cid, "guest", type="in", action="ACCEPT", source=src).status_code == 200, src
    for port in ("80", "80:90", "80,443", "http", "ssh,8000:9000"):
        assert post(c, cid, "guest", type="in", action="ACCEPT", proto="tcp", dport=port).status_code == 200, port


def test_unknown_fields_ignored_never_forwarded(api):
    c, cid = api
    assert post(c, cid, "guest", type="in", action="ACCEPT", evil="x", digest="x").status_code == 200
    assert set(WRITES[0][2]) <= {"type", "action", "enable"}


def test_update_changes_and_clears_and_forwards_digest(api):
    c, cid = api
    ST["rules"]["guest"].append({"type": "in", "action": "ACCEPT", "dport": "80", "proto": "tcp", "comment": "old", "enable": 0})
    r = put(c, cid, "guest", 0, dport="8080", clear=["comment"], enable=True)
    assert r.status_code == 200, r.text
    m, p, body = WRITES[-1]
    assert body["dport"] == "8080" and body["delete"] == "comment" and body["digest"] == DIGEST and body["enable"] == "1"
    assert "comment" not in ST["rules"]["guest"][0]
    assert put(c, cid, "guest", 0, comment="x", clear=["comment"]).status_code == 422
    assert put(c, cid, "guest", 0, clear=["type"]).status_code == 422
    assert put(c, cid, "guest", 0).status_code == 422
    assert put(c, cid, "guest", 7, comment="x").status_code == 404


def test_update_type_group_checks_action(api):
    c, cid = api
    ST["rules"]["guest"].append({"type": "in", "action": "ACCEPT", "enable": 0})
    assert put(c, cid, "guest", 0, type="group").status_code == 422          # action ACCEPT n'est pas un groupe
    assert put(c, cid, "guest", 0, type="group", action="web").status_code == 200


def test_clear_icmp_type_uses_wire_name(api):
    c, cid = api
    ST["rules"]["guest"].append({"type": "in", "action": "ACCEPT", "proto": "icmp", "icmp_type": "echo-request", "enable": 0})
    assert put(c, cid, "guest", 0, clear=["icmp_type"]).status_code == 200
    assert WRITES[-1][2]["delete"] == "icmp-type"
    assert post(c, cid, "guest", type="in", action="ACCEPT", proto="icmp", icmp_type="echo-request").status_code == 200
    assert WRITES[-1][2]["icmp-type"] == "echo-request"


def test_delete_requires_confirm_and_missing_404(api):
    c, cid = api
    ST["rules"]["guest"].append({"type": "in", "action": "ACCEPT", "enable": 0})
    assert c.delete(f"/api/connections/{cid}{URLS['guest']}/rules/0").status_code == 400
    assert delete(c, cid, "guest", 3).status_code == 404
    assert delete(c, cid, "guest", 0, dry_run=True).json()["dry_run"] and len(ST["rules"]["guest"]) == 1
    assert delete(c, cid, "guest", 0).status_code == 200 and not ST["rules"]["guest"]


def test_create_position_and_move_bounds(api):
    c, cid = api
    post(c, cid, "guest", type="in", action="ACCEPT", comment="a")
    post(c, cid, "guest", type="in", action="ACCEPT", comment="b", pos=0)
    assert [r["comment"] for r in ST["rules"]["guest"]] == ["b", "a"]
    assert post(c, cid, "guest", type="in", action="ACCEPT", pos=9).status_code == 422
    assert move(c, cid, "guest", 0, 5).status_code == 422
    assert move(c, cid, "guest", 0, 1).status_code == 200 and ST["rules"]["guest"][1]["comment"] == "b"


def test_not_applied_is_502_and_audited(api):
    c, cid = api
    ST["noapply"] = True
    r = post(c, cid, "guest", type="in", action="ACCEPT")
    assert r.status_code == 502
    assert ("fw-rule-create", "error") in audit_pairs(c)


def test_proxmox_error_does_not_leak_secret_and_audit(api):
    c, cid = api
    ST["fail"] = True
    r = post(c, cid, "guest", type="in", action="ACCEPT")
    assert r.status_code >= 400 and SECRET not in r.text
    assert SECRET not in str(c.get("/api/audit").json())


def test_audit_success_and_refusals(api):
    c, cid = api
    post(c, cid, "guest", type="in", action="ACCEPT")
    ST["opts"]["cluster"]["enable"] = 1; ST["opts"]["guest"]["enable"] = 1
    post(c, cid, "guest", type="in", action="ACCEPT", enable=True)
    pairs = audit_pairs(c)
    assert ("fw-rule-create", "started") in pairs and ("fw-rule-create", "error") in pairs


def test_requires_login(client):
    assert client.post("/api/connections/1/firewall/cluster/rules", json={"confirm": True, "type": "in", "action": "ACCEPT"}).status_code == 401


def test_vnc_port_range_and_macros(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1
    assert post(c, cid, "cluster", enable=True, acknowledge_live=True, type="in", action="DROP", proto="tcp", dport="5950").status_code == 409
    for macro in ("SSH", "VNC", "SPICEproxy"):
        assert post(c, cid, "cluster", enable=True, acknowledge_live=True, type="in", action="DROP", macro=macro).status_code == 409, macro
    r = post(c, cid, "cluster", enable=True, acknowledge_live=True, type="in", action="DROP", macro="HTTPS")
    assert r.status_code == 200, r.text                     # une macro étrangère à l'administration n'est pas « tout le trafic »


def test_edit_that_keeps_accept_admin_is_not_a_cut(api):
    c, cid = api
    ST["opts"]["cluster"].update(enable=1, policy_in="DROP")
    ST["rules"]["cluster"].append({"type": "in", "action": "ACCEPT", "dport": "8006", "proto": "tcp", "enable": 1})
    assert put(c, cid, "cluster", 0, comment="ok", acknowledge_live=True).status_code == 200


def test_missing_policy_in_defaults_to_restrictive(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1                      # policy_in absente : Proxmox applique DROP
    ST["rules"]["cluster"].append({"type": "in", "action": "ACCEPT", "dport": "22", "proto": "tcp", "enable": 1})
    assert delete(c, cid, "cluster", 0, acknowledge_live=True).status_code == 409


def test_guest_blocking_rule_is_only_live(api):
    c, cid = api
    ST["opts"]["cluster"]["enable"] = 1; ST["opts"]["guest"]["enable"] = 1
    assert post(c, cid, "guest", enable=True, acknowledge_live=True, **ADMIN_DROP).status_code == 200


def test_level_enabled_but_cluster_disabled_is_inert(api):
    c, cid = api
    ST["opts"]["guest"]["enable"] = 1
    assert post(c, cid, "guest", type="in", action="DROP", enable=True).status_code == 200


def test_moving_alone_accept_is_a_cut(api):
    c, cid = api
    ST["opts"]["cluster"].update(enable=1, policy_in="DROP")
    ST["rules"]["cluster"] += [{"type": "in", "action": "ACCEPT", "dport": "8006", "proto": "tcp", "enable": 1}, {"type": "in", "action": "ACCEPT", "dport": "80", "proto": "tcp", "enable": 1}]
    assert move(c, cid, "cluster", 0, 1, acknowledge_live=True).status_code == 409


def test_plus_ipset_needs_a_name(api):
    c, cid = api
    assert post(c, cid, "guest", type="in", action="ACCEPT", source="+10.0.0.1").status_code == 422
