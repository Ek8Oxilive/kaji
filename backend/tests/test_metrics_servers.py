"""Serveurs de métriques (lot #149) : faux Proxmox STRICT (chemin, paramètres par type, valeurs, digest ; 400 sinon). Il renvoie le jeton EN CLAIR : Kaji ne doit jamais le relayer."""
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
TOKEN = "tok-AbC123_secret=="
HDR = "eyJBdXRob3JpemF0aW9uIjoiQmVhcmVyIFNFQ1JFVCJ9"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
DIGEST = "d" * 40
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}
COMMON = {"server", "port", "disable"}
KEYS = {"influxdb": COMMON | {"influxdbproto", "organization", "bucket", "token", "max-body-size", "mtu", "verify-certificate", "api-path-prefix"},
        "graphite": COMMON | {"proto", "path", "mtu", "timeout"},
        "opentelemetry": COMMON | {"otel-protocol", "otel-path", "otel-timeout", "otel-compression", "otel-verify-ssl", "otel-max-body-size", "otel-headers", "otel-resource-attributes"}}
BOOLS = {"disable", "verify-certificate", "otel-verify-ssl"}
INTS = {"port", "max-body-size", "mtu", "timeout", "otel-timeout", "otel-max-body-size"}
ENUMS = {"influxdbproto": {"udp", "http", "https"}, "proto": {"udp", "tcp"}, "otel-protocol": {"http", "https"}, "otel-compression": {"none", "gzip"}}


def fresh():
    ST.clear()
    ST.update(noapply=False, fail=False, servers={
        "influx1": {"type": "influxdb", "server": "192.168.1.50", "port": 8086, "influxdbproto": "https", "organization": "lab", "bucket": "pve", "token": TOKEN, "disable": 0},
        "graph1": {"type": "graphite", "server": "graphite.lan", "port": 2003, "proto": "udp", "path": "proxmox.lab", "disable": 1},
        "otel1": {"type": "opentelemetry", "server": "otel.lan", "port": 4318, "otel-protocol": "http", "otel-path": "/v1/metrics", "otel-headers": HDR, "disable": 0}})


def bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def check(body, typ):
    if set(body) - KEYS[typ] - {"type", "delete", "digest"}:
        return f"paramètres refusés {sorted(set(body) - KEYS[typ] - {'type', 'delete', 'digest'})}"
    for k, v in body.items():
        if k in BOOLS and v not in ("0", "1"):
            return f"{k} doit être 0/1"
        if k in INTS and not v.isdigit():
            return f"{k} doit être un entier"
        if k in ENUMS and v not in ENUMS[k]:
            return f"{k} invalide"
    return None


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    m = request.method
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if m == "GET":
        if p == "/cluster/metrics/server":
            return httpx.Response(200, json={"data": [{"id": k, "type": v["type"], "server": v["server"], "port": v["port"], "disable": v.get("disable", 0)} for k, v in ST["servers"].items()]})
        sid = p.removeprefix("/cluster/metrics/server/")
        if p.startswith("/cluster/metrics/server/") and sid in ST["servers"]:
            return httpx.Response(200, json={"data": {**ST["servers"][sid], "digest": DIGEST}})
        return httpx.Response(500, json={"data": None, "message": "no such server"})
    if ST["fail"]:
        return httpx.Response(403, json={"data": None, "message": SECRET})
    if not p.startswith("/cluster/metrics/server/"):
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    sid = p.removeprefix("/cluster/metrics/server/")
    query = dict(request.url.params)
    CALLS.append((m, p, {**body, **({"__query": query} if query else {})}))
    if m == "POST":
        if body.get("type") not in KEYS or not {"server", "port"} <= set(body) or (err := check(body, body["type"])):
            return bad(err if "err" in dir() and body.get("type") in KEYS else "type ou paramètres obligatoires manquants")
        if sid in ST["servers"]:
            return bad("existe déjà")
        if not ST["noapply"]:
            ST["servers"][sid] = {"type": body["type"], **{k: (int(v) if k in INTS | BOOLS else v) for k, v in body.items() if k != "type"}}
        return httpx.Response(200, json={"data": None})
    cur = ST["servers"].get(sid)
    if cur is None:
        return httpx.Response(500, json={"data": None, "message": "no such server"})
    if m == "PUT":
        if (err := check(body, cur["type"])):
            return bad(err)
        if body.get("digest") != DIGEST:
            return bad("digest différent")
        dl = [x for x in body.get("delete", "").split(",") if x]
        if set(dl) - (KEYS[cur["type"]] - {"server", "port"}):
            return bad("delete invalide")
        if not ST["noapply"]:
            for k, v in body.items():
                if k not in ("delete", "digest"):
                    cur[k] = int(v) if k in INTS | BOOLS else v
            for k in dl:
                cur.pop(k, None)
        return httpx.Response(200, json={"data": None})
    if m == "DELETE":
        if body or query:
            return bad("aucun paramètre attendu")
        if not ST["noapply"]:
            del ST["servers"][sid]
        return httpx.Response(200, json={"data": None})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client):
    CALLS.clear(); fresh()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, sid=""):
    return f"/api/connections/{cid}/metrics/servers" + (f"/{sid}" if sid else "")


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# ---------------------------------------------------------------- lecture : jamais de secret
def test_list_and_detail_never_return_secrets(api):
    c, cid = api
    r = c.get(url(cid))
    assert r.status_code == 200 and [x["id"] for x in r.json()] == ["graph1", "influx1", "otel1"] and TOKEN not in r.text
    i = c.get(url(cid, "influx1"))
    assert i.status_code == 200 and TOKEN not in i.text and i.json()["token_set"] is True and "token" not in i.json()
    assert i.json()["organization"] == "lab" and i.json()["influxdbproto"] == "https" and i.json()["digest"] == DIGEST and i.json()["disable"] is False
    o = c.get(url(cid, "otel1"))
    assert HDR not in o.text and o.json()["otel_headers_set"] is True and o.json()["otel_protocol"] == "http"
    g = c.get(url(cid, "graph1")).json()
    assert g["proto"] == "udp" and g["path"] == "proxmox.lab" and g["disable"] is True
    assert c.get(url(cid, "nope")).status_code == 404


# ---------------------------------------------------------------- création
def test_create_influxdb_exact_params_and_no_secret_back(api):
    c, cid = api
    r = c.post(url(cid), json={"id": "idb2", "type": "influxdb", "server": "influx.example.org", "port": 8086, "influxdbproto": "https", "organization": "mon org", "bucket": "pve",
                              "token": TOKEN, "max_body_size": 25000000, "verify_certificate": True, "api_path_prefix": "/influx", "confirm": True})
    assert r.status_code == 201 and TOKEN not in r.text and r.json()["token_set"] is True and r.json()["type"] == "influxdb"
    assert CALLS == [("POST", "/cluster/metrics/server/idb2", {"type": "influxdb", "server": "influx.example.org", "port": "8086", "influxdbproto": "https", "organization": "mon org",
                                                                 "bucket": "pve", "token": TOKEN, "max-body-size": "25000000", "verify-certificate": "1", "api-path-prefix": "/influx"})]
    assert TOKEN not in c.get("/api/audit").text and "token=défini" in c.get("/api/audit").text


def test_create_graphite_and_opentelemetry(api):
    c, cid = api
    assert c.post(url(cid), json={"id": "g2", "type": "graphite", "server": "10.1.2.3", "port": 2003, "proto": "tcp", "path": "proxmox.lab.cluster", "mtu": 1400, "timeout": 5, "confirm": True}).status_code == 201
    assert CALLS[-1][2] == {"type": "graphite", "server": "10.1.2.3", "port": "2003", "proto": "tcp", "path": "proxmox.lab.cluster", "mtu": "1400", "timeout": "5"}
    r = c.post(url(cid), json={"id": "o2", "type": "opentelemetry", "server": "otel.example.org", "port": 4318, "otel_protocol": "https", "otel_path": "/v1/metrics", "otel_timeout": 10,
                              "otel_compression": "gzip", "otel_verify_ssl": False, "otel_max_body_size": 2048, "otel_headers": HDR, "otel_resource_attributes": HDR, "confirm": True})
    assert r.status_code == 201, r.text
    assert HDR not in r.text and r.json()["otel_headers_set"] is True
    assert CALLS[-1][2] == {"type": "opentelemetry", "server": "otel.example.org", "port": "4318", "otel-protocol": "https", "otel-path": "/v1/metrics", "otel-timeout": "10",
                             "otel-compression": "gzip", "otel-verify-ssl": "0", "otel-max-body-size": "2048", "otel-headers": HDR, "otel-resource-attributes": HDR}


def test_enabled_server_needs_confirm_disabled_one_does_not(api):
    c, cid = api
    r = c.post(url(cid), json={"id": "g3", "type": "graphite", "server": "10.1.2.3", "port": 2003})
    assert r.status_code == 400 and "confirm=true" in r.json()["detail"] and not CALLS
    assert c.post(url(cid), json={"id": "g3", "type": "graphite", "server": "10.1.2.3", "port": 2003, "confirm": "true"}).status_code == 422
    assert c.post(url(cid), json={"id": "g3", "type": "graphite", "server": "10.1.2.3", "port": 2003, "disable": True}).status_code == 201
    assert CALLS[-1][2]["disable"] == "1"


def test_create_dry_run_masks_secrets_and_writes_nothing(api):
    c, cid = api
    r = c.post(url(cid), json={"id": "idb2", "type": "influxdb", "server": "10.0.0.9", "port": 8086, "token": TOKEN, "dry_run": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True and r.json()["params"]["token"] == "défini" and TOKEN not in r.text and r.json()["needs_confirm"] is True
    assert not CALLS and "idb2" not in ST["servers"]


def test_duplicate_id_is_409(api):
    c, cid = api
    assert c.post(url(cid), json={"id": "influx1", "type": "influxdb", "server": "10.0.0.9", "port": 8086, "confirm": True}).status_code == 409 and not CALLS


def test_fields_of_another_type_are_refused_and_unknown_ones_never_forwarded(api):
    c, cid = api
    base = {"server": "10.1.2.3", "port": 2003, "confirm": True}
    for typ, extra in (("graphite", {"token": TOKEN}), ("graphite", {"organization": "x"}), ("influxdb", {"path": "a.b"}), ("influxdb", {"proto": "udp"}), ("opentelemetry", {"influxdbproto": "udp"}),
                       ("graphite", {"otel_headers": HDR})):
        assert c.post(url(cid), json={"id": "x1", "type": typ, **base, **extra}).status_code == 422
    assert not CALLS
    assert c.post(url(cid), json={"id": "x1", "type": "graphite", **base, "hookscript": "x", "evil": SECRET, "id2": "y"}).status_code == 201
    assert set(CALLS[-1][2]) == {"type", "server", "port"}


@pytest.mark.parametrize("b", [
    {"server": "127.0.0.1"}, {"server": "127.5.5.5"}, {"server": "localhost"}, {"server": "sub.localhost"}, {"server": "::1"}, {"server": "0.0.0.0"}, {"server": "169.254.1.1"}, {"server": "224.0.0.1"},
    {"server": "240.0.0.1"}, {"server": "fe80::1"}, {"server": "a b"}, {"server": "host;ls"}, {"server": "http://h"}, {"server": "h:80"}, {"server": "-bad.example"}, {"server": ""}, {"server": "x" * 254},
    {"server": "[::1]"}, {"server": "1:2:3:4:5:6:7:8:9"}, {"server": "gg::1"},
    {"port": 0}, {"port": 65536}, {"port": "8086"}, {"port": True}, {"port": 80.5}, {"port": -1},
    {"influxdbproto": "ftp"}, {"mtu": 511}, {"mtu": 65537}, {"max_body_size": 0}, {"disable": "1"}, {"disable": 1}, {"verify_certificate": "yes"},
    {"organization": "a;b"}, {"organization": "a\nb"}, {"bucket": "x" * 129}, {"bucket": ""},
    {"api_path_prefix": "/a/../b"}, {"api_path_prefix": "..//x"}, {"api_path_prefix": "/a b"}, {"api_path_prefix": "http://x"},
    {"token": "a b"}, {"token": "a\nb"}, {"token": ""}, {"token": "x" * 513}, {"token": 5},
    {"confirm": "true"}, {"dry_run": "no"},
])
def test_invalid_values_are_refused_without_any_call(api, b):
    c, cid = api
    assert c.post(url(cid), json={"id": "x1", "type": "influxdb", "server": "10.1.2.3", "port": 8086, "confirm": True, **b}).status_code == 422 and not CALLS


@pytest.mark.parametrize("b", [
    {"proto": "icmp"}, {"path": "a..b"}, {"path": ".a"}, {"path": "a b"}, {"path": "a/b"}, {"path": "a;b"}, {"timeout": -1}, {"timeout": 301}, {"mtu": 100},
])
def test_invalid_graphite_values_are_refused(api, b):
    c, cid = api
    assert c.post(url(cid), json={"id": "x1", "type": "graphite", "server": "10.1.2.3", "port": 2003, "confirm": True, **b}).status_code == 422 and not CALLS


@pytest.mark.parametrize("b", [
    {"otel_protocol": "ftp"}, {"otel_path": "v1/../x"}, {"otel_timeout": 0}, {"otel_timeout": 11}, {"otel_compression": "zip"}, {"otel_max_body_size": 1023}, {"otel_headers": "pas du base64!"},
    {"otel_headers": "x" * 1025}, {"otel_resource_attributes": "{\"a\":1}"},
])
def test_invalid_opentelemetry_values_are_refused(api, b):
    c, cid = api
    assert c.post(url(cid), json={"id": "x1", "type": "opentelemetry", "server": "10.1.2.3", "port": 4318, "confirm": True, **b}).status_code == 422 and not CALLS


@pytest.mark.parametrize("sid", ["1abc", "a", "a b", "a/b", "../x", "a;b", "x" * 65, ""])
def test_invalid_ids_are_refused(api, sid):
    c, cid = api
    assert c.post(url(cid), json={"id": sid, "type": "graphite", "server": "10.1.2.3", "port": 2003, "confirm": True}).status_code == 422 and not CALLS


def test_server_and_port_are_required_to_create(api):
    c, cid = api
    for extra in ({}, {"server": "10.1.2.3"}, {"port": 2003}):
        assert c.post(url(cid), json={"id": "x1", "type": "graphite", "confirm": True, **extra}).status_code == 422
    assert not CALLS


def test_private_lan_addresses_are_allowed(api):
    c, cid = api
    for i, host in enumerate(("192.168.1.50", "10.0.0.7", "172.16.0.2", "influx.lan", "[2001:db8::5]".strip("[]"))):
        assert c.post(url(cid), json={"id": f"ok{i}", "type": "graphite", "server": host, "port": 2003, "confirm": True}).status_code == 201


# ---------------------------------------------------------------- modification
def test_update_exact_params_digest_and_clear(api):
    c, cid = api
    r = c.put(url(cid, "influx1"), json={"organization": "autre", "token": TOKEN + "2", "clear": ["bucket"]})
    assert r.status_code == 200 and TOKEN not in r.text and r.json()["organization"] == "autre"
    assert CALLS == [("PUT", "/cluster/metrics/server/influx1", {"organization": "autre", "token": TOKEN + "2", "delete": "bucket", "digest": DIGEST})]
    assert "bucket" not in ST["servers"]["influx1"]
    assert c.put(url(cid, "influx1"), json={"max_body_size": 5000, "verify_certificate": False}).status_code == 200
    assert c.put(url(cid, "influx1"), json={"clear": ["max_body_size", "verify_certificate", "api_path_prefix"], "confirm": True}).status_code == 200
    assert CALLS[-1][2]["delete"] == "max-body-size,verify-certificate,api-path-prefix"                                   # noms Proxmox, avec tirets
    assert c.put(url(cid, "influx1"), json={"clear": ["token"]}).status_code == 200 and "token" not in ST["servers"]["influx1"]
    assert c.get(url(cid, "influx1")).json()["token_set"] is False


def test_update_type_is_immutable_and_foreign_fields_refused(api):
    c, cid = api
    assert c.put(url(cid, "graph1"), json={"token": TOKEN, "comment": "x"}).status_code == 422
    assert c.put(url(cid, "influx1"), json={"path": "a.b"}).status_code == 422
    assert not CALLS
    assert c.put(url(cid, "graph1"), json={"type": "influxdb", "id": "autre", "mtu": 1400}).status_code == 200
    assert set(CALLS[-1][2]) == {"mtu", "digest"} and ST["servers"]["graph1"]["type"] == "graphite"


@pytest.mark.parametrize("b", [{}, {"clear": []}, {"clear": ["server"]}, {"clear": ["port"]}, {"clear": ["type"]}, {"clear": ["id"]}, {"clear": ["../x"]}, {"clear": ["otel_headers"]},
                               {"organization": "x", "clear": ["organization"]}, {"token": TOKEN, "clear": ["token"]}])
def test_update_empty_or_forbidden_changes(api, b):
    c, cid = api
    assert c.put(url(cid, "influx1"), json=b).status_code == 422 and not CALLS


def test_update_unknown_server_and_stale_digest(api):
    c, cid = api
    assert c.put(url(cid, "nope"), json={"mtu": 1400}).status_code == 404 and not CALLS
    r = c.put(url(cid, "influx1"), json={"organization": "x", "digest": "0" * 40})
    assert r.status_code == 409 and "digest périmé" in r.json()["detail"] and not CALLS
    assert c.put(url(cid, "influx1"), json={"organization": "x", "digest": DIGEST}).status_code == 200


def test_update_confirm_rules(api):
    c, cid = api
    # serveur activé : changer où partent les métriques exige confirm ; un réglage sans effet sur la destination, non
    assert c.put(url(cid, "influx1"), json={"server": "10.9.9.9"}).status_code == 400
    assert c.put(url(cid, "influx1"), json={"port": 9999}).status_code == 400
    assert c.put(url(cid, "influx1"), json={"influxdbproto": "http"}).status_code == 400
    assert c.put(url(cid, "influx1"), json={"api_path_prefix": "/x"}).status_code == 400
    assert c.put(url(cid, "influx1"), json={"clear": ["api_path_prefix"]}).status_code == 400
    assert not CALLS
    assert c.put(url(cid, "influx1"), json={"organization": "autre", "bucket": "b2", "max_body_size": 1000}).status_code == 200
    assert c.put(url(cid, "influx1"), json={"server": "10.9.9.9", "confirm": True}).status_code == 200
    # serveur désactivé : modifier la destination est sans effet tant qu'il reste désactivé, mais l'activer exige confirm
    assert c.put(url(cid, "graph1"), json={"server": "10.9.9.8", "port": 2004}).status_code == 200
    assert c.put(url(cid, "graph1"), json={"disable": False}).status_code == 400
    assert c.put(url(cid, "graph1"), json={"disable": False, "confirm": True}).status_code == 200 and ST["servers"]["graph1"]["disable"] == 0
    assert c.put(url(cid, "graph1"), json={"disable": True}).status_code == 200                                   # désactiver : jamais de confirmation


def test_update_dry_run(api):
    c, cid = api
    d = c.put(url(cid, "influx1"), json={"server": "10.9.9.9", "token": TOKEN, "dry_run": True})
    assert d.status_code == 200 and d.json()["needs_confirm"] is True and d.json()["params"]["token"] == "défini" and TOKEN not in d.text and not CALLS


# ---------------------------------------------------------------- suppression
def test_delete_needs_confirm_and_retyped_id(api):
    c, cid = api
    assert c.delete(url(cid, "graph1")).status_code == 400
    assert c.delete(url(cid, "graph1"), params={"confirm": True}).status_code == 400
    assert c.delete(url(cid, "graph1"), params={"confirm": True, "type_name": "graph2"}).status_code == 400
    assert c.delete(url(cid, "graph1"), params={"type_name": "graph1"}).status_code == 400
    assert not CALLS and "graph1" in ST["servers"]
    r = c.delete(url(cid, "graph1"), params={"confirm": True, "type_name": "graph1"})
    assert r.status_code == 200 and CALLS == [("DELETE", "/cluster/metrics/server/graph1", {})] and "graph1" not in ST["servers"]
    assert c.delete(url(cid, "graph1"), params={"confirm": True, "type_name": "graph1"}).status_code == 404


def test_delete_dry_run(api):
    c, cid = api
    d = c.delete(url(cid, "graph1"), params={"dry_run": True})
    assert d.status_code == 200 and d.json() == {"dry_run": True, "remove": ["graph1"], "retype": "graph1"} and not CALLS


# ---------------------------------------------------------------- relecture, audit, secrets
@pytest.mark.parametrize("call", [
    lambda c, cid: c.post(url(cid), json={"id": "n1", "type": "graphite", "server": "10.1.2.3", "port": 2003, "confirm": True}),
    lambda c, cid: c.put(url(cid, "graph1"), json={"mtu": 1400}),
    lambda c, cid: c.delete(url(cid, "graph1"), params={"confirm": True, "type_name": "graph1"}),
], ids=["create", "update", "delete"])
def test_unapplied_change_is_a_502(api, call):
    c, cid = api
    ST["noapply"] = True
    r = call(c, cid)
    assert r.status_code == 502 and "n'a pas" in r.json()["detail"] and audit_pairs(c)[-1][1] == "error"


def test_every_write_and_refusal_is_audited_without_secret(api):
    c, cid = api
    c.post(url(cid), json={"id": "n1", "type": "influxdb", "server": "10.1.2.3", "port": 8086, "token": TOKEN})                       # refus : pas de confirm
    c.post(url(cid), json={"id": "n1", "type": "influxdb", "server": "10.1.2.3", "port": 8086, "token": TOKEN, "confirm": True})         # succès
    c.delete(url(cid, "n1"), params={"confirm": True})                                                                                    # refus : identifiant non retapé
    pairs = audit_pairs(c)
    assert pairs.count(("metrics-server-create", "error")) == 1 and pairs.count(("metrics-server-create", "started")) == 1 and ("metrics-server-delete", "error") in pairs
    assert TOKEN not in c.get("/api/audit").text and SECRET not in c.get("/api/audit").text


def test_proxmox_error_never_leaks_its_message(api):
    c, cid = api
    ST["fail"] = True
    r = c.put(url(cid, "influx1"), json={"organization": "x", "token": TOKEN})
    assert r.status_code == 502 and SECRET not in r.text and TOKEN not in r.text and SECRET not in c.get("/api/audit").text and TOKEN not in c.get("/api/audit").text


def test_requires_authentication(client):
    for m, p in (("get", ""), ("get", "/x1"), ("post", ""), ("put", "/x1"), ("delete", "/x1")):
        assert getattr(client, m)(url(1, p.lstrip("/"))).status_code == 401
