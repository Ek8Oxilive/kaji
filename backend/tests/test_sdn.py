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
B = "/api/connections/{}/sdn"
DIGEST = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
WRITES: list[tuple[str, str, dict]] = []
ST: dict = {}
ZONE_OK = {"zone", "type", "nodes", "mtu", "ipam", "dns", "reversedns", "dnszone", "dhcp", "bridge", "tag", "vlan-protocol", "peers", "vxlan-port", "controller", "vrf-vxlan", "exitnodes",
           "exitnodes-primary", "exitnodes-local-routing", "advertise-subnets", "disable-arp-nd-suppression", "rt-import", "delete", "digest"}
VNET_OK = {"vnet", "zone", "alias", "tag", "vlanaware", "isolate-ports", "delete", "digest"}
SUB_OK = {"subnet", "type", "gateway", "snat", "dhcp-dns-server", "dnszoneprefix", "dhcp-range", "delete", "digest", "vnet"}
BOOLS = {"exitnodes-local-routing", "advertise-subnets", "disable-arp-nd-suppression", "vlanaware", "isolate-ports", "snat"}
INTS = {"mtu", "tag", "vxlan-port", "vrf-vxlan"}


def fresh():
    ST.clear()
    ST["run"] = {"zones": {}, "vnets": {}, "subnets": {}}
    ST["pend"] = copy.deepcopy(ST["run"])          # configuration en attente complète
    ST["deleted"] = {"zones": set(), "vnets": set(), "subnets": set()}


def conv(k, v):
    return (int(v) if k in BOOLS or k in INTS else v)


def listing(kind, idkey, vnet=None):
    out = []
    run, pend = ST["run"][kind], ST["pend"][kind]
    for i, cfg in pend.items():
        if kind == "subnets" and cfg["_vnet"] != vnet:
            continue
        item = {k: v for k, v in cfg.items() if not k.startswith("_")}
        if i not in run:
            out.append({idkey: i, **item, "state": "new", "digest": DIGEST})
        elif {k: v for k, v in run[i].items()} != cfg:
            diff = {k: v for k, v in item.items() if run[i].get(k) != v}
            base = {k: v for k, v in run[i].items() if not k.startswith("_")}
            out.append({idkey: i, **base, "pending": diff, "state": "deleted" if i in ST["deleted"][kind] else "changed", "digest": DIGEST})
        else:
            out.append({idkey: i, **item, "digest": DIGEST})
    for i in ST["deleted"][kind]:
        if i in run and i not in pend and (kind != "subnets" or run[i]["_vnet"] == vnet):
            out.append({idkey: i, **{k: v for k, v in run[i].items() if not k.startswith("_")}, "state": "deleted", "digest": DIGEST})
    return out


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
    raw = parse_qs(request.content.decode(), keep_blank_values=True)
    body = {k: (v if k == "dhcp-range" else v[0]) for k, v in raw.items()}
    m = request.method
    parts = p.strip("/").split("/")                            # cluster sdn <kind> [id] [subnets [sid]]
    if parts[:2] != ["cluster", "sdn"]:
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if m != "GET" and ST.get("fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    if len(parts) == 2 and m == "PUT":
        WRITES.append((m, p, body))
        ST["run"] = copy.deepcopy(ST["pend"])
        for k in ST["deleted"]:
            ST["deleted"][k].clear()
        return httpx.Response(200, json={"data": "UPID:enzo:0001:0002:0003:reloadnetworkall:root@pam:"})
    if parts[2:] == ["rollback"] and m == "POST":
        WRITES.append((m, p, body))
        if not ST.get("norollback"):
            ST["pend"] = copy.deepcopy(ST["run"])
            for k in ST["deleted"]:
                ST["deleted"][k].clear()
        return httpx.Response(200, json={"data": None})
    kind = parts[2]
    if kind not in ("zones", "vnets"):
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if kind == "zones":
        store, ok, idkey = "zones", ZONE_OK, "zone"
    else:
        store, ok, idkey = "vnets", VNET_OK, "vnet"
    sub = len(parts) >= 5 and parts[4] == "subnets"
    if sub:
        vnet, store, ok, idkey = parts[3], "subnets", SUB_OK, "subnet"
        if vnet not in ST["pend"]["vnets"]:
            # le vrai Proxmox met son message dans la phrase de raison HTTP (c'est ce que Kaji relit)
            return httpx.Response(500, json={"data": None}, extensions={"reason_phrase": f"sdn vnet '{vnet}' does not exist".encode()})
        sid = parts[5] if len(parts) > 5 else None
    else:
        sid = parts[3] if len(parts) > 3 else None
        vnet = None
    if m == "GET":
        if sub and ST.get("sub_fail"):
            return httpx.Response(500, json={"data": None}, extensions={"reason_phrase": b"cluster file system unavailable"})
        if sid:
            return httpx.Response(501, json={"data": None})
        return httpx.Response(200, json={"data": listing(store, idkey, vnet)})
    bad = set(body) - ok
    if bad or any(body.get(k) not in ("0", "1") for k in set(body) & BOOLS) or any(not body[k].isdigit() for k in set(body) & INTS):
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(bad)}"})
    # constaté en réel (Proxmox 9, 2026-11-13) : `vnet` est un paramètre OBLIGATOIRE du corps pour CRÉER un sous-réseau (en plus du chemin) ;
    # sans lui : « create sdn subnet object failed: 400 Parameter verification failed »
    if sub and m == "POST" and body.get("vnet") != vnet:
        return httpx.Response(400, json={"data": None, "message": "Parameter verification failed: vnet manquant dans le corps"})
    if m != "POST" and body.get("digest") not in (None, DIGEST):
        return httpx.Response(400, json={"data": None, "message": "digest"})
    WRITES.append((m, p, body))
    if ST.get("noapply"):
        return httpx.Response(200, json={"data": None})
    pend = ST["pend"][store]
    cfg = {k: (conv(k, v) if k != "dhcp-range" else v) for k, v in body.items() if (k not in (idkey, "delete", "digest", "type") and not (store == "subnets" and k == "vnet")) or (k == "type" and store == "zones")}
    if m == "POST":
        i = body[idkey]
        if i in pend:
            return httpx.Response(400, json={"data": None, "message": "exists"})
        if store == "subnets":
            cfg["_vnet"] = vnet
        pend[i] = cfg
    elif m == "PUT":
        c = pend[sid]
        for k in [x for x in body.get("delete", "").split(",") if x]:
            c.pop(k, None)
        c.update(cfg)
    else:
        if sid in ST["run"][store]:
            ST["deleted"][store].add(sid)
        pend.pop(sid, None)
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    WRITES.clear(); fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def call(c, cid, method, path, **b):
    if method == "DELETE":
        return c.delete(B.format(cid) + path, params={"confirm": True, **b})
    return c.request(method, B.format(cid) + path, json={"confirm": True, **b})


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


def mkzone(c, cid, zone="z1", **b):
    return call(c, cid, "POST", "/zones", zone=zone, type=b.pop("type", "simple"), **b)


def test_subnet_creation_sends_vnet_in_the_body(api):
    # constaté en réel (Proxmox 9, 2026-11-13) : sans `vnet` dans le corps, « create sdn subnet object failed: 400 Parameter verification failed »
    c, cid = api
    mkzone(c, cid)
    call(c, cid, "POST", "/vnets", vnet="v1", zone="z1")
    assert call(c, cid, "POST", "/vnets/v1/subnets", subnet="10.99.0.0/24", gateway="10.99.0.1").status_code == 200
    body = WRITES[-1][2]
    assert body["vnet"] == "v1" and body["subnet"] == "z1-10.99.0.0-24" and body["type"] == "subnet"


def test_subnets_of_unknown_vnet_is_404_not_502(api):
    c, cid = api
    r = c.get(B.format(cid) + "/vnets/nope/subnets")
    assert r.status_code == 404 and r.json()["detail"] == "VNet inconnu"


def test_other_subnet_read_failures_stay_errors(api):
    c, cid = api
    mkzone(c, cid)
    call(c, cid, "POST", "/vnets", vnet="v1", zone="z1")
    ST["sub_fail"] = True
    r = c.get(B.format(cid) + "/vnets/v1/subnets")
    assert r.status_code == 502 and "VNet inconnu" not in r.text


def test_full_stack_is_staged_not_applied(api):
    c, cid = api
    assert mkzone(c, cid).status_code == 200
    r = call(c, cid, "POST", "/vnets", vnet="v1", zone="z1", alias="réseau test", vlanaware=True)
    assert r.status_code == 200, r.text
    r = call(c, cid, "POST", "/vnets/v1/subnets", subnet="10.99.0.0/24", gateway="10.99.0.1", snat=True, dhcp_range=[{"start": "10.99.0.10", "end": "10.99.0.50"}])
    assert r.status_code == 200, r.text
    assert r.json()["subnet"] == "z1-10.99.0.0-24"
    assert WRITES[-1][2]["dhcp-range"] == ["start-address=10.99.0.10,end-address=10.99.0.50"] and WRITES[-1][2]["snat"] == "1"
    assert not any(w[0] == "PUT" and w[1] == "/cluster/sdn" for w in WRITES)
    assert [z["state"] for z in c.get(B.format(cid) + "/zones").json()] == ["new"]
    assert c.get(B.format(cid) + "/vnets/v1/subnets").json()[0]["subnet"] == "z1-10.99.0.0-24"


def test_requires_confirm_and_dry_run(api):
    c, cid = api
    assert c.post(B.format(cid) + "/zones", json={"zone": "z1", "type": "simple"}).status_code == 400 and not WRITES
    r = c.post(B.format(cid) + "/zones", json={"dry_run": True, "zone": "z1", "type": "simple"})
    assert r.status_code == 200 and r.json()["dry_run"] and not WRITES


@pytest.mark.parametrize("bad", [
    {"zone": "Z1"}, {"zone": "z-1"}, {"zone": "toolongzone"}, {"zone": "1z"}, {"type": "faucet"}, {"type": "vlan"}, {"type": "qinq", "bridge": "vmbr0"}, {"type": "vxlan"},
    {"type": "evpn", "controller": "c"}, {"type": "simple", "bridge": "vmbr0"}, {"type": "vlan", "bridge": "vmbr0 x"}, {"type": "vlan", "bridge": "vmbr0", "tag": 5000},
    {"type": "vlan", "bridge": "vmbr0", "mtu": 10}, {"type": "vlan", "bridge": "vmbr0", "mtu": "1500"}, {"type": "vxlan", "peers": ["x"]}, {"type": "vxlan", "peers": ["10.0.0.1", "10.0.0.1"]},
    {"type": "vlan", "bridge": "vmbr0", "nodes": ["a b"]}, {"type": "vlan", "bridge": "vmbr0", "nodes": ["a", "a"]}, {"type": "vlan", "bridge": "vmbr0", "dnszone": "bad name"},
    {"type": "vlan", "bridge": "vmbr0", "dhcp": "kea"}, {"type": "evpn", "controller": "c", "vrf_vxlan": 1, "exitnodes": ["a"], "exitnodes_primary": "b"},
    {"type": "evpn", "controller": "c", "vrf_vxlan": 1, "rt_import": ["x"]}, {"type": "vlan", "bridge": "vmbr0", "vxlan_port": 4789},
    {"type": "vlan", "bridge": "vmbr0", "advertise_subnets": "true"}, {"type": "vlan", "bridge": "vmbr0", "ipam": "bad;name"},
])
def test_zone_invalid_rejected_without_write_or_echo(api, bad):
    c, cid = api
    body = {"zone": "z1", "type": "simple", **bad}
    r = call(c, cid, "POST", "/zones", **body)
    assert r.status_code == 422 and not WRITES, (bad, r.status_code, r.text)
    assert SECRET not in r.text


def test_zone_valid_per_type(api):
    c, cid = api
    assert mkzone(c, cid, "zv", type="vlan", bridge="vmbr0", nodes=["enzo", "enzo2"], mtu=1500, dhcp="dnsmasq").status_code == 200
    assert WRITES[-1][2]["nodes"] == "enzo,enzo2" and WRITES[-1][2]["mtu"] == "1500"
    assert mkzone(c, cid, "zq", type="qinq", bridge="vmbr0", tag=100, vlan_protocol="802.1ad").status_code == 200
    assert mkzone(c, cid, "zx", type="vxlan", peers=["10.0.0.1", "10.0.0.2"], vxlan_port=4789).status_code == 200
    assert mkzone(c, cid, "ze", type="evpn", controller="ctl", vrf_vxlan=4000, exitnodes=["enzo"], exitnodes_primary="enzo", advertise_subnets=True, rt_import=["65000:1"]).status_code == 200
    assert WRITES[-1][2]["rt-import"] == "65000:1" and WRITES[-1][2]["advertise-subnets"] == "1"


def test_duplicate_zone_409_and_unknown_fields_ignored(api):
    c, cid = api
    assert mkzone(c, cid, evil="x", digest="x").status_code == 200
    assert set(WRITES[0][2]) == {"zone", "type"}
    n = len(WRITES)
    assert mkzone(c, cid).status_code == 409 and len(WRITES) == n


def test_zone_update_clear_and_digest(api):
    c, cid = api
    mkzone(c, cid, "zv", type="vlan", bridge="vmbr0", mtu=1500)
    ST["run"] = copy.deepcopy(ST["pend"])
    r = call(c, cid, "PUT", "/zones/zv", mtu=1400, clear=[])
    assert r.status_code == 200 and WRITES[-1][2]["digest"] == DIGEST and WRITES[-1][2]["mtu"] == "1400"
    assert call(c, cid, "PUT", "/zones/zv", clear=["mtu"]).status_code == 200 and WRITES[-1][2]["delete"] == "mtu"
    assert call(c, cid, "PUT", "/zones/zv", mtu=1400, clear=["mtu"]).status_code == 422
    assert call(c, cid, "PUT", "/zones/zv", clear=["type"]).status_code == 422
    assert call(c, cid, "PUT", "/zones/zv", clear=["bridge"]).status_code == 422              # exigé par le type vlan
    assert call(c, cid, "PUT", "/zones/zv", vxlan_port=1).status_code == 422                   # champ d'un autre type
    assert call(c, cid, "PUT", "/zones/zv").status_code == 422
    assert call(c, cid, "PUT", "/zones/nope", mtu=1400).status_code == 404


def test_zone_delete_rules(api):
    c, cid = api
    mkzone(c, cid)
    call(c, cid, "POST", "/vnets", vnet="v1", zone="z1")
    r = call(c, cid, "DELETE", "/zones/z1")
    assert r.status_code == 409 and "v1" in r.json()["detail"]
    assert call(c, cid, "DELETE", "/vnets/v1").status_code == 200
    assert call(c, cid, "DELETE", "/zones/z1", dry_run=True).json()["dry_run"] and "z1" in ST["pend"]["zones"]
    assert c.delete(B.format(cid) + "/zones/z1").status_code == 400
    assert call(c, cid, "DELETE", "/zones/z1").status_code == 200 and "z1" not in ST["pend"]["zones"]
    assert call(c, cid, "DELETE", "/zones/zz").status_code == 404


@pytest.mark.parametrize("bad", [
    {"vnet": "V1"}, {"vnet": "v-1"}, {"zone": "nope"}, {"zone": "Z1"}, {"alias": "a\nb"}, {"alias": "x" * 257}, {"tag": 0}, {"tag": 5000}, {"vlanaware": "true"}, {"isolate_ports": 1},
])
def test_vnet_invalid(api, bad):
    c, cid = api
    mkzone(c, cid, "zv", type="vlan", bridge="vmbr0")
    n = len(WRITES)
    r = call(c, cid, "POST", "/vnets", **{"vnet": "v1", "zone": "zv", "tag": 10, **bad})
    assert r.status_code == 422 and len(WRITES) == n, (bad, r.status_code, r.text)


def test_vnet_tag_rules_by_zone_type(api):
    c, cid = api
    mkzone(c, cid, "zv", type="vlan", bridge="vmbr0"); mkzone(c, cid, "zs")
    assert call(c, cid, "POST", "/vnets", vnet="v1", zone="zv").status_code == 422             # tag exigé
    assert call(c, cid, "POST", "/vnets", vnet="v1", zone="zv", tag=100).status_code == 200
    assert call(c, cid, "POST", "/vnets", vnet="v2", zone="zs", tag=100).status_code == 422    # pas de tag en zone simple
    assert call(c, cid, "POST", "/vnets", vnet="v3", zone="zs").status_code == 200
    assert call(c, cid, "POST", "/vnets", vnet="v1", zone="zs").status_code == 409


def test_vnet_update_delete_and_subnet_guard(api):
    c, cid = api
    mkzone(c, cid, "zs")
    call(c, cid, "POST", "/vnets", vnet="v1", zone="zs", alias="old")
    assert call(c, cid, "PUT", "/vnets/v1", alias="new", vlanaware=True).status_code == 200
    assert call(c, cid, "PUT", "/vnets/v1", clear=["alias"]).status_code == 200 and WRITES[-1][2]["delete"] == "alias"
    assert call(c, cid, "PUT", "/vnets/v1", alias="x", clear=["alias"]).status_code == 422
    assert call(c, cid, "PUT", "/vnets/v1", clear=["zone"]).status_code == 422
    assert call(c, cid, "PUT", "/vnets/nope", alias="x").status_code == 404
    call(c, cid, "POST", "/vnets/v1/subnets", subnet="10.1.0.0/24")
    r = call(c, cid, "DELETE", "/vnets/v1")
    assert r.status_code == 409 and "z" in r.json()["detail"]
    call(c, cid, "DELETE", "/vnets/v1/subnets/zs-10.1.0.0-24")
    assert call(c, cid, "DELETE", "/vnets/v1").status_code == 200


@pytest.mark.parametrize("bad", [
    {"subnet": "10.0.0.5/24"}, {"subnet": "10.0.0.0"}, {"subnet": "10.0.0.1/32"}, {"subnet": "nope/24"}, {"gateway": "10.1.0.1"}, {"gateway": "x"}, {"gateway": "fe80::1"},
    {"dhcp_range": [{"start": "10.0.0.50", "end": "10.0.0.10"}], "gateway": "10.0.0.1"}, {"dhcp_range": [{"start": "10.9.0.1", "end": "10.9.0.5"}], "gateway": "10.0.0.1"},
    {"dhcp_range": [{"start": "10.0.0.5", "end": "10.0.0.9"}]}, {"dhcp_dns_server": "x"}, {"dnszoneprefix": "bad name"}, {"snat": "true"},
])
def test_subnet_invalid(api, bad):
    c, cid = api
    mkzone(c, cid); call(c, cid, "POST", "/vnets", vnet="v1", zone="z1")
    n = len(WRITES)
    r = call(c, cid, "POST", "/vnets/v1/subnets", **{"subnet": "10.0.0.0/24", **bad})
    assert r.status_code == 422 and len(WRITES) == n, (bad, r.status_code, r.text)


def test_subnet_overlap_duplicate_and_update(api):
    c, cid = api
    mkzone(c, cid); call(c, cid, "POST", "/vnets", vnet="v1", zone="z1")
    assert call(c, cid, "POST", "/vnets/v1/subnets", subnet="10.0.0.0/24", gateway="10.0.0.1").status_code == 200
    ST["run"] = copy.deepcopy(ST["pend"])
    for s in list(ST["run"]["subnets"].values()):
        s["cidr"] = "10.0.0.0/24"
    ST["pend"] = copy.deepcopy(ST["run"])
    assert call(c, cid, "POST", "/vnets/v1/subnets", subnet="10.0.0.0/24").status_code == 409
    assert call(c, cid, "POST", "/vnets/v1/subnets", subnet="10.0.0.0/25").status_code == 409
    assert call(c, cid, "POST", "/vnets/nope/subnets", subnet="10.5.0.0/24").status_code == 404
    sid = "z1-10.0.0.0-24"
    assert call(c, cid, "PUT", f"/vnets/v1/subnets/{sid}", gateway="10.0.0.254", snat=True).status_code == 200
    assert call(c, cid, "PUT", f"/vnets/v1/subnets/{sid}", gateway="10.7.0.1").status_code == 422
    assert call(c, cid, "PUT", f"/vnets/v1/subnets/{sid}", clear=["gateway"]).status_code == 200
    assert call(c, cid, "PUT", f"/vnets/v1/subnets/{sid}", clear=["cidr"]).status_code == 422
    assert call(c, cid, "PUT", f"/vnets/v1/subnets/z1-10.8.0.0-24", snat=True).status_code == 404


def test_apply_needs_pending(api):
    c, cid = api
    assert call(c, cid, "POST", "/apply", acknowledge_live=True).status_code == 409 and not WRITES


def test_apply_simple_zone_only_live_lock(api):
    c, cid = api
    mkzone(c, cid); call(c, cid, "POST", "/vnets", vnet="v1", zone="z1")
    assert call(c, cid, "POST", "/apply").status_code == 409
    assert call(c, cid, "POST", "/apply", acknowledge_live="true").status_code == 422
    d = c.post(B.format(cid) + "/apply", json={"dry_run": True}).json()
    assert d["dry_run"] and not d["locks"]["cut"] and d["pending"]["zones"] == ["z1"] and d["pending"]["vnets"] == ["v1"]
    n = len(WRITES)
    r = call(c, cid, "POST", "/apply", acknowledge_live=True)
    assert r.status_code == 200 and r.json()["task"].startswith("UPID:") and WRITES[n:] == [("PUT", "/cluster/sdn", {})]


def test_apply_host_zone_and_deletions_need_phrase(api):
    c, cid = api
    mkzone(c, cid, "zv", type="vlan", bridge="vmbr0")
    r = call(c, cid, "POST", "/apply", acknowledge_live=True)
    assert r.status_code == 409 and "zv" in r.json()["detail"] and "Coupure" in r.json()["detail"]
    assert call(c, cid, "POST", "/apply", acknowledge_cut_access=True, type_name="coupure possible").status_code == 409
    assert call(c, cid, "POST", "/apply", acknowledge_cut_access=True, type_name=PHRASE).status_code == 200
    mkzone(c, cid, "zs"); call(c, cid, "POST", "/vnets", vnet="v1", zone="zs")
    call(c, cid, "POST", "/apply", acknowledge_live=True)
    call(c, cid, "DELETE", "/vnets/v1")
    r = call(c, cid, "POST", "/apply", acknowledge_live=True)
    assert r.status_code == 409 and "v1" in r.json()["detail"]
    call(c, cid, "POST", "/rollback")


def test_changed_host_zone_needs_phrase_but_unchanged_does_not(api):
    c, cid = api
    mkzone(c, cid, "zv", type="vlan", bridge="vmbr0", mtu=1500)
    call(c, cid, "POST", "/apply", acknowledge_cut_access=True, type_name=PHRASE)
    mkzone(c, cid, "zs"); call(c, cid, "PUT", "/zones/zs", mtu=1400)
    assert call(c, cid, "POST", "/apply", acknowledge_live=True).status_code == 200          # zv inchangée : pas de phrase
    call(c, cid, "PUT", "/zones/zv", mtu=1400)
    assert call(c, cid, "POST", "/apply", acknowledge_live=True).status_code == 409


def test_subnet_only_pending_counts(api):
    c, cid = api
    mkzone(c, cid); call(c, cid, "POST", "/vnets", vnet="v1", zone="z1")
    call(c, cid, "POST", "/apply", acknowledge_live=True)
    call(c, cid, "POST", "/vnets/v1/subnets", subnet="10.3.0.0/24")
    d = c.post(B.format(cid) + "/apply", json={"dry_run": True})
    assert d.status_code == 200 and d.json()["pending"]["subnets"] == ["z1-10.3.0.0-24"]


def test_rollback(api):
    c, cid = api
    assert call(c, cid, "POST", "/rollback").status_code == 409
    mkzone(c, cid)
    assert c.post(B.format(cid) + "/rollback", json={}).status_code == 400
    assert c.post(B.format(cid) + "/rollback", json={"dry_run": True}).json()["dry_run"] and "z1" in ST["pend"]["zones"]
    assert call(c, cid, "POST", "/rollback").json()["rolled_back"] and not ST["pend"]["zones"]
    mkzone(c, cid)
    ST["norollback"] = True
    assert call(c, cid, "POST", "/rollback").status_code == 502


def test_not_saved_502_audit_and_no_secret(api):
    c, cid = api
    ST["noapply"] = True
    assert mkzone(c, cid).status_code == 502 and ("sdn-zone-create", "error") in audit_pairs(c)
    ST.pop("noapply"); ST["fail"] = True
    r = mkzone(c, cid, "z2")
    assert r.status_code >= 400 and SECRET not in r.text and SECRET not in str(c.get("/api/audit").json())


def test_audit_success_and_login(api, client):
    c, cid = api
    mkzone(c, cid); call(c, cid, "POST", "/vnets", vnet="v1", zone="z1"); call(c, cid, "POST", "/apply", acknowledge_live=True)
    pairs = audit_pairs(c)
    assert {("sdn-zone-create", "started"), ("sdn-vnet-create", "started"), ("sdn-apply", "started")} <= set(pairs)
    c.post("/api/auth/logout")
    assert c.post(B.format(cid) + "/zones", json={"confirm": True, "zone": "z9", "type": "simple"}).status_code == 401


def test_deleted_zone_needs_phrase(api):
    c, cid = api
    mkzone(c, cid, "zs")
    call(c, cid, "POST", "/apply", acknowledge_live=True)
    assert call(c, cid, "DELETE", "/zones/zs").status_code == 200
    r = call(c, cid, "POST", "/apply", acknowledge_live=True)
    assert r.status_code == 409 and "zs" in r.json()["detail"]


def test_vnet_and_subnet_not_saved_502(api):
    c, cid = api
    mkzone(c, cid)
    ST["noapply"] = True
    assert call(c, cid, "POST", "/vnets", vnet="v1", zone="z1").status_code == 502
    ST.pop("noapply")
    call(c, cid, "POST", "/vnets", vnet="v1", zone="z1")
    ST["noapply"] = True
    assert call(c, cid, "POST", "/vnets/v1/subnets", subnet="10.2.0.0/24").status_code == 502
