import copy
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
PHRASE = "COUPURE POSSIBLE"
B = "/api/connections/{}/nodes/enzo/network"
WRITES: list[tuple[str, str, dict]] = []
ST: dict = {}
ALLOWED = {"type", "iface", "cidr", "cidr6", "gateway", "gateway6", "mtu", "comments", "bridge_ports", "bridge_vlan_aware", "bridge_vids", "slaves", "bond_mode",
           "bond_xmit_hash_policy", "bond-primary", "autostart", "vlan-id", "vlan-raw-device", "delete"}


def fresh():
    ST.clear()
    ST["ifs"] = [
        {"iface": "nic0", "type": "eth", "active": 1, "autostart": 1},
        {"iface": "nic1", "type": "eth", "active": 1},
        {"iface": "nic2", "type": "eth", "active": 1},
        {"iface": "vmbr0", "type": "bridge", "active": 1, "autostart": 1, "cidr": "192.168.1.200/24", "gateway": "192.168.1.1", "bridge_ports": "nic0"},
    ]
    ST["base"] = copy.deepcopy(ST["ifs"])
    ST["changes"] = None


def diff():
    return "--- a\n+++ b\n" + "\n".join(f"+iface {i['iface']}" for i in ST["ifs"] if i not in ST["base"]) + "\n" + "\n".join(f"-iface {i['iface']}" for i in ST["base"] if i not in ST["ifs"])


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    m = request.method
    if not p.startswith("/nodes/enzo/network"):
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    name = p.removeprefix("/nodes/enzo/network").strip("/")
    if m == "GET":
        return httpx.Response(200, json={"data": copy.deepcopy(ST["ifs"]), "changes": ST["changes"]})
    if ST.get("fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    bad = set(body) - ALLOWED
    if bad:
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(bad)}"})
    WRITES.append((m, name, body))
    if ST.get("noapply"):
        return httpx.Response(200, json={"data": None})
    if m == "POST":
        if "type" not in body or "iface" not in body or any(i["iface"] == body["iface"] for i in ST["ifs"]):
            return httpx.Response(400, json={"data": None, "message": "type/iface"})
        ST["ifs"].append({k.replace("-", "_") if False else k: (int(v) if k in ("mtu", "autostart", "bridge_vlan_aware") else v) for k, v in body.items()})
    elif m == "PUT" and name:
        if "type" not in body:
            return httpx.Response(400, json={"data": None, "message": "type requis"})
        i = next(x for x in ST["ifs"] if x["iface"] == name)
        for k in [x for x in body.get("delete", "").split(",") if x]:
            i.pop(k, None)
        i.update({k: (int(v) if k in ("mtu", "autostart", "bridge_vlan_aware") else v) for k, v in body.items() if k not in ("delete",)})
    elif m == "DELETE" and name:
        ST["ifs"] = [x for x in ST["ifs"] if x["iface"] != name]
    elif m == "PUT":
        ST["base"] = copy.deepcopy(ST["ifs"]); ST["changes"] = None
        return httpx.Response(200, json={"data": "UPID:enzo:0001:0002:0003:ifreload:enzo:root@pam:"})
    elif m == "DELETE":
        if ST.get("norevert"):
            return httpx.Response(200, json={"data": None})
        ST["ifs"] = copy.deepcopy(ST["base"]); ST["changes"] = None
        return httpx.Response(200, json={"data": None})
    ST["changes"] = diff()
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    WRITES.clear(); fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def create(c, cid, **b):
    return c.post(B.format(cid) + "/interfaces", json={"confirm": True, **b})


def update(c, cid, name, **b):
    return c.put(B.format(cid) + f"/interfaces/{name}", json={"confirm": True, **b})


def delete(c, cid, name, **q):
    return c.delete(B.format(cid) + f"/interfaces/{name}", params={"confirm": True, **q})


def apply(c, cid, **b):
    return c.post(B.format(cid) + "/apply", json={"confirm": True, **b})


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


def test_create_bridge_is_staged_not_applied(api):
    c, cid = api
    r = create(c, cid, type="bridge", iface="vmbr1", comments="lab", bridge_ports=["nic1"], bridge_vlan_aware=True)
    assert r.status_code == 200, r.text
    assert r.json()["staged"] and r.json()["applied"] is False and r.json()["pending"]
    m, name, body = WRITES[0]
    assert (m, name) == ("POST", "") and body["bridge_ports"] == "nic1" and body["bridge_vlan_aware"] == "1" and body["type"] == "bridge"
    assert not any(w[0] == "PUT" and w[1] == "" for w in WRITES)             # jamais d'application par une préparation


def test_requires_confirm_and_dry_run_writes_nothing(api):
    c, cid = api
    r = c.post(B.format(cid) + "/interfaces", json={"type": "bridge", "iface": "vmbr1"})
    assert r.status_code == 400 and not WRITES
    r = c.post(B.format(cid) + "/interfaces", json={"dry_run": True, "type": "bridge", "iface": "vmbr1"})
    assert r.status_code == 200 and r.json()["dry_run"] and not WRITES


@pytest.mark.parametrize("bad", [
    {"type": "bridge", "iface": "br0"}, {"type": "bridge", "iface": "vmbr12345"}, {"type": "bond", "iface": "vmbr1"}, {"type": "vlan", "iface": "foo"}, {"type": "eth", "iface": "nic9"},
    {"type": "bridge", "iface": "vmbr1", "cidr": "10.0.0.2"}, {"type": "bridge", "iface": "vmbr1", "cidr": "999.0.0.1/24"}, {"type": "bridge", "iface": "vmbr1", "cidr": "fe80::1/64"},
    {"type": "bridge", "iface": "vmbr1", "cidr6": "10.0.0.1/24"}, {"type": "bridge", "iface": "vmbr1", "gateway": "10.0.0.1"},
    {"type": "bridge", "iface": "vmbr1", "cidr": "10.0.0.2/24", "gateway": "10.1.0.1"}, {"type": "bridge", "iface": "vmbr1", "gateway": "x"},
    {"type": "bridge", "iface": "vmbr1", "mtu": 100}, {"type": "bridge", "iface": "vmbr1", "mtu": "1500"}, {"type": "bridge", "iface": "vmbr1", "comments": "a\nb"},
    {"type": "bridge", "iface": "vmbr1", "bridge_ports": ["nope"]}, {"type": "bridge", "iface": "vmbr1", "bridge_ports": ["nic1", "nic1"]},
    {"type": "bridge", "iface": "vmbr1", "bridge_ports": ["nic0"]}, {"type": "bridge", "iface": "vmbr1", "bridge_ports": ["nic1;x"]},
    {"type": "bridge", "iface": "vmbr1", "bridge_vids": "2-4094"}, {"type": "bridge", "iface": "vmbr1", "bridge_vlan_aware": True, "bridge_vids": "0-5"},
    {"type": "bridge", "iface": "vmbr1", "bridge_vlan_aware": True, "bridge_vids": "5000"}, {"type": "bridge", "iface": "vmbr1", "bridge_vlan_aware": "true"},
    {"type": "bridge", "iface": "vmbr1", "slaves": ["nic1"]}, {"type": "bridge", "iface": "vmbr1", "bond_mode": "802.3ad"},
    {"type": "bond", "iface": "bond0", "slaves": ["vmbr0"]}, {"type": "bond", "iface": "bond0", "slaves": ["nic1"], "bond_mode": "bogus"},
    {"type": "bond", "iface": "bond0", "slaves": ["nic1"], "bond_primary": "nic2"}, {"type": "bond", "iface": "bond0", "bridge_ports": ["nic1"]},
    {"type": "vlan", "iface": "nic1.100", "vlan_id": 200}, {"type": "vlan", "iface": "vlan100"}, {"type": "vlan", "iface": "nope.100"}, {"type": "vlan", "iface": "nic1.100", "vlan_id": 5000},
    {"type": "vmbr"}, {"iface": "vmbr1"}, {"type": "bridge", "iface": "vmbr0"},
])
def test_invalid_rejected_without_echo_or_write(api, bad):
    c, cid = api
    r = create(c, cid, **bad)
    assert r.status_code in (409, 422) and not WRITES, (bad, r.status_code, r.text)
    assert SECRET not in r.text


def test_valid_variants(api):
    c, cid = api
    assert create(c, cid, type="bond", iface="bond0", slaves=["nic1", "nic2"], bond_mode="802.3ad", bond_xmit_hash_policy="layer2+3", bond_primary="nic1").status_code == 200
    assert WRITES[-1][2]["bond-primary"] == "nic1" and WRITES[-1][2]["slaves"] == "nic1 nic2"
    assert create(c, cid, type="vlan", iface="nic1.100").status_code == 200
    assert create(c, cid, type="vlan", iface="vlan200", vlan_id=200, vlan_raw_device="nic1").status_code == 200
    assert WRITES[-1][2]["vlan-id"] == "200" and WRITES[-1][2]["vlan-raw-device"] == "nic1"
    assert create(c, cid, type="bridge", iface="vmbr2", cidr="10.9.0.2/24", gateway="10.9.0.1", cidr6="2001:db8::2/64", gateway6="2001:db8::1", mtu=1500, bridge_ports=["bond0"]).status_code in (200, 409)


def test_bridge_port_already_used_is_refused(api):
    c, cid = api
    assert create(c, cid, type="bridge", iface="vmbr1", bridge_ports=["nic1"]).status_code == 200
    r = create(c, cid, type="bridge", iface="vmbr2", bridge_ports=["nic1"])
    assert r.status_code == 422 and "déjà utilisé" in r.json()["detail"]


def test_unknown_fields_never_forwarded(api):
    c, cid = api
    assert create(c, cid, type="bridge", iface="vmbr1", evil="x", delete="x").status_code == 200
    assert set(WRITES[0][2]) == {"type", "iface"}


def test_admin_interface_staging_needs_cut_lock(api):
    c, cid = api
    for name in ("vmbr0", "nic0"):
        r = update(c, cid, name, comments="x")
        assert r.status_code == 409 and "administration" in r.json()["detail"], name
    assert not WRITES
    assert update(c, cid, "vmbr0", comments="x", acknowledge_cut_access=True).status_code == 409           # phrase manquante
    assert update(c, cid, "vmbr0", comments="x", acknowledge_cut_access=True, type_name="coupure possible").status_code == 409
    r = update(c, cid, "vmbr0", comments="x", acknowledge_cut_access=True, type_name=PHRASE)
    assert r.status_code == 200 and WRITES[-1][0] == "PUT" and WRITES[-1][1] == "vmbr0" and WRITES[-1][2]["type"] == "bridge"
    assert not any(w[1] == "" and w[0] == "PUT" for w in WRITES)


def test_moving_gateway_to_other_interface_needs_cut(api):
    c, cid = api
    create(c, cid, type="bridge", iface="vmbr1", cidr="10.0.0.2/24")
    r = update(c, cid, "vmbr1", gateway="10.0.0.1")
    assert r.status_code == 409 and "passerelle" in r.json()["detail"]
    assert update(c, cid, "vmbr1", mtu=1500).status_code == 200


def test_delete_rules(api):
    c, cid = api
    assert delete(c, cid, "nope").status_code == 404
    assert delete(c, cid, "nic0").status_code in (409, 422)                    # port de vmbr0 : jamais sans retirer d'abord
    assert delete(c, cid, "vmbr0").status_code == 409                          # interface d'administration : verrou
    assert c.delete(B.format(cid) + "/interfaces/vmbr0").status_code == 400
    create(c, cid, type="bridge", iface="vmbr1")
    assert delete(c, cid, "vmbr1", dry_run=True).json()["dry_run"]
    assert delete(c, cid, "vmbr1").status_code == 200 and all(i["iface"] != "vmbr1" for i in ST["ifs"])
    assert delete(c, cid, "vmbr0", acknowledge_cut_access=True, type_name=PHRASE).status_code == 200


def test_update_clear_and_wire_names(api):
    c, cid = api
    create(c, cid, type="bond", iface="bond0", slaves=["nic1", "nic2"], bond_primary="nic1", comments="old")
    assert update(c, cid, "bond0", clear=["bond_primary", "comments"]).status_code == 200
    assert WRITES[-1][2]["delete"] == "bond-primary,comments"
    assert update(c, cid, "bond0", comments="x", clear=["comments"]).status_code == 422
    assert update(c, cid, "bond0", clear=["type"]).status_code == 422
    assert update(c, cid, "bond0").status_code == 422
    assert update(c, cid, "nope", comments="x").status_code == 404


def test_update_of_unmanaged_type_refused(api):
    c, cid = api
    ST["ifs"].append({"iface": "ovs0", "type": "OVSBridge"})
    assert update(c, cid, "ovs0", comments="x").status_code == 422


def test_apply_needs_pending(api):
    c, cid = api
    assert apply(c, cid, acknowledge_live=True).status_code == 409 and not WRITES


def test_apply_locks(api):
    c, cid = api
    create(c, cid, type="bridge", iface="vmbr1")
    assert apply(c, cid).status_code == 409                                    # acknowledge_live manquant
    assert apply(c, cid, acknowledge_live="true").status_code == 422
    d = c.post(B.format(cid) + "/apply", json={"dry_run": True}).json()
    assert d["dry_run"] and "vmbr1" in d["changes"] and not d["locks"]["cut"]
    n = len(WRITES)
    r = apply(c, cid, acknowledge_live=True)
    assert r.status_code == 200 and r.json()["applied"] and r.json()["task"].startswith("UPID:") and WRITES[n:] == [("PUT", "", {})]
    assert ST["changes"] is None


def test_apply_touching_admin_needs_phrase(api):
    c, cid = api
    update(c, cid, "vmbr0", comments="x", acknowledge_cut_access=True, type_name=PHRASE)
    ST["changes"] = "--- a\n+++ b\n+\tcomments x\n iface vmbr0 inet static"          # diff qui nomme vmbr0
    r = apply(c, cid, acknowledge_live=True)
    assert r.status_code == 409 and "administration" in r.json()["detail"]
    assert apply(c, cid, acknowledge_cut_access=True, type_name=PHRASE).status_code == 200


def test_apply_removed_gateway_in_diff_needs_phrase(api):
    c, cid = api
    create(c, cid, type="bridge", iface="vmbr1")
    ST["changes"] = "--- a\n+++ b\n-\tgateway 192.168.1.1\n"
    assert apply(c, cid, acknowledge_live=True).status_code == 409


def test_revert(api):
    c, cid = api
    assert c.post(B.format(cid) + "/revert", json={"confirm": True}).status_code == 409
    create(c, cid, type="bridge", iface="vmbr1")
    assert c.post(B.format(cid) + "/revert", json={}).status_code == 400
    assert c.post(B.format(cid) + "/revert", json={"dry_run": True}).json()["dry_run"] and len(ST["ifs"]) == 5
    assert c.post(B.format(cid) + "/revert", json={"confirm": True}).json()["reverted"] and len(ST["ifs"]) == 4


def test_not_saved_is_502_and_audited(api):
    c, cid = api
    ST["noapply"] = True
    assert create(c, cid, type="bridge", iface="vmbr1").status_code == 502
    assert ("net-create", "error") in audit_pairs(c)


def test_errors_never_leak_secret_and_are_audited(api):
    c, cid = api
    ST["fail"] = True
    r = create(c, cid, type="bridge", iface="vmbr1")
    assert r.status_code >= 400 and SECRET not in r.text and SECRET not in str(c.get("/api/audit").json())


def test_audit_success_and_refusal(api):
    c, cid = api
    create(c, cid, type="bridge", iface="vmbr1")
    update(c, cid, "vmbr0", comments="x")
    apply(c, cid, acknowledge_live=True)
    pairs = audit_pairs(c)
    assert ("net-create", "started") in pairs and ("net-update", "error") in pairs


def test_requires_login(client):
    assert client.post("/api/connections/1/nodes/enzo/network/apply", json={"confirm": True}).status_code == 401


def drop_gateway():
    for i in ST["ifs"]:
        i.pop("gateway", None)
    ST["base"] = copy.deepcopy(ST["ifs"])


def test_gateway_without_other_gateway_is_not_a_cut(api):
    c, cid = api
    drop_gateway()
    create(c, cid, type="bridge", iface="vmbr1", cidr="10.0.0.2/24")
    assert update(c, cid, "vmbr1", gateway="10.0.0.1").status_code == 200


def test_gateway_outside_network_refused(api):
    c, cid = api
    drop_gateway()
    r = create(c, cid, type="bridge", iface="vmbr1", cidr="10.0.0.2/24", gateway="10.1.0.1")
    assert r.status_code == 422 and "réseau" in r.json()["detail"]
    r = create(c, cid, type="bridge", iface="vmbr1", cidr6="2001:db8::2/64", gateway6="2001:db9::1")
    assert r.status_code == 422 and "réseau" in r.json()["detail"]
    assert create(c, cid, type="bridge", iface="vmbr1", gateway="10.0.0.1").status_code == 422


def test_duplicate_create_is_409_without_write(api):
    c, cid = api
    assert create(c, cid, type="bridge", iface="vmbr1").status_code == 200
    n = len(WRITES)
    r = create(c, cid, type="bridge", iface="vmbr1")
    assert r.status_code == 409 and "existe" in r.json()["detail"] and len(WRITES) == n


def test_delete_port_in_use_refused(api):
    c, cid = api
    create(c, cid, type="bridge", iface="vmbr1", bridge_ports=["nic1"])
    r = delete(c, cid, "nic1")
    assert r.status_code == 409 and "Utilisée" in r.json()["detail"]
    create(c, cid, type="vlan", iface="vlan50", vlan_id=50, vlan_raw_device="nic2")
    r = delete(c, cid, "nic2")
    assert r.status_code == 409 and "vlan50" in r.json()["detail"]


def test_management_follows_ports_slaves_vlans_and_gateway6(api):
    c, cid = api
    ST["ifs"] = [{"iface": n, "type": "eth"} for n in ("nic0", "nic1", "nic2", "nic3")] + [
        {"iface": "bond0", "type": "bond", "slaves": "nic1 nic2"}, {"iface": "vmbr0", "type": "bridge", "bridge_ports": "bond0", "cidr": "10.0.0.2/24", "gateway": "10.0.0.1"},
        {"iface": "nic3.5", "type": "vlan", "vlan-id": 5, "vlan-raw-device": "nic3", "cidr6": "2001:db8::2/64", "gateway6": "2001:db8::1"}]
    ST["base"] = copy.deepcopy(ST["ifs"])
    for name in ("vmbr0", "bond0", "nic1", "nic2", "nic3.5", "nic3"):
        r = update(c, cid, name, comments="x")
        assert r.status_code == 409 and "administration" in r.json()["detail"], name
    assert update(c, cid, "nic0", comments="x").status_code == 200


def test_apply_diff_word_boundaries_and_removals(api):
    c, cid = api
    create(c, cid, type="bridge", iface="vmbr1")
    ST["changes"] = "--- a\n+++ b\n+iface vmbr01 inet manual\n+iface xvmbr0 inet manual\n"
    assert apply(c, cid, acknowledge_live=True).status_code == 200
    for line in ("-\tbridge-ports nic1", "-\tbond-slaves nic1 nic2", "-iface vmbr1 inet manual", "-iface bond0 inet manual", "-\tgateway6 fe80::1"):
        create(c, cid, type="bridge", iface="vmbr1")
        ST["changes"] = "--- a\n+++ b\n" + line + "\n"
        r = apply(c, cid, acknowledge_live=True)
        assert r.status_code == 409 and "Coupure" in r.json()["detail"], line
        c.post(B.format(cid) + "/revert", json={"confirm": True})


def test_vids_shape(api):
    c, cid = api
    r = create(c, cid, type="bridge", iface="vmbr1", bridge_vlan_aware=True, bridge_vids="1-2-3")
    assert r.status_code == 422 and not WRITES
    assert create(c, cid, type="bridge", iface="vmbr1", bridge_vlan_aware=True, bridge_vids="2-4094 10").status_code == 200


def test_revert_not_applied_is_502(api):
    c, cid = api
    create(c, cid, type="bridge", iface="vmbr1")
    ST["norevert"] = True
    assert c.post(B.format(cid) + "/revert", json={"confirm": True}).status_code == 502
