import copy
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
TOKEN = "tok-AbC123-secret-token"
KEY = "powerdns-api-key-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
PHRASE = "COUPURE POSSIBLE"
B = "/api/connections/{}/sdn"
DIGEST = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
WRITES: list[tuple[str, str, dict]] = []
ST: dict = {}
OK = {
    "controllers": {"controller", "type", "asn", "peers", "ebgp", "ebgp-multihop", "bgp-multipath-as-path-relax", "node", "loopback", "isis-domain", "isis-ifaces", "isis-net", "fabric", "delete", "digest"},
    "ipams": {"ipam", "type", "url", "section", "fingerprint", "token", "delete", "digest"},
    "dns": {"dns", "type", "url", "key", "ttl", "reversemaskv6", "fingerprint", "delete", "digest"},
    "fabrics": {"id", "protocol", "ip_prefix", "ip6_prefix", "area", "hello_interval", "csnp_interval", "delete", "digest"},
}
IDKEY = {"controllers": "controller", "ipams": "ipam", "dns": "dns", "fabrics": "id"}
INTS = {"asn", "ebgp-multihop", "section", "ttl", "reversemaskv6", "hello_interval", "csnp_interval"}
BOOLS = {"ebgp", "bgp-multipath-as-path-relax"}
PENDING = ("controllers", "fabrics")


def fresh():
    ST.clear()
    ST["run"] = {k: {} for k in OK}
    ST["run"]["ipams"] = {"pve": {"type": "pve"}}
    ST["pend"] = copy.deepcopy(ST["run"])
    ST["fn_run"], ST["fn_pend"] = {}, {}
    ST["zones"] = []


def listing(kind):
    out = []
    idk = IDKEY[kind]
    for i, cfg in ST["pend"][kind].items():
        item = {idk: i, **cfg, "digest": DIGEST}
        if kind in PENDING:
            if i not in ST["run"][kind]:
                item["state"] = "new"
            elif ST["run"][kind][i] != cfg:
                item["state"] = "changed"
        out.append(item)
    if kind in PENDING:
        for i, cfg in ST["run"][kind].items():
            if i not in ST["pend"][kind]:
                out.append({idk: i, **cfg, "state": "deleted", "digest": DIGEST})
    return out


def fnodes(fab):
    out = []
    pend, run = ST["fn_pend"].get(fab, {}), ST["fn_run"].get(fab, {})
    for n, cfg in pend.items():
        it = {"node_id": n, **cfg, "digest": DIGEST}
        if n not in run:
            it["state"] = "new"
        elif run[n] != cfg:
            it["state"] = "changed"
        out.append(it)
    for n, cfg in run.items():
        if n not in pend:
            out.append({"node_id": n, **cfg, "state": "deleted", "digest": DIGEST})
    return out


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    raw = parse_qs(request.content.decode(), keep_blank_values=True)
    body = {k: (v if k in ("delete", "interfaces") else v[0]) for k, v in raw.items()}
    m = request.method
    parts = p.strip("/").split("/")
    if parts[:2] != ["cluster", "sdn"]:
        return httpx.Response(501, json={"data": None})
    if ST.get("fail") and m != "GET":
        return httpx.Response(403, json={"data": None, "message": SECRET})
    rest = parts[2:]
    if rest == ["zones"]:
        return httpx.Response(200, json={"data": ST["zones"]})
    if rest == ["vnets"]:
        return httpx.Response(200, json={"data": []})
    if rest == ["apply"] or (rest == [] and m == "PUT"):
        WRITES.append((m, p, body))
        ST["run"] = copy.deepcopy(ST["pend"]); ST["fn_run"] = copy.deepcopy(ST["fn_pend"])
        return httpx.Response(200, json={"data": "UPID:enzo:1:2:3:reload:root@pam:"})
    if rest[:2] == ["fabrics", "node"]:
        fab = rest[2]
        if fab not in ST["pend"]["fabrics"]:
            return httpx.Response(500, json={"data": None, "message": "no fabric"})
        node = rest[3] if len(rest) > 3 else None
        if m == "GET":
            return httpx.Response(200, json={"data": fnodes(fab)})
        bad = set(body) - {"protocol", "node_id", "ip", "ip6", "interfaces", "digest"}
        if bad or any(not x.startswith("name=") for x in body.get("interfaces", [])):
            return httpx.Response(400, json={"data": None, "message": f"refusé {sorted(bad)}"})
        WRITES.append((m, p, body))
        if ST.get("noapply"):
            return httpx.Response(200, json={"data": None})
        pend = ST["fn_pend"].setdefault(fab, {})
        cfg = {k: v for k, v in body.items() if k in ("ip", "ip6")}
        cfg["interfaces"] = [{"name": x.split("=", 1)[1]} for x in body.get("interfaces", [])]
        if m == "POST":
            pend[body["node_id"]] = cfg
        elif m == "PUT":
            pend[node] = cfg
        else:
            pend.pop(node, None)
        return httpx.Response(200, json={"data": None})
    if rest[0] == "fabrics" and rest[1:2] == ["fabric"]:
        kind, sid = "fabrics", (rest[2] if len(rest) > 2 else None)
    elif rest[0] in OK and rest[0] != "fabrics":
        kind, sid = rest[0], (rest[1] if len(rest) > 1 else None)
    else:
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if m == "GET":
        return httpx.Response(200, json={"data": listing(kind)})
    bad = set(body) - OK[kind]
    if bad or any(not body[k].isdigit() for k in set(body) & INTS) or any(body[k] not in ("0", "1") for k in set(body) & BOOLS):
        return httpx.Response(400, json={"data": None, "message": f"paramètres refusés {sorted(bad)}"})
    if m != "POST" and body.get("digest") not in (None, DIGEST):
        return httpx.Response(400, json={"data": None, "message": "digest"})
    WRITES.append((m, p, body))
    if ST.get("noapply"):
        return httpx.Response(200, json={"data": None})
    pend = ST["pend"][kind]
    idk = IDKEY[kind]
    cfg = {k.replace("-", "_") if kind == "fabrics" else k: (int(v) if k in INTS else v) for k, v in body.items() if k not in (idk, "delete", "digest")}
    if kind == "controllers":
        cfg = {k: (int(v) if k in BOOLS else v) for k, v in cfg.items()}
        if "peers" in cfg:
            cfg["peers"] = cfg["peers"]
    if m == "POST":
        if body[idk] in pend:
            return httpx.Response(400, json={"data": None, "message": "exists"})
        pend[body[idk]] = cfg
    elif m == "PUT":
        c = pend[sid]
        for k in (body.get("delete") if isinstance(body.get("delete"), list) else [x for x in body.get("delete", "").split(",") if x]):
            c.pop(k, None)
        c.update(cfg)
    else:
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


def audit_text(c):
    return str(c.get("/api/audit").json())


EVPN = dict(controller="ctl1", type="evpn", asn=65000, peers=["10.0.0.1", "10.0.0.2"])


def test_controller_create_staged_and_lists(api):
    c, cid = api
    r = call(c, cid, "POST", "/controllers", **EVPN)
    assert r.status_code == 200 and r.json()["staged"] and r.json()["applied"] is False
    assert WRITES[-1][2]["peers"] == "10.0.0.1,10.0.0.2" and WRITES[-1][2]["asn"] == "65000"
    row = c.get(B.format(cid) + "/controllers").json()[0]
    assert row["controller"] == "ctl1" and row["state"] == "new" and row["peers"] == ["10.0.0.1", "10.0.0.2"]
    assert not any(w[0] == "PUT" and w[1] == "/cluster/sdn" for w in WRITES)


ISIS = dict(controller="is1", type="isis", node="enzo", isis_domain="d", isis_ifaces=["nic0"], isis_net="49.0001.0000.0000.0001.00")


@pytest.mark.parametrize("base,bad", [
    (EVPN, {"controller": "Ctl"}), (EVPN, {"controller": "toolongctl"}), (EVPN, {"type": "faucet"}), (EVPN, {"asn": -1}), (EVPN, {"asn": 4294967296}), (EVPN, {"asn": "65000"}),
    (EVPN, {"peers": ["x"]}), (EVPN, {"peers": ["10.0.0.1", "10.0.0.1"]}), (dict(controller="b1", type="bgp"), {}), (dict(controller="b1", type="bgp", asn=1), {"node": "a b"}),
    (EVPN, {"node": "enzo"}), (EVPN, {"ebgp": True}), (EVPN, {"isis_net": "49.0001.0000.0000.0001.00"}), (ISIS, {"isis_net": "bad"}), (ISIS, {"isis_ifaces": ["a b"]}),
    (ISIS, {"isis_ifaces": ["nic0", "nic0"]}), (ISIS, {"isis_domain": "bad domain"}), (ISIS, {"asn": 1}), (dict(controller="b1", type="bgp", asn=1, node="enzo"), {"ebgp_multihop": 0}),
    (dict(controller="b1", type="bgp", asn=1, node="enzo"), {"ebgp": "true"}), (dict(controller="b1", type="bgp", asn=1, node="enzo"), {"loopback": "lo lo"}),
])
def test_controller_invalid(api, base, bad):
    c, cid = api
    r = call(c, cid, "POST", "/controllers", **{**base, **bad})
    assert r.status_code == 422 and not WRITES, (base, bad, r.status_code, r.text)


def test_controller_variants_update_delete_guard(api):
    c, cid = api
    assert call(c, cid, "POST", "/controllers", controller="bg1", type="bgp", asn=65001, node="enzo", ebgp=True, ebgp_multihop=2, loopback="lo").status_code == 200
    assert call(c, cid, "POST", "/controllers", controller="is1", type="isis", node="enzo", isis_domain="dom", isis_ifaces=["nic0", "nic1"], isis_net="49.0001.0000.0000.0001.00").status_code == 200
    assert call(c, cid, "POST", "/controllers", **EVPN).status_code == 200
    assert call(c, cid, "POST", "/controllers", **EVPN).status_code == 409
    ST["run"] = copy.deepcopy(ST["pend"])
    assert call(c, cid, "PUT", "/controllers/ctl1", asn=65002).status_code == 200 and WRITES[-1][2]["digest"] == DIGEST
    assert call(c, cid, "PUT", "/controllers/ctl1", clear=["asn"]).status_code == 422                # exigé
    assert call(c, cid, "PUT", "/controllers/ctl1", asn=1, clear=["asn"]).status_code == 422
    assert call(c, cid, "PUT", "/controllers/bg1", ebgp_multihop=3, clear=["ebgp_multihop"]).status_code == 422
    assert call(c, cid, "PUT", "/controllers/bg1").status_code == 422
    assert call(c, cid, "PUT", "/controllers/bg1", clear=["type"]).status_code == 422
    assert call(c, cid, "PUT", "/controllers/bg1", clear=["ebgp_multihop"]).status_code == 200 and ",".join(WRITES[-1][2]["delete"]) == "ebgp-multihop"
    assert call(c, cid, "PUT", "/controllers/nope", asn=1).status_code == 404
    ST["zones"] = [{"zone": "ze", "type": "evpn", "controller": "ctl1"}]
    r = call(c, cid, "DELETE", "/controllers/ctl1")
    assert r.status_code == 409 and "ze" in r.json()["detail"]
    ST["zones"] = []
    assert call(c, cid, "DELETE", "/controllers/ctl1", dry_run=True).json()["dry_run"] and "ctl1" in ST["pend"]["controllers"]
    assert call(c, cid, "DELETE", "/controllers/ctl1").status_code == 200 and "ctl1" not in ST["pend"]["controllers"]


def test_apply_with_routing_needs_phrase(api):
    c, cid = api
    call(c, cid, "POST", "/controllers", **EVPN)
    r = call(c, cid, "POST", "/apply", acknowledge_live=True)
    assert r.status_code == 409 and "ctl1" in r.json()["detail"] and "routage" in r.json()["detail"]
    assert call(c, cid, "POST", "/apply", acknowledge_cut_access=True, type_name=PHRASE).status_code == 200


def test_ipam_secret_never_leaks(api):
    c, cid = api
    r = call(c, cid, "POST", "/ipams", ipam="nb1", type="netbox", url="https://netbox.lan/api", token=TOKEN)
    assert r.status_code == 200 and r.json()["saved"] is True and TOKEN not in r.text
    assert WRITES[-1][2]["token"] == TOKEN                                      # transmis à Proxmox, nulle part ailleurs
    d = c.post(B.format(cid) + "/ipams", json={"dry_run": True, "ipam": "nb2", "type": "netbox", "url": "https://n.lan", "token": TOKEN})
    assert d.status_code == 200 and TOKEN not in d.text and d.json()["params"]["token"] == "***" and d.json()["secrets_set"] == ["token"]
    assert TOKEN not in c.get(B.format(cid) + "/ipams").text and TOKEN not in audit_text(c)
    assert "secret défini : token" in audit_text(c)
    ST["pend"]["ipams"]["nb1"]["token"] = TOKEN
    row = [i for i in c.get(B.format(cid) + "/ipams").json() if i["ipam"] == "nb1"][0]
    assert row["token_set"] is True and "token" not in row
    r = call(c, cid, "POST", "/ipams", ipam="nb3", type="netbox", url="bad", token=TOKEN)
    assert r.status_code == 422 and TOKEN not in r.text
    r = call(c, cid, "POST", "/ipams", ipam="nb4", type="netbox", url="https://n.lan", token="a b")
    assert r.status_code == 422 and "a b" not in r.text


@pytest.mark.parametrize("bad", [
    {"ipam": "Bad"}, {"type": "infoblox"}, {"type": "netbox"}, {"type": "phpipam", "url": "https://p.lan"}, {"type": "pve", "url": "https://x.lan"}, {"type": "pve", "token": "abc"},
    {"type": "netbox", "url": "ftp://x.lan"}, {"type": "netbox", "url": "https://user:pw@x.lan"}, {"type": "netbox", "url": "https://x.lan/a b"},
    {"type": "netbox", "url": "https://x.lan", "fingerprint": "zz"}, {"type": "netbox", "url": "https://x.lan", "section": 1}, {"type": "phpipam", "url": "https://p.lan", "section": -1},
])
def test_ipam_invalid(api, bad):
    c, cid = api
    r = call(c, cid, "POST", "/ipams", **{"ipam": "nb1", "type": "pve", **bad})
    assert r.status_code == 422 and not WRITES, (bad, r.status_code, r.text)


def test_ipam_update_live_lock_and_delete_guards(api):
    c, cid = api
    call(c, cid, "POST", "/ipams", ipam="nb1", type="netbox", url="https://n.lan", token=TOKEN)
    assert call(c, cid, "PUT", "/ipams/nb1", url="https://n2.lan").status_code == 200
    ST["zones"] = [{"zone": "z1", "type": "simple", "ipam": "nb1"}]
    r = call(c, cid, "PUT", "/ipams/nb1", url="https://n3.lan")
    assert r.status_code == 409 and "zone SDN" in r.json()["detail"]
    assert call(c, cid, "PUT", "/ipams/nb1", url="https://n3.lan", acknowledge_live=True).status_code == 200
    assert call(c, cid, "PUT", "/ipams/nb1", url="https://n3.lan", acknowledge_live="true").status_code == 422
    r = call(c, cid, "DELETE", "/ipams/nb1")
    assert r.status_code == 409 and "z1" in r.json()["detail"]
    r = call(c, cid, "DELETE", "/ipams/pve")
    assert r.status_code == 409
    ST["zones"] = [{"zone": "z1", "type": "simple", "ipam": "nb1", "state": "deleted"}]
    assert call(c, cid, "DELETE", "/ipams/nb1").status_code == 200


def test_dns_create_update_delete(api):
    c, cid = api
    assert call(c, cid, "POST", "/dns", dns="pdns", type="powerdns", url="https://pdns.lan:8081/api", key=KEY, ttl=3600, reversemaskv6=64).status_code == 200
    assert KEY not in c.get(B.format(cid) + "/dns").text and KEY not in audit_text(c)
    assert call(c, cid, "POST", "/dns", dns="pdns2", type="powerdns", url="https://pdns.lan").status_code == 422        # clé exigée
    assert call(c, cid, "POST", "/dns", dns="pdns3", type="powerdns", url="https://x.lan", key=KEY, ttl=0).status_code == 422
    assert call(c, cid, "POST", "/dns", dns="pdns3", type="powerdns", url="https://x.lan", key=KEY, reversemaskv6=129).status_code == 422
    assert call(c, cid, "POST", "/dns", dns="pdns", type="powerdns", url="https://x.lan", key=KEY).status_code == 409
    assert call(c, cid, "PUT", "/dns/pdns", ttl=60, key="new-key-value").status_code == 200
    assert call(c, cid, "PUT", "/dns/pdns", clear=["ttl"]).status_code == 200
    assert call(c, cid, "PUT", "/dns/pdns", clear=["key"]).status_code == 422
    ST["zones"] = [{"zone": "z1", "type": "simple", "dns": "pdns"}]
    assert call(c, cid, "PUT", "/dns/pdns", ttl=5).status_code == 409
    assert "z1" in call(c, cid, "DELETE", "/dns/pdns").json()["detail"]
    ST["zones"] = [{"zone": "z2", "type": "simple", "reversedns": "pdns"}]
    assert call(c, cid, "DELETE", "/dns/pdns").status_code == 409
    ST["zones"] = []
    assert call(c, cid, "DELETE", "/dns/pdns").status_code == 200


FAB = dict(id="fab1", protocol="ospf", ip_prefix="10.10.0.0/24", area="0")


def test_fabric_and_nodes(api):
    c, cid = api
    assert call(c, cid, "POST", "/fabrics", **FAB).status_code == 200
    assert WRITES[-1][2]["ip_prefix"] == "10.10.0.0/24" and WRITES[-1][2]["protocol"] == "ospf"
    assert call(c, cid, "POST", "/fabrics", **FAB).status_code == 409
    assert call(c, cid, "POST", "/fabrics", id="of1", protocol="openfabric", ip_prefix="10.20.0.0/24", hello_interval=5, csnp_interval=10).status_code == 200
    for bad in ({"area": "0"}, {"hello_interval": 5}):
        base = {"id": "fx", "protocol": "openfabric" if "area" in bad else "ospf", "ip_prefix": "10.1.0.0/24"}
        assert call(c, cid, "POST", "/fabrics", **{**base, **bad}).status_code == 422
    for bad in ({"ip6_prefix": "10.1.0.0/24"}, {"ip_prefix": "10.1.0.5/24"}, {"ip_prefix": "fe80::/64"}, {"ip_prefix": None}, {"area": "x"}, {"id": "bad id"}, {"protocol": "isis"}, {"hello_interval": 0}, {"csnp_interval": 601}):
        assert call(c, cid, "POST", "/fabrics", **{"id": "fy", "protocol": "ospf", "ip_prefix": "10.1.0.0/24", **bad}).status_code == 422, bad
    ST["run"] = copy.deepcopy(ST["pend"])
    assert call(c, cid, "PUT", "/fabrics/fab1", area="1").status_code == 200
    assert call(c, cid, "PUT", "/fabrics/fab1", clear=["area"]).status_code == 200 and WRITES[-1][2]["delete"] == ["area"]
    assert call(c, cid, "PUT", "/fabrics/fab1", ip6_prefix="fd00::/64", area="2").status_code == 200
    assert call(c, cid, "PUT", "/fabrics/fab1", clear=["area", "ip6_prefix"]).status_code == 200 and WRITES[-1][2]["delete"] == ["area", "ip6_prefix"]
    assert "area" not in ST["pend"]["fabrics"]["fab1"] and "ip6_prefix" not in ST["pend"]["fabrics"]["fab1"]
    assert call(c, cid, "PUT", "/fabrics/fab1", clear=["ip_prefix"]).status_code == 422                # exige un préfixe
    assert call(c, cid, "PUT", "/fabrics/fab1", hello_interval=3).status_code == 422                   # champ d'openfabric
    # nœuds
    assert call(c, cid, "POST", "/fabrics/nope/nodes/enzo", ip="10.10.0.1").status_code == 404
    assert call(c, cid, "POST", "/fabrics/fab1/nodes/enzo", interfaces=[{"name": "nic1"}]).status_code == 422          # ip exigée
    assert call(c, cid, "POST", "/fabrics/fab1/nodes/enzo", ip="10.10.0.1", interfaces=[{"name": "nic1"}, {"name": "nic2"}]).status_code == 200
    assert WRITES[-1][2]["interfaces"] == ["name=nic1", "name=nic2"] and WRITES[-1][2]["protocol"] == "ospf" and WRITES[-1][2]["node_id"] == "enzo"
    assert call(c, cid, "POST", "/fabrics/fab1/nodes/enzo", ip="10.10.0.1").status_code == 409
    assert call(c, cid, "POST", "/fabrics/fab1/nodes/e2", ip="999.1.1.1").status_code == 422
    assert call(c, cid, "POST", "/fabrics/fab1/nodes/e2", ip="10.10.0.2", interfaces=[{"name": "a b"}]).status_code == 422
    assert call(c, cid, "POST", "/fabrics/fab1/nodes/e2", ip="10.10.0.2", interfaces=[{"name": "n"}, {"name": "n"}]).status_code == 422
    assert c.get(B.format(cid) + "/fabrics/fab1/nodes").json()[0]["interfaces"] == ["nic1", "nic2"]
    assert call(c, cid, "PUT", "/fabrics/fab1/nodes/enzo", ip6="fd00::1").status_code == 200
    assert call(c, cid, "PUT", "/fabrics/fab1/nodes/zz", ip="10.10.0.9").status_code == 404
    r = call(c, cid, "DELETE", "/fabrics/fab1")
    assert r.status_code == 409 and "enzo" in r.json()["detail"]
    assert call(c, cid, "DELETE", "/fabrics/fab1/nodes/enzo").status_code == 200
    call(c, cid, "POST", "/controllers", controller="is1", type="isis", node="enzo", isis_domain="d", isis_ifaces=["nic0"], isis_net="49.0001.0000.0000.0001.00", fabric="fab1")
    assert call(c, cid, "DELETE", "/fabrics/fab1").status_code == 409
    call(c, cid, "DELETE", "/controllers/is1")
    assert call(c, cid, "DELETE", "/fabrics/fab1").status_code == 200


def test_apply_lists_fabric_nodes_and_routing_lock(api):
    c, cid = api
    call(c, cid, "POST", "/fabrics", **FAB)
    call(c, cid, "POST", "/apply", acknowledge_cut_access=True, type_name=PHRASE)
    call(c, cid, "POST", "/fabrics/fab1/nodes/enzo", ip="10.10.0.1")
    d = c.post(B.format(cid) + "/apply", json={"dry_run": True}).json()
    assert d["pending"]["fabrics"] == ["fab1/enzo"] and d["locks"]["cut"]


def test_not_saved_502_audit_and_no_secret_in_errors(api):
    c, cid = api
    ST["noapply"] = True
    assert call(c, cid, "POST", "/controllers", **EVPN).status_code == 502
    ST.pop("noapply"); ST["fail"] = True
    r = call(c, cid, "POST", "/ipams", ipam="nb1", type="netbox", url="https://n.lan", token=TOKEN)
    assert r.status_code >= 400 and SECRET not in r.text and TOKEN not in r.text and TOKEN not in audit_text(c) and SECRET not in audit_text(c)


def test_confirm_required_and_login(api, client):
    c, cid = api
    assert c.post(B.format(cid) + "/controllers", json=EVPN).status_code == 400 and not WRITES
    assert c.delete(B.format(cid) + "/ipams/nb1").status_code in (400, 404)
    c.post("/api/auth/logout")
    assert c.post(B.format(cid) + "/controllers", json={"confirm": True, **EVPN}).status_code == 401

