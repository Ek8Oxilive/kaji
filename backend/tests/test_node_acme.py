import httpx
import pytest

from app import acmespec as A
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
UPID = "UPID:enzo:0001A2B3:00C4D5E6:67890ABC:acmeregister:default:kaji@pve!kaji:"
PROD = "https://acme-v02.api.letsencrypt.org/directory"
STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"
TOS = "https://letsencrypt.org/documents/LE-SA-v1.8.pdf"
DIGEST = "ab" * 20
CALLS: list[tuple[str, str, str]] = []
ST: dict = {}

# schémas réels (Proxmox 9.1.9) : tout autre paramètre = 400
SCHEMA = {("POST", "/cluster/acme/account"): {"name", "contact", "directory", "tos_url"}, ("DELETE", "/cluster/acme/account/"): set(),
          ("POST", "/certificates/acme/certificate"): {"force"}, ("PUT", "/certificates/acme/certificate"): {"force"}}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    q = request.url.query.decode() + request.content.decode()
    CALLS.append((request.method, p, q))
    sent = set(httpx.QueryParams(q).keys())
    for (m, frag), allowed in SCHEMA.items():
        if request.method == m and frag in p and sent != allowed:
            return httpx.Response(400, json={"data": None, "message": "Parameter verification failed.", "errors": {k: "schema" for k in sent ^ allowed}})
    if request.method == "PUT" and p.endswith("/config"):
        ok = {"acme", "delete", "digest"} | {f"acmedomain{i}" for i in range(5)}
        if not sent <= ok:
            return httpx.Response(400, json={"data": None, "message": "Parameter verification failed."})
    if request.method == "GET":
        if p in ST.get("down", ()):
            return httpx.Response(500, json={"data": None, "message": SECRET})
        if p == "/cluster/acme/directories":
            return httpx.Response(200, json={"data": [{"name": "LE", "url": PROD}, {"name": "LE staging", "url": STAGING}]})
        if p == "/cluster/acme/tos":
            return httpx.Response(200, json={"data": None if ST.get("tos_null") else TOS})
        if p == "/cluster/acme/account":
            return httpx.Response(200, json={"data": [{"name": n} for n in ST.get("accounts", ["default"])]})
        if p.startswith("/cluster/acme/account/"):
            n = p.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"data": {"account": {"contact": ["mailto:moi@exemple.org"], "status": "valid"}, "directory": ST.get("dir", {}).get(n, PROD), "location": "x", "tos": TOS}})
        if p == "/cluster/acme/plugins":
            return httpx.Response(200, json={"data": [{"plugin": "standalone", "type": "standalone", "data": {"SECRET_TOKEN": SECRET}}, {"plugin": "cf", "type": "dns", "data": {"CF_Token": SECRET}}]})
        if p == "/nodes":
            return httpx.Response(200, json={"data": [{"node": "enzo"}, {"node": "enzo2"}]})
        if p.endswith("/config"):
            node = p.split("/")[2]
            return httpx.Response(200, json={"data": ST.get("config", {}).get(node, {"digest": DIGEST})})
        if p.endswith("/certificates/info"):
            return httpx.Response(200, json={"data": [{"filename": "pve-ssl.pem"}] + ([{"filename": "pveproxy-ssl.pem"}] if ST.get("has_custom") else [])})
        return httpx.Response(404, json={"data": None})
    if ST.get("write_fail"):
        return httpx.Response(403, json={"data": None, "message": SECRET})
    return httpx.Response(200, json={"data": UPID if "config" not in p else None})


@pytest.fixture
def api(client):
    CALLS.clear()
    ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def writes():
    return [x for x in CALLS if x[0] != "GET"]


def create(c, cid, **b):
    return c.post(f"/api/connections/{cid}/acme/accounts", json={"name": "perso", "contact": "moi@exemple.org", "directory": STAGING, "accept_tos": True, "confirm": True, **b})


def cfg(c, cid, **b):
    return c.put(f"/api/connections/{cid}/nodes/enzo/acme/config", json={"account": "default", "domains": [{"domain": "pve.exemple.org"}], "confirm": True, **b})


def order(c, cid, kind="order", **b):
    return c.post(f"/api/connections/{cid}/nodes/enzo/acme/{kind}", json={"confirm": True, **b})


# ---------------------------------------------------------------- lecture
def test_read_has_no_plugin_secret(api):
    c, cid = api
    r = c.get(f"/api/connections/{cid}/nodes/enzo/acme")
    d = r.json()
    assert r.status_code == 200 and all(v["state"] == "ok" for v in d.values())
    assert d["accounts"]["data"] == [{"name": "default", "directory": PROD, "contact": ["moi@exemple.org"], "status": "valid"}]
    assert d["plugins"]["data"] == [{"id": "standalone", "type": "standalone"}, {"id": "cf", "type": "dns"}] and SECRET not in r.text
    assert d["tos"]["data"] == TOS and [x["url"] for x in d["directories"]["data"]] == [PROD, STAGING]
    assert not writes()


def test_read_section_failure_is_isolated(api):
    c, cid = api
    ST["down"] = ("/cluster/acme/plugins",)
    d = c.get(f"/api/connections/{cid}/nodes/enzo/acme").json()
    assert d["plugins"]["state"] == "error" and d["accounts"]["state"] == "ok" and SECRET not in str(d)


def test_node_config_parsing():
    c = A.shape_node_acme({"acme": "account=default", "acmedomain0": "domain=a.exemple.org,plugin=cf", "acmedomain1": "domain=b.exemple.org", "digest": DIGEST, "autre": "x"})
    assert c == {"account": "default", "domains": [{"slot": 0, "domain": "a.exemple.org", "plugin": "cf"}, {"slot": 1, "domain": "b.exemple.org", "plugin": None}], "digest": DIGEST}
    assert A.shape_node_acme("x") == {"account": None, "domains": [], "digest": None}


# ---------------------------------------------------------------- compte
def test_create_account_sends_exact_schema_with_live_tos(api):
    c, cid = api
    r = create(c, cid)
    assert r.status_code == 202 and r.json() == {"upid": UPID}
    assert writes() == [("POST", "/cluster/acme/account", f"name=perso&contact=moi%40exemple.org&directory=https%3A%2F%2Facme-staging-v02.api.letsencrypt.org%2Fdirectory&tos_url=https%3A%2F%2Fletsencrypt.org%2Fdocuments%2FLE-SA-v1.8.pdf")]


def test_tos_is_the_live_one_never_the_clients(api):
    c, cid = api
    create(c, cid, tos_url="https://evil.example/tos", eab_kid="x", **{"eab-hmac-key": "y"})
    assert "evil" not in writes()[0][2] and "eab" not in writes()[0][2]


def test_account_needs_tos_and_confirm(api):
    c, cid = api
    assert create(c, cid, accept_tos=False).status_code == 400 and create(c, cid, confirm=False).status_code == 400
    assert not writes()


@pytest.mark.parametrize("contact", ["", "moi", "moi@", "@exemple.org", "moi@exemple", "a b@exemple.org", "moi@exemple.org\nBcc: x@y.z", "x" * 300 + "@exemple.org"])
def test_contact_validated(api, contact):
    c, cid = api
    assert create(c, cid, contact=contact).status_code in (422,) and not writes()


def test_directory_must_be_listed_and_name_unused(api):
    c, cid = api
    assert create(c, cid, directory="https://evil.example/directory").status_code == 422
    assert create(c, cid, directory="http://acme-v02.api.letsencrypt.org/directory").status_code == 422
    assert create(c, cid, name="default").status_code == 409
    assert not writes()


@pytest.mark.parametrize("name", ["", "A", "1a", "a b", "a;b", "-a", "a" * 33])
def test_account_name_validated(api, name):
    c, cid = api
    assert create(c, cid, name=name).status_code == 422 and not CALLS


def test_unreadable_state_refuses_account(api):
    c, cid = api
    ST["down"] = ("/cluster/acme/tos",)
    r = create(c, cid)
    assert r.status_code == 502 and SECRET not in r.text and not writes()


def test_missing_terms_of_service_refuses_account(api):
    c, cid = api
    ST["tos_null"] = True
    assert create(c, cid).status_code == 502 and not writes()


def test_delete_account(api):
    c, cid = api
    url = f"/api/connections/{cid}/acme/accounts/default/delete"
    assert c.post(url, json={"confirm": True, "type_name": "default"}).status_code == 202
    assert writes() == [("DELETE", "/cluster/acme/account/default", "")]


def test_delete_account_guards(api):
    c, cid = api
    url = lambda n: f"/api/connections/{cid}/acme/accounts/{n}/delete"          # noqa: E731
    assert c.post(url("default"), json={"confirm": False, "type_name": "default"}).status_code == 400
    for typed in (None, "", "defaul", "DEFAULT"):
        assert c.post(url("default"), json={"confirm": True, "type_name": typed}).status_code == 400
    assert c.post(url("inconnu"), json={"confirm": True, "type_name": "inconnu"}).status_code == 404
    ST["config"] = {"enzo2": {"acme": "account=default", "digest": DIGEST}}
    r = c.post(url("default"), json={"confirm": True, "type_name": "default"})
    assert r.status_code == 422 and "enzo2" in r.json()["detail"]
    ST["down"] = ("/nodes/enzo2/config",)
    assert c.post(url("default"), json={"confirm": True, "type_name": "default"}).status_code == 502
    assert not writes()


# ---------------------------------------------------------------- configuration du nœud
def test_config_written_with_only_acme_fields(api):
    c, cid = api
    ST["config"] = {"enzo": {"acme": "account=old", "acmedomain0": "domain=a.exemple.org", "acmedomain1": "domain=b.exemple.org", "acmedomain2": "domain=c.exemple.org", "digest": DIGEST, "description": "notes"}}
    r = cfg(c, cid, domains=[{"domain": "pve.exemple.org", "plugin": "cf"}, {"domain": "*.exemple.org", "plugin": "cf"}])
    assert r.status_code == 200
    m, p, body = writes()[0]
    q = httpx.QueryParams(body)
    assert (m, p) == ("PUT", "/nodes/enzo/config") and q["acme"] == "account=default" and q["acmedomain0"] == "domain=pve.exemple.org,plugin=cf"
    assert q["acmedomain1"] == "domain=*.exemple.org,plugin=cf" and q["delete"] == "acmedomain2" and q["digest"] == DIGEST and "description" not in q


def test_config_guards(api):
    c, cid = api
    assert cfg(c, cid, confirm=False).status_code == 400
    assert cfg(c, cid, account="inconnu").status_code == 404
    assert cfg(c, cid, domains=[{"domain": "*.exemple.org"}]).status_code == 422                          # générique sans plugin DNS
    assert cfg(c, cid, domains=[{"domain": "a.exemple.org", "plugin": "absent"}]).status_code == 422
    assert cfg(c, cid, domains=[{"domain": "a.exemple.org"}, {"domain": "A.exemple.org"}]).status_code == 422
    assert cfg(c, cid, digest="cd" * 20).status_code == 409                                              # périmé
    assert not writes()


@pytest.mark.parametrize("domain", ["", "localhost", "10.0.0.1", "a..exemple.org", "-a.exemple.org", "a_b.exemple.org", "a.exemple.org,plugin=x", "a.exemple.org\nacmedomain1=x",
                                    "a b.exemple.org", "*exemple.org", "*.*.exemple.org", "exemple.org/x", "a.exemple.o", "x" * 260 + ".org"])
def test_domain_validated(api, domain):
    c, cid = api
    assert cfg(c, cid, domains=[{"domain": domain}]).status_code == 422 and not writes()


def test_config_limits(api):
    c, cid = api
    assert cfg(c, cid, domains=[]).status_code == 422
    assert cfg(c, cid, domains=[{"domain": f"d{i}.exemple.org"} for i in range(6)]).status_code == 422
    assert cfg(c, cid, domains=[{"domain": "a.exemple.org", "plugin": "a,b"}]).status_code == 422
    assert not writes()


# ---------------------------------------------------------------- commande / renouvellement
def configured(**extra):
    return {"enzo": {"acme": "account=default", "acmedomain0": "domain=pve.exemple.org", "digest": DIGEST, **extra}}


def test_order_and_renew(api):
    c, cid = api
    ST["config"] = configured()
    assert order(c, cid).status_code == 202
    assert order(c, cid, "renew").status_code == 202
    assert writes() == [("POST", "/nodes/enzo/certificates/acme/certificate", "force=0"), ("PUT", "/nodes/enzo/certificates/acme/certificate", "force=0")]


def test_order_guards(api):
    c, cid = api
    assert order(c, cid).status_code == 409                                    # nœud pas configuré
    ST["config"] = configured()
    assert order(c, cid, confirm=False).status_code == 400
    ST["has_custom"] = True
    assert order(c, cid).status_code == 409                                    # certificat personnalisé : remplacement explicite
    assert order(c, cid, replace_existing=True).status_code == 202 and writes()[-1][2] == "force=1"
    assert order(c, cid, "renew").status_code == 202 and writes()[-1][2] == "force=0"      # le renouvellement ne force jamais


def test_staging_order_refused_when_connection_verifies_tls(api):
    c, cid = api
    ST["config"] = configured(acme="account=test")
    ST["dir"] = {"test": STAGING}
    assert order(c, cid).status_code == 202                                    # verify_ssl faux : permis
    n = len(writes())
    c.patch(f"/api/connections/{cid}", json={"verify_ssl": True})
    r = order(c, cid)
    assert r.status_code == 422 and "staging" in r.json()["detail"] and len(writes()) == n


def test_account_directory_unreadable_refuses_order(api):
    c, cid = api
    ST["config"] = configured()
    ST["dir"] = {"default": None}
    r = order(c, cid)
    assert r.status_code == 502 and not writes()


def test_renew_never_forces_even_if_asked(api):
    c, cid = api
    ST["config"] = configured()
    ST["has_custom"] = True
    assert order(c, cid, "renew", replace_existing=True).status_code == 202
    assert writes() == [("PUT", "/nodes/enzo/certificates/acme/certificate", "force=0")]


def test_unreadable_state_refuses_order(api):
    c, cid = api
    ST["config"] = configured()
    ST["down"] = ("/nodes/enzo/certificates/info",)
    assert order(c, cid).status_code == 502 and not writes()


# ---------------------------------------------------------------- transverse
def test_requires_login_and_node_validated(api):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/nodes/a;b/acme/order", json={"confirm": True})
    assert r.status_code in (404, 422) and not CALLS
    c.post("/api/auth/logout")
    assert create(c, cid).status_code == 401 and cfg(c, cid).status_code == 401 and order(c, cid).status_code == 401
    assert c.get(f"/api/connections/{cid}/nodes/enzo/acme").status_code == 401


def test_audit_success_refusal_error_without_secret(api):
    c, cid = api
    create(c, cid)
    create(c, cid, accept_tos=False)
    ST["write_fail"] = True
    assert create(c, cid, name="autre").status_code == 502
    log = c.get("/api/audit").json()[::-1]
    assert [(e["action"], e["status"]) for e in log] == [("acme-account-create", "started"), ("acme-account-create", "error"), ("acme-account-create", "error")]
    assert log[0]["upid"] == UPID and SECRET not in c.get("/api/audit").text
