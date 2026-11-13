"""Realms d'authentification (lot #379) : faux Proxmox STRICT (méthode, chemin, clés autorisées par type, motifs du schéma de Proxmox 9, secrets jamais relus).

RIEN de ce fichier n'a tourné sur un vrai cluster : le jeton de Kaji n'a pas `Realm.Allocate` et un realm mal réglé peut verrouiller la connexion.
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app import adminsession as A
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.realmspec import shape_realm

PWD = "un-mot-de-passe-solide"
PERM_SECRET = "s3cr3t-value-xyz"
BIND_PW = "bind-pw-SECRET-1"
OIDC_KEY = "oidc-client-key-SECRET-2"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": PERM_SECRET}
UUID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
ADMIN = {"user": "admin@pve", "token_id": "kaji-admin", "secret": UUID}
ADMIN_CORP = {"user": "svc@corp", "token_id": "kaji-admin", "secret": UUID}
AUTHS = {f"PVEAPIToken=admin@pve!kaji-admin={UUID}", f"PVEAPIToken=svc@corp!kaji-admin={UUID}", f"PVEAPIToken=kaji@pve!kaji={PERM_SECRET}"}
SEEN: list[httpx.Request] = []
WRITES: list[tuple[str, str, dict]] = []
ST: dict = {}
CLOCK = {"t": 1000.0}
PHRASE = "COUPURE POSSIBLE"

COMMON = {"server1", "server2", "port", "mode", "bind_dn", "password", "filter", "group_filter", "sync_attributes", "verify", "sslversion", "case-sensitive", "check-connection",
          "comment", "default", "sync-defaults-options"}
KEYS = {"ldap": COMMON | {"base_dn", "user_attr", "user_classes", "group_dn", "group_classes", "group_name_attr"}, "ad": COMMON | {"domain"},
        "openid": {"issuer-url", "client-id", "client-key", "username-claim", "scopes", "prompt", "acr-values", "autocreate", "groups-autocreate", "groups-claim", "groups-overwrite",
                   "query-userinfo", "comment", "default"},
        "pam": {"comment", "default"}, "pve": {"comment", "default"}}
REQUIRED = {"ldap": {"server1", "base_dn", "user_attr"}, "ad": {"server1", "domain"}, "openid": {"issuer-url", "client-id"}}
BOOLS = {"verify", "case-sensitive", "check-connection", "default", "autocreate", "groups-autocreate", "groups-overwrite", "query-userinfo"}
SYNC_OPT = re.compile(r"(scope=(users|groups|both)|enable-new=[01]|remove-vanished=(none|(acl|properties|entry)(;(acl|properties|entry))*))(,(scope=(users|groups|both)|enable-new=[01]|remove-vanished=[a-z;]+))*")
SECRET_KEYS = {"password", "client-key"}
UPID = "UPID:enzo:000A1B2C:00D3E4F5:6735A8C0:auth-realm-sync:corp:root@pam:"


def fresh():
    ST.clear()
    ST["realms"] = {"pam": {"type": "pam", "comment": "Linux PAM standard authentication", "default": 1}, "pve": {"type": "pve", "comment": "Proxmox VE authentication server"},
                    "corp": {"type": "ldap", "server1": "ldap.example.org", "port": 389, "mode": "ldap", "base_dn": "dc=example,dc=org", "user_attr": "uid", "bind_dn": "cn=ro,dc=example,dc=org",
                             "password": BIND_PW, "comment": "annuaire"}}
    ST["users"] = {"root@pam": {"enable": 1}, "kaji@pve": {"enable": 1}, "admin@pve": {"enable": 1}, "svc@corp": {"enable": 1}, "bob@corp": {"enable": 1}}
    ST.update(noapply=False, fail=False, leaky=False, digest=None)


def _bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def _check_values(body, typ):
    for k, v in body.items():
        if k in BOOLS and v not in ("0", "1"):
            return f"{k} : booléen attendu"
        if k == "port" and not (v.isdigit() and 1 <= int(v) <= 65535):
            return "port invalide"
        if k == "mode" and v not in ("ldap", "ldaps", "ldap+starttls"):
            return "mode invalide"
        if k == "sslversion" and v not in ("tlsv1", "tlsv1_1", "tlsv1_2", "tlsv1_3"):
            return "sslversion invalide"
        if k == "sync-defaults-options" and not SYNC_OPT.fullmatch(v):
            return "sync-defaults-options invalide"
        if k in ("server1", "server2", "base_dn", "bind_dn", "domain", "issuer-url", "client-id") and (not v or len(v) > 256):
            return f"{k} invalide"
    return None


def _public(r):
    out = {k: v for k, v in r.items() if ST["leaky"] or k not in SECRET_KEYS}
    return {**out, **({"digest": ST["digest"]} if ST["digest"] else {})}


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    m = request.method
    if request.headers.get("authorization") not in AUTHS:
        return httpx.Response(401, json={"data": None, "message": PERM_SECRET})
    if ST["fail"] and m != "GET":
        return httpx.Response(403, json={"data": None, "message": PERM_SECRET})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    ok = lambda d=None: httpx.Response(200, json={"data": d})
    if m == "GET" and p == "/access/domains":
        return ok([{"realm": r, "type": v["type"], "comment": v.get("comment", ""), **({"default": 1} if v.get("default") in (1, "1") else {})} for r, v in sorted(ST["realms"].items())])
    if m == "GET" and p == "/access/permissions":
        return ok({"/pool/kaji-test": {"Permissions.Modify": 1}})
    if m == "GET" and p == "/access/users":
        return ok([{"userid": u, **v} for u, v in sorted(ST["users"].items())])
    mm = re.fullmatch(r"/access/domains/([A-Za-z][A-Za-z0-9._\-]{1,31})(/sync)?", p)
    if m == "POST" and p == "/access/domains":
        typ, realm = body.get("type"), body.get("realm", "")
        if typ not in ("ldap", "ad", "openid") or not re.fullmatch(r"[A-Za-z][A-Za-z0-9._\-]{1,31}", realm):
            return _bad("type ou realm invalide")
        extra = set(body) - KEYS[typ] - {"realm", "type"}
        if extra:
            return _bad(f"paramètres refusés {sorted(extra)}")
        if REQUIRED[typ] - set(body):
            return _bad(f"paramètre manquant {sorted(REQUIRED[typ] - set(body))}")
        if realm in ST["realms"]:
            return _bad("realm existe déjà")
        err = _check_values(body, typ)
        if err:
            return _bad(err)
        WRITES.append((m, p, body))
        if not ST["noapply"]:
            ST["realms"][realm] = {"type": typ, **{k: (int(v) if k == "port" else (int(v) if k in BOOLS else v)) for k, v in body.items() if k not in ("realm", "type")}}
        return ok()
    if mm and not mm.group(2):
        realm = mm.group(1)
        r = ST["realms"].get(realm)
        if r is None:
            return httpx.Response(500, json={"data": None, "message": "realm introuvable"})
        if m == "GET":
            return ok(_public(r))
        if m == "DELETE":
            if body or r["type"] in ("pam", "pve"):
                return _bad("suppression refusée")
            WRITES.append((m, p, body))
            if not ST["noapply"]:
                del ST["realms"][realm]
            return ok()
        if m == "PUT":
            extra = set(body) - KEYS[r["type"]] - {"delete", "digest"}
            if extra:
                return _bad(f"paramètres refusés {sorted(extra)}")
            dl = [x for x in body.get("delete", "").split(",") if x]
            if set(dl) - KEYS[r["type"]] or set(dl) & set(body):
                return _bad("delete invalide")
            if ST["digest"] and body.get("digest") != ST["digest"]:
                return _bad("digest différent")
            err = _check_values(body, r["type"])
            if err:
                return _bad(err)
            WRITES.append((m, p, body))
            if not ST["noapply"]:
                for k, v in body.items():
                    if k not in ("delete", "digest"):
                        r[k] = int(v) if k == "port" or k in BOOLS else v
                for k in dl:
                    r.pop(k, None)
            return ok()
    if mm and mm.group(2) and m == "POST":
        r = ST["realms"].get(mm.group(1))
        if r is None or r["type"] not in ("ldap", "ad"):
            return httpx.Response(500, json={"data": None, "message": "pas de synchronisation pour ce realm"})
        extra = set(body) - {"dry-run", "scope", "enable-new", "remove-vanished"}
        if extra:
            return _bad(f"paramètres refusés {sorted(extra)}")
        if body.get("dry-run") not in ("0", "1") or ("scope" in body and body["scope"] not in ("users", "groups", "both")):
            return _bad("valeur invalide")
        if "remove-vanished" in body and not re.fullmatch(r"(acl|properties|entry)(;(acl|properties|entry))*", body["remove-vanished"]):
            return _bad("remove-vanished invalide")
        WRITES.append((m, p, body))
        return ok(UPID)
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client, monkeypatch):
    SEEN.clear(); WRITES.clear(); fresh(); CLOCK["t"] = 1000.0
    A.sessions.clear()
    monkeypatch.setattr(A, "_now", lambda: CLOCK["t"])
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    assert client.post(f"/api/connections/{cid}/admin-session", json=ADMIN).status_code == 201
    SEEN.clear()
    yield client, cid
    A.sessions.clear()
    app.dependency_overrides.clear()


def u(cid, tail=""):
    return f"/api/connections/{cid}/access/realms{tail}"


def audit_text(c):
    return c.get("/api/audit").text


def no_secret(*texts):
    return all(s not in t for t in texts for s in (BIND_PW, OIDC_KEY, PERM_SECRET, UUID))


LDAP = {"realm": "ldap2", "type": "ldap", "server1": "ldap2.example.org", "base_dn": "dc=example,dc=org", "user_attr": "uid", "confirm": True, "type_name": "ldap2"}


def create(c, cid, **over):
    body = {**LDAP, **over}
    return c.post(u(cid), json={k: v for k, v in body.items() if v is not None})


# ---------------------------------------------------------------- lecture
def test_read_a_realm_without_any_secret_and_with_a_stable_digest(api):
    c, cid = api
    ST["leaky"] = True                                                   # un Proxmox qui renverrait le mot de passe : Kaji ne doit jamais le relayer
    r = c.get(u(cid, "/corp"))
    j = r.json()
    assert r.status_code == 200 and j["type"] == "ldap" and j["server1"] == "ldap.example.org" and j["port"] == 389 and j["base_dn"] == "dc=example,dc=org" and j["builtin"] is False
    assert "password" not in j and BIND_PW not in r.text and len(j["digest"]) == 40 and c.get(u(cid, "/corp")).json()["digest"] == j["digest"]
    assert c.get(u(cid, "/pam")).json()["builtin"] is True and c.get(u(cid, "/pam")).json()["default"] is True


def test_shape_drops_hostile_values_and_fields_of_other_types():
    s = shape_realm({"type": "openid", "issuer-url": "https://x", "client-key": OIDC_KEY, "password": BIND_PW, "server1": "no", "port": True, "verify": "oui", "scopes": "a" * 5000}, "oid1")
    assert s["type"] == "openid" and "server1" not in s and "port" not in s and OIDC_KEY not in repr(s) and BIND_PW not in repr(s) and len(s["scopes"]) <= 2048
    assert shape_realm({"type": "bogus"}, "x") is None and shape_realm("x", "x") is None and shape_realm({"type": "ldap", "port": True, "verify": "oui"}, "l")["port"] is None


def test_read_requires_a_session(client):
    assert client.get(u(1, "/corp")).status_code == 401


# ---------------------------------------------------------------- création
def test_create_ldap_exact_params_and_no_secret_back(api):
    c, cid = api
    r = create(c, cid, port=636, mode="ldaps", bind_dn="cn=ro,dc=example,dc=org", password=BIND_PW, verify=True, sslversion="tlsv1_3", case_sensitive=False, comment="ldap de test",
               sync_defaults_options={"scope": "users", "enable_new": False, "remove_vanished": ["acl"]})
    assert r.status_code == 201, r.text
    assert WRITES[-1] == ("POST", "/access/domains", {"realm": "ldap2", "type": "ldap", "server1": "ldap2.example.org", "base_dn": "dc=example,dc=org", "user_attr": "uid", "port": "636",
                                                      "mode": "ldaps", "bind_dn": "cn=ro,dc=example,dc=org", "password": BIND_PW, "verify": "1", "sslversion": "tlsv1_3", "case-sensitive": "0",
                                                      "comment": "ldap de test", "sync-defaults-options": "scope=users,enable-new=0,remove-vanished=acl"})
    assert no_secret(r.text, audit_text(c)) and "password" not in r.json() and r.json()["created"] == "ldap2" and r.json()["port"] == 636
    assert "password=défini" in audit_text(c)


def test_create_ad_and_openid_exact_params(api):
    c, cid = api
    assert c.post(u(cid), json={"realm": "ad1", "type": "ad", "server1": "10.0.0.9", "domain": "example.org", "default": True, "confirm": True, "type_name": "ad1"}).status_code == 201
    assert WRITES[-1][2] == {"realm": "ad1", "type": "ad", "server1": "10.0.0.9", "domain": "example.org", "default": "1"}
    r = c.post(u(cid), json={"realm": "oidc1", "type": "openid", "issuer_url": "https://sso.example.org/realms/main", "client_id": "kaji", "client_key": OIDC_KEY, "autocreate": True,
                             "username_claim": "email", "scopes": "openid email profile", "query_userinfo": False, "confirm": True, "type_name": "oidc1"})
    assert r.status_code == 201, r.text
    assert WRITES[-1][2] == {"realm": "oidc1", "type": "openid", "issuer-url": "https://sso.example.org/realms/main", "client-id": "kaji", "client-key": OIDC_KEY, "autocreate": "1",
                             "username-claim": "email", "scopes": "openid email profile", "query-userinfo": "0"}
    assert no_secret(r.text, audit_text(c)) and "client_key" not in r.json() and "client-key" not in r.json()


def test_sync_defaults_with_nothing_to_remove_is_sent_as_none(api):
    c, cid = api
    assert create(c, cid, sync_defaults_options={"remove_vanished": []}).status_code == 201
    assert WRITES[-1][2]["sync-defaults-options"] == "remove-vanished=none"
    assert create(c, cid, realm="ldap3", type_name="ldap3", sync_defaults_options={"scope": "both", "remove_vanished": ["entry", "entry", "acl"]}).status_code == 201
    assert WRITES[-1][2]["sync-defaults-options"] == "scope=both,remove-vanished=entry;acl"                         # doublons écartés, ordre gardé


def test_create_dry_run_writes_nothing_and_masks_the_secrets(api):
    c, cid = api
    r = create(c, cid, password=BIND_PW, bind_dn="cn=ro,dc=example,dc=org", dry_run=True, confirm=False, type_name=None)
    assert r.status_code == 201 and r.json()["dry_run"] is True and r.json()["params"]["password"] == "défini" and BIND_PW not in r.text and not WRITES


def test_create_needs_confirm_and_the_realm_retyped(api):
    c, cid = api
    assert create(c, cid, confirm=False).status_code == 400 and create(c, cid, type_name="autre").status_code == 400 and create(c, cid, type_name=None).status_code == 400 and not WRITES
    assert ("realm-create", "error") in [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


def test_create_refusals(api):
    c, cid = api
    assert create(c, cid, realm="corp", type_name="corp").status_code == 409
    for builtin in ("pam", "pve"):
        assert create(c, cid, realm=builtin, type_name=builtin).status_code == 422
    assert create(c, cid, server1=None).status_code == 422 and create(c, cid, base_dn=None).status_code == 422 and create(c, cid, user_attr=None).status_code == 422
    assert c.post(u(cid), json={"realm": "oid2", "type": "openid", "client_id": "x", "confirm": True, "type_name": "oid2"}).status_code == 422          # issuer_url manquant
    assert c.post(u(cid), json={"realm": "ad2", "type": "ad", "server1": "a.example.org", "confirm": True, "type_name": "ad2"}).status_code == 422       # domain manquant
    assert not WRITES


@pytest.mark.parametrize("typ,field", [("ldap", {"issuer_url": "https://x.example.org"}), ("ldap", {"domain": "x.org"}), ("ldap", {"client_key": "k"}), ("ad", {"base_dn": "dc=x"}),
                                       ("ad", {"user_attr": "uid"}), ("openid", {"server1": "a.example.org"}), ("openid", {"password": "p"}), ("openid", {"port": 389}),
                                       ("openid", {"verify": True})])
def test_a_field_of_another_type_is_refused(api, typ, field):
    c, cid = api
    base = {"ldap": LDAP, "ad": {"realm": "ad9", "type": "ad", "server1": "a.example.org", "domain": "x.org", "confirm": True, "type_name": "ad9"},
            "openid": {"realm": "oid9", "type": "openid", "issuer_url": "https://x.example.org", "client_id": "c", "confirm": True, "type_name": "oid9"}}[typ]
    r = c.post(u(cid), json={**base, **field})
    assert r.status_code == 422 and not WRITES


@pytest.mark.parametrize("over", [
    {"port": 0}, {"port": 70000}, {"port": "389"}, {"port": True}, {"port": 3.5}, {"mode": "plain"}, {"sslversion": "tlsv1"}, {"sslversion": "tlsv1_1"}, {"verify": "true"}, {"verify": 1},
    {"server1": "127.0.0.1"}, {"server1": "localhost"}, {"server1": "ldap.localhost"}, {"server1": "0.0.0.0"}, {"server1": "169.254.1.1"}, {"server1": "a b"}, {"server1": ""}, {"server2": "[::1]"},
    {"base_dn": "dc=a\nb"}, {"base_dn": " "}, {"base_dn": "x" * 257}, {"bind_dn": "a\x00b"}, {"user_attr": "u"}, {"user_attr": "a b"}, {"user_attr": "x" * 257},
    {"filter": "x" * 2049}, {"filter": "(a)\n(b)"}, {"group_filter": "a\x7fb"}, {"user_classes": "a b c;;"}, {"user_classes": "../x"}, {"group_classes": "a," * 30}, {"group_name_attr": "a b"},
    {"sync_attributes": "pas-une-paire"}, {"sync_attributes": "a=b,c"}, {"comment": "a\x00b"}, {"comment": "x" * 513}, {"password": ""}, {"password": "a\nb"}, {"password": "x" * 513},
    {"sync_defaults_options": {"scope": "tous"}}, {"sync_defaults_options": {"enable_new": "oui"}}, {"sync_defaults_options": {"remove_vanished": ["users"]}}, {"sync_defaults_options": {}},
    {"realm": "1abc", "type_name": "1abc"}, {"realm": "a", "type_name": "a"}, {"realm": "x" * 33, "type_name": "x" * 33}, {"realm": "a b", "type_name": "a b"}, {"realm": "../x", "type_name": "../x"},
    {"type": "pam"}, {"type": "pve"}, {"type": "bogus"}, {"confirm": "true"},
])
def test_create_values_are_validated_before_anything_is_sent(api, over):
    c, cid = api
    assert create(c, cid, **over).status_code == 422 and not WRITES


@pytest.mark.parametrize("over", [
    {"issuer_url": "http://sso.example.org"}, {"issuer_url": "https://user:pw@sso.example.org"}, {"issuer_url": "https://sso.example.org?x=1"}, {"issuer_url": "https://127.0.0.1/"},
    {"issuer_url": "https://localhost/realms/x"}, {"issuer_url": "https://sso.example.org:99999"}, {"issuer_url": "https://"}, {"issuer_url": "https://a b"}, {"issuer_url": "ftp://x"},
    {"client_id": "a b"}, {"client_id": ""}, {"client_key": ""}, {"scopes": "a  b"}, {"scopes": "a\nb"}, {"username_claim": "a b"}, {"groups_claim": "../x"}, {"prompt": "a b"},
    {"acr_values": "a b"}, {"acr_values": 'a"b'}, {"autocreate": "yes"}, {"query_userinfo": 0},
])
def test_openid_values_are_validated(api, over):
    c, cid = api
    body = {"realm": "oid3", "type": "openid", "issuer_url": "https://sso.example.org", "client_id": "kaji", "confirm": True, "type_name": "oid3", **over}
    assert c.post(u(cid), json=body).status_code == 422 and not WRITES


def test_create_not_applied_by_proxmox_is_a_bad_gateway(api):
    c, cid = api
    ST["noapply"] = True
    r = create(c, cid)
    assert r.status_code == 502 and "n'a pas créé" in r.json()["detail"]
    assert ("realm-create", "error") in [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# ---------------------------------------------------------------- modification
def test_update_sends_only_what_changed_and_reads_back(api):
    c, cid = api
    r = c.put(u(cid, "/corp"), json={"comment": "nouveau", "check_connection": True, "confirm": True, "type_name": "corp"})
    assert r.status_code == 200, r.text
    assert WRITES[-1] == ("PUT", "/access/domains/corp", {"comment": "nouveau", "check-connection": "1"})
    assert r.json()["updated"] == "corp" and r.json()["comment"] == "nouveau" and r.json()["check_connection"] is True and len(r.json()["digest"]) == 40


def test_update_builtin_realms_only_comment_and_default(api):
    c, cid = api
    assert c.put(u(cid, "/pve"), json={"comment": "interne", "default": True, "confirm": True, "type_name": "pve"}).status_code == 200
    assert WRITES[-1][2] == {"comment": "interne", "default": "1"}
    for field in ({"server1": "a.example.org"}, {"verify": True}, {"port": 389}):
        assert c.put(u(cid, "/pam"), json={**field, "confirm": True, "type_name": "pam"}).status_code == 422
    assert len(WRITES) == 1


def test_update_refusals(api):
    c, cid = api
    assert c.put(u(cid, "/nope"), json={"comment": "x", "confirm": True, "type_name": "nope"}).status_code == 404
    assert c.put(u(cid, "/corp"), json={"comment": "x", "confirm": False, "type_name": "corp"}).status_code == 400
    assert c.put(u(cid, "/corp"), json={"comment": "x", "confirm": True, "type_name": "autre"}).status_code == 400
    assert c.put(u(cid, "/corp"), json={"confirm": True, "type_name": "corp"}).status_code == 422                                              # rien à modifier
    assert c.put(u(cid, "/corp"), json={"issuer_url": "https://x.example.org", "confirm": True, "type_name": "corp"}).status_code == 422          # champ d'un autre type
    assert c.put(u(cid, "/corp"), json={"comment": "a", "clear": ["comment"], "confirm": True, "type_name": "corp"}).status_code == 422          # modifié et retiré
    assert c.put(u(cid, "/corp"), json={"clear": ["client_key"], "confirm": True, "type_name": "corp"}).status_code == 422                       # réglage d'un autre type
    assert c.put(u(cid, "/corp"), json={"clear": ["server1"], "confirm": True, "type_name": "corp"}).status_code == 422                          # obligatoire : pas retirable
    assert not WRITES


def test_update_clear_sends_proxmox_names_with_dashes(api):
    c, cid = api
    ST["realms"]["corp"]["filter"] = "(uid=*)"
    ST["realms"]["corp"]["check-connection"] = 1
    r = c.put(u(cid, "/corp"), json={"clear": ["check_connection", "filter", "comment"], "confirm": True, "type_name": "corp"})
    assert r.status_code == 200, r.text
    assert WRITES[-1][2] == {"delete": "check-connection,filter,comment"} and "check-connection" not in ST["realms"]["corp"] and "filter" not in ST["realms"]["corp"]


def test_update_stale_digest_is_refused(api):
    c, cid = api
    d = c.get(u(cid, "/corp")).json()["digest"]
    ST["realms"]["corp"]["comment"] = "modifié ailleurs"
    assert c.put(u(cid, "/corp"), json={"comment": "x", "digest": d, "confirm": True, "type_name": "corp"}).status_code == 409 and not WRITES
    d2 = c.get(u(cid, "/corp")).json()["digest"]
    assert c.put(u(cid, "/corp"), json={"comment": "x", "digest": d2, "confirm": True, "type_name": "corp"}).status_code == 200


def test_changing_how_accounts_log_in_needs_the_phrase_when_the_realm_has_accounts(api):
    c, cid = api
    body = {"server1": "ldap-bis.example.org", "confirm": True, "type_name": "corp"}
    r = c.put(u(cid, "/corp"), json=body)
    assert r.status_code == 409 and "2 compte" in r.json()["detail"] and "server1" in r.json()["detail"] and not WRITES
    assert c.put(u(cid, "/corp"), json={**body, "acknowledge_cut_access": True}).status_code == 409
    assert c.put(u(cid, "/corp"), json={**body, "phrase": PHRASE}).status_code == 409
    assert c.put(u(cid, "/corp"), json={**body, "acknowledge_cut_access": True, "phrase": "coupure possible"}).status_code == 409
    assert c.put(u(cid, "/corp"), json={**body, "acknowledge_cut_access": True, "phrase": PHRASE}).status_code == 200
    assert WRITES[-1][2] == {"server1": "ldap-bis.example.org"}


def test_changing_the_password_or_clearing_a_login_setting_also_needs_the_phrase(api):
    c, cid = api
    assert c.put(u(cid, "/corp"), json={"password": BIND_PW + "2", "confirm": True, "type_name": "corp"}).status_code == 409
    assert c.put(u(cid, "/corp"), json={"clear": ["mode"], "confirm": True, "type_name": "corp"}).status_code == 409
    assert not WRITES


def test_no_phrase_when_nothing_about_login_changes_or_the_realm_has_no_account(api):
    c, cid = api
    assert c.put(u(cid, "/corp"), json={"comment": "x", "default": True, "filter": "(uid=*)", "confirm": True, "type_name": "corp"}).status_code == 200
    del ST["users"]["svc@corp"], ST["users"]["bob@corp"]
    assert c.put(u(cid, "/corp"), json={"server1": "ldap-ter.example.org", "confirm": True, "type_name": "corp"}).status_code == 200


def test_update_dry_run_reports_the_locks_and_writes_nothing(api):
    c, cid = api
    r = c.put(u(cid, "/corp"), json={"server1": "ldap-bis.example.org", "password": BIND_PW, "dry_run": True})
    assert r.status_code == 200 and r.json()["locks"] == {"login_fields": ["password", "server1"], "users": 2, "cut": True} and r.json()["params"]["password"] == "défini"
    assert BIND_PW not in r.text and not WRITES
    assert c.put(u(cid, "/corp"), json={"comment": "x", "dry_run": True}).json()["locks"]["cut"] is False


def test_update_not_applied_is_a_bad_gateway(api):
    c, cid = api
    ST["noapply"] = True
    r = c.put(u(cid, "/corp"), json={"comment": "x", "confirm": True, "type_name": "corp"})
    assert r.status_code == 502 and "n'a pas appliqué" in r.json()["detail"]
    ST["realms"]["corp"]["check-connection"] = 1
    assert c.put(u(cid, "/corp"), json={"clear": ["check_connection"], "confirm": True, "type_name": "corp"}).status_code == 502


# ---------------------------------------------------------------- suppression
def test_delete_a_realm_with_its_name_retyped(api):
    c, cid = api
    del ST["users"]["svc@corp"], ST["users"]["bob@corp"]
    ST["realms"]["vide"] = {"type": "openid", "issuer-url": "https://x.example.org", "client-id": "c"}
    assert c.delete(u(cid, "/vide")).status_code == 400 and c.delete(u(cid, "/vide?confirm=true&name=autre")).status_code == 400 and not WRITES
    r = c.delete(u(cid, "/vide?confirm=true&name=vide"))
    assert r.status_code == 200 and r.json() == {"deleted": "vide"} and WRITES[-1][:2] == ("DELETE", "/access/domains/vide") and "vide" not in ST["realms"]


def test_delete_builtin_realms_is_always_refused(api):
    c, cid = api
    for b in ("pam", "pve"):
        assert c.delete(u(cid, f"/{b}?confirm=true&name={b}&acknowledge_cut_access=true&phrase={PHRASE}")).status_code == 403
    assert not WRITES


def test_delete_the_realm_of_kajis_own_account_or_of_the_admin_session_is_always_refused(api):
    c, cid = api
    assert c.delete(f"/api/connections/{cid}/admin-session").status_code in (200, 204)
    assert c.post(f"/api/connections/{cid}/admin-session", json=ADMIN_CORP).status_code == 201
    r = c.delete(u(cid, f"/corp?confirm=true&name=corp&acknowledge_cut_access=true&phrase={PHRASE}"))
    assert r.status_code == 403 and "couperait Kaji" in r.json()["detail"] and not [w for w in WRITES if w[0] == "DELETE"]


def test_delete_a_realm_with_accounts_or_default_needs_the_phrase(api):
    c, cid = api
    q = "/corp?confirm=true&name=corp"
    r = c.delete(u(cid, q))
    assert r.status_code == 409 and "2 compte" in r.json()["detail"] and not WRITES
    assert c.delete(u(cid, q + "&acknowledge_cut_access=true")).status_code == 409 and c.delete(u(cid, q + f"&phrase={PHRASE}")).status_code == 409
    assert c.delete(u(cid, q + f"&acknowledge_cut_access=true&phrase={PHRASE}")).status_code == 200 and "corp" not in ST["realms"]
    ST["realms"]["vide"] = {"type": "openid", "issuer-url": "https://x.example.org", "client-id": "c", "default": 1}
    assert c.delete(u(cid, "/vide?confirm=true&name=vide")).status_code == 409                                  # realm par défaut, sans compte


def test_delete_dry_run_and_unknown_and_not_applied(api):
    c, cid = api
    r = c.delete(u(cid, "/corp?dry_run=true"))
    assert r.status_code == 200 and r.json()["locks"] == {"users": 2, "default": False, "cut": True} and not WRITES
    assert c.delete(u(cid, "/nope?confirm=true&name=nope")).status_code == 404
    ST["noapply"] = True
    r = c.delete(u(cid, f"/corp?confirm=true&name=corp&acknowledge_cut_access=true&phrase={PHRASE}"))
    assert r.status_code == 502 and "n'a pas supprimé" in r.json()["detail"]


# ---------------------------------------------------------------- synchronisation
def test_sync_is_a_simulation_by_default(api):
    c, cid = api
    r = c.post(u(cid, "/corp/sync"), json={})
    assert r.status_code == 200 and r.json() == {"upid": UPID, "dry_run": True, "params": {"dry-run": "1"}}
    assert WRITES[-1] == ("POST", "/access/domains/corp/sync", {"dry-run": "1"})


def test_a_real_sync_needs_confirm_and_the_realm_retyped(api):
    c, cid = api
    assert c.post(u(cid, "/corp/sync"), json={"dry_run": False}).status_code == 400
    assert c.post(u(cid, "/corp/sync"), json={"dry_run": False, "confirm": True, "type_name": "autre"}).status_code == 400 and not WRITES
    r = c.post(u(cid, "/corp/sync"), json={"dry_run": False, "confirm": True, "type_name": "corp", "scope": "both", "enable_new": False})
    assert r.status_code == 200 and WRITES[-1][2] == {"dry-run": "0", "scope": "both", "enable-new": "0"}


def test_removing_vanished_entries_needs_the_phrase(api):
    c, cid = api
    body = {"dry_run": False, "confirm": True, "type_name": "corp", "remove_vanished": ["acl", "entry"]}
    assert c.post(u(cid, "/corp/sync"), json=body).status_code == 409 and not WRITES
    assert c.post(u(cid, "/corp/sync"), json={**body, "acknowledge_cut_access": True}).status_code == 409
    assert c.post(u(cid, "/corp/sync"), json={**body, "acknowledge_cut_access": True, "phrase": "non"}).status_code == 409
    assert c.post(u(cid, "/corp/sync"), json={**body, "acknowledge_cut_access": True, "phrase": PHRASE}).status_code == 200
    assert WRITES[-1][2] == {"dry-run": "0", "remove-vanished": "acl;entry"}
    assert c.post(u(cid, "/corp/sync"), json={"remove_vanished": ["entry"]}).status_code == 200                # simulation : aucune phrase, rien n'est supprimé
    assert WRITES[-1][2] == {"dry-run": "1", "remove-vanished": "entry"}


@pytest.mark.parametrize("body", [{"scope": "tous"}, {"remove_vanished": ["users"]}, {"enable_new": "oui"}, {"dry_run": "non"}, {"remove_vanished": ["acl"] * 4}])
def test_sync_values_are_validated(api, body):
    c, cid = api
    assert c.post(u(cid, "/corp/sync"), json=body).status_code == 422 and not WRITES


def test_only_ldap_and_ad_realms_sync(api):
    c, cid = api
    ST["realms"]["oid"] = {"type": "openid", "issuer-url": "https://x.example.org", "client-id": "c"}
    for r in ("oid", "pam", "pve"):
        assert c.post(u(cid, f"/{r}/sync"), json={}).status_code == 422
    assert c.post(u(cid, "/nope/sync"), json={}).status_code == 404 and not WRITES


# ---------------------------------------------------------------- session, audit, secrets, erreurs
def test_every_write_needs_the_admin_session(api):
    c, cid = api
    assert c.delete(f"/api/connections/{cid}/admin-session").status_code in (200, 204)
    for method, tail, body in (("post", "", LDAP), ("put", "/corp", {"comment": "x", "confirm": True, "type_name": "corp"}), ("delete", "/corp?confirm=true&name=corp", None),
                               ("post", "/corp/sync", {})):
        r = getattr(c, method)(u(cid, tail), **({"json": body} if body is not None else {}))
        assert r.status_code in (401, 403) and r.status_code != 200, (method, tail, r.status_code)
    assert not WRITES


def test_writes_need_a_kaji_session(client):
    for method, tail in (("POST", ""), ("PUT", "/corp"), ("DELETE", "/corp"), ("POST", "/corp/sync")):
        assert client.request(method, u(1, tail), json={}).status_code == 401


def test_every_write_and_refusal_is_audited_without_secret(api):
    c, cid = api
    create(c, cid, password=BIND_PW, bind_dn="cn=x")
    create(c, cid, realm="corp", type_name="corp")                                                        # refus 409
    c.put(u(cid, "/corp"), json={"password": BIND_PW + "2", "confirm": True, "type_name": "corp"})          # refus : phrase (le realm a des comptes)
    c.post(u(cid, "/ldap2/sync"), json={})
    c.delete(u(cid, "/pam?confirm=true&name=pam"))
    log = audit_text(c)
    pairs = {(a["action"], a["status"]) for a in c.get("/api/audit").json()}
    assert {("realm-create", "started"), ("realm-create", "error"), ("realm-update", "error"), ("realm-sync", "started"), ("realm-delete", "error")} <= pairs
    assert no_secret(log) and BIND_PW + "2" not in log


def test_proxmox_error_is_passed_on_without_leaking_its_message(api):
    c, cid = api
    ST["fail"] = True
    r = create(c, cid, password=BIND_PW)
    assert r.status_code in (403, 502) and no_secret(r.text, audit_text(c))
