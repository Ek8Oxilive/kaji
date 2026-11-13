"""Notifications en écriture (lot #151, étape 2) : faux Proxmox STRICT (chemins, paramètres par type, tableaux, base64). Comme en réel supposé : secrets jamais relus."""
import base64
import re
from urllib.parse import parse_qs

import httpx
import pytest

import app.routers.notifications_write as nw
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
SMTP_PW = "pw-smtp-SECRET-1"
TOKEN = "gotify-token-SECRET-2"
HDRV = "Bearer SECRET-3"
B = "/cluster/notifications"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}
b64 = lambda s: base64.b64encode(s.encode()).decode()          # noqa: E731
COMMON = {"comment", "disable"}
KEYS = {"sendmail": COMMON | {"author", "from-address", "mailto", "mailto-user"},
        "smtp": COMMON | {"author", "from-address", "mailto", "mailto-user", "mode", "password", "port", "server", "username"},
        "gotify": COMMON | {"server", "token"}, "webhook": COMMON | {"url", "method", "header", "secret", "body"}}
REQ = {"sendmail": set(), "smtp": {"from-address", "server"}, "gotify": {"server", "token"}, "webhook": {"url", "method"}}
ARRAYS = {"mailto", "mailto-user", "header", "secret", "match-field", "match-severity", "match-calendar", "target", "delete"}
SECRET_KEYS = {"password", "token", "header", "secret", "body"}
MKEYS = {"comment", "disable", "invert-match", "mode", "match-field", "match-severity", "match-calendar", "target"}


def _pairs_error(items) -> str | None:
    """En-têtes et secrets d'un webhook : chaîne de propriétés `name=<nom>,value=<base64>` (schéma de Proxmox 9, `apidoc.js`). L'ancien `nom=valeur` donne, chez le vrai Proxmox,
    `error: unknown key "<nom>"` (constaté en réel le 2026-11-13 avec `Content-Type=…`)."""
    for h in items:
        props = [p.partition("=") for p in h.split(",")]
        for k, sep, _ in props:
            if k not in ("name", "value") or not sep:
                return f'error: unknown key "{k}"'
        d = {k: v for k, _, v in props}
        if set(d) != {"name", "value"} or len(props) != 2 or not re.fullmatch(r"[A-Za-z0-9\-]{1,64}", d["name"]):
            return "en-tête mal formé"
        try:
            if not d["value"] or base64.b64decode(d["value"], validate=True) is None:
                return "valeur mal encodée"
        except ValueError:
            return "valeur mal encodée"
    return None


def fresh():
    ST.clear()
    ST.update(noapply=False, fail=False, leaky=False, pve_digest=None,
              endpoints={"sendmail": {"mail-to-root": {"origin": "builtin", "mailto-user": ["root@pam"]}},
                         "smtp": {"smtp1": {"origin": "user-created", "server": "smtp.example.org", "port": 587, "mode": "starttls", "from-address": "pve@example.org", "mailto": ["a@example.org"], "password": SMTP_PW}},
                         "gotify": {"gotify1": {"origin": "user-created", "server": "https://gotify.example.org", "token": TOKEN}},
                         "webhook": {"hook1": {"origin": "user-created", "url": "https://hooks.example.org/x", "method": "post", "header": [f"name=X-Auth,value={b64(HDRV)}"], "secret": [f"name=key,value={b64('v')}"], "body": b64("corps"), "disable": 1}}},
              matchers={"default-matcher": {"origin": "builtin", "target": ["mail-to-root"], "mode": "all"}, "m1": {"origin": "user-created", "target": ["smtp1"], "match-severity": ["error"], "mode": "any"}})


def bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def parse(request):
    q = parse_qs(request.content.decode(), keep_blank_values=True)
    return {k: (v if k in ARRAYS else v[0]) for k, v in q.items()}


def _rows():
    return [{"name": n, "type": t, "origin": e.get("origin"), "disable": e.get("disable", 0), "comment": e.get("comment")} for t, d in ST["endpoints"].items() for n, e in d.items()]


def _public(e):
    return {k: v for k, v in e.items() if ST["leaky"] or k not in ("password", "token")}


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    m = request.method
    parts = p.removeprefix(B + "/").split("/") if p.startswith(B + "/") else []
    if m == "GET":
        if p == f"{B}/targets":
            return httpx.Response(200, json={"data": _rows()})
        if p == f"{B}/matchers":
            return httpx.Response(200, json={"data": [{"name": n, **v} for n, v in ST["matchers"].items()]})
        if len(parts) == 2 and parts[0] == "endpoints":
            return httpx.Response(200, json={"data": [{"name": n, **_public(e)} for n, e in ST["endpoints"][parts[1]].items()]})
        if len(parts) == 3 and parts[0] == "endpoints" and parts[2] in ST["endpoints"].get(parts[1], {}):
            return httpx.Response(200, json={"data": {**_public(ST["endpoints"][parts[1]][parts[2]]), **({"digest": ST["pve_digest"]} if ST["pve_digest"] else {})}})
        if len(parts) == 2 and parts[0] == "matchers" and parts[1] in ST["matchers"]:
            return httpx.Response(200, json={"data": {**ST["matchers"][parts[1]], **({"digest": ST["pve_digest"]} if ST["pve_digest"] else {})}})
        return httpx.Response(500, json={"data": None, "message": "introuvable"})
    if ST["fail"]:
        return httpx.Response(403, json={"data": None, "message": SECRET})
    body = parse(request)
    CALLS.append((m, p, {**body, **({"__query": dict(request.url.params)} if request.url.params else {})}))
    # endpoints
    if m == "POST" and len(parts) == 2 and parts[0] == "endpoints":
        typ = parts[1]
        if "name" not in body or set(body) - KEYS[typ] - {"name"} or not REQ[typ] <= set(body):
            return bad(f"paramètres refusés/manquants {sorted(set(body) - KEYS[typ] - {'name'})}")
        if body["name"] in {r["name"] for r in _rows()}:
            return bad("existe déjà")
        if "disable" in body and body["disable"] not in ("0", "1"):
            return bad("disable 0/1")
        err = _pairs_error(body.get("header", []) + body.get("secret", []))
        if err:
            return bad(err)
        if "body" in body:
            base64.b64decode(body["body"], validate=True)
        if not ST["noapply"]:
            ST["endpoints"][typ][body["name"]] = {"origin": "user-created", **{k: (int(v) if k in ("port", "disable") else v) for k, v in body.items() if k != "name"}}
        return httpx.Response(200, json={"data": None})
    if len(parts) == 3 and parts[0] == "endpoints" and m in ("PUT", "DELETE"):
        typ, name = parts[1], parts[2]
        e = ST["endpoints"].get(typ, {}).get(name)
        if e is None:
            return httpx.Response(500, json={"data": None, "message": "introuvable"})
        if m == "DELETE":
            if e.get("origin") == "builtin":
                return bad("intégrée")
            if body or request.url.params:
                return bad("aucun paramètre attendu")
            if not ST["noapply"]:
                del ST["endpoints"][typ][name]
            return httpx.Response(200, json={"data": None})
        if set(body) - KEYS[typ] - {"delete", "digest"}:
            return bad(f"paramètres refusés {sorted(set(body) - KEYS[typ] - {'delete', 'digest'})}")
        if ST["pve_digest"] and body.get("digest") != ST["pve_digest"]:
            return bad("digest différent")
        if set(body.get("delete", [])) - KEYS[typ]:
            return bad("delete invalide")
        err = _pairs_error(body.get("header", []) + body.get("secret", []))
        if err:
            return bad(err)
        if not ST["noapply"]:
            for k, v in body.items():
                if k not in ("delete", "digest"):
                    e[k] = int(v) if k in ("port", "disable") else v
            for k in body.get("delete", []):
                e.pop(k, None)
        return httpx.Response(200, json={"data": None})
    if m == "POST" and len(parts) == 3 and parts[0] == "targets" and parts[2] == "test":
        if parts[1] not in {r["name"] for r in _rows()} or body:
            return bad("cible inconnue")
        return httpx.Response(200, json={"data": None})
    # matchers
    if m == "POST" and parts == ["matchers"]:
        if "name" not in body or set(body) - MKEYS - {"name"}:
            return bad(f"paramètres refusés {sorted(set(body) - MKEYS - {'name'})}")
        if body["name"] in ST["matchers"]:
            return bad("existe déjà")
        if not ST["noapply"]:
            ST["matchers"][body["name"]] = {"origin": "user-created", **{k: (int(v) if k in ("disable", "invert-match") else v) for k, v in body.items() if k != "name"}}
        return httpx.Response(200, json={"data": None})
    if len(parts) == 2 and parts[0] == "matchers" and m in ("PUT", "DELETE"):
        name = parts[1]
        if name not in ST["matchers"]:
            return httpx.Response(500, json={"data": None, "message": "introuvable"})
        if m == "DELETE":
            if ST["matchers"][name].get("origin") == "builtin":
                return bad("intégrée")
            if not ST["noapply"]:
                del ST["matchers"][name]
            return httpx.Response(200, json={"data": None})
        if set(body) - MKEYS - {"delete", "digest"} or (ST["pve_digest"] and body.get("digest") != ST["pve_digest"]):
            return bad("paramètres refusés")
        if not ST["noapply"]:
            for k, v in body.items():
                if k not in ("delete", "digest"):
                    ST["matchers"][name][k] = int(v) if k in ("disable", "invert-match") else v
            for k in body.get("delete", []):
                ST["matchers"][name].pop(k, None)
        return httpx.Response(200, json={"data": None})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client, monkeypatch):
    CALLS.clear(); fresh(); nw._LAST_TEST.clear()
    clock = {"t": 1000.0}
    monkeypatch.setattr(nw, "_clock", lambda: clock["t"])
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    client.clock = clock
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, path=""):
    return f"/api/connections/{cid}/notifications{path}"


def audit_text(c):
    return c.get("/api/audit").text


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


def no_secret(*texts):
    return all(s not in t for t in texts for s in (SMTP_PW, TOKEN, HDRV, SECRET, b64(HDRV)))


# ---------------------------------------------------------------- cibles : création
def test_create_each_type_with_exact_params_and_no_secret_back(api):
    c, cid = api
    r = c.post(url(cid, "/targets/smtp"), json={"name": "smtp2", "server": "mail.example.org", "port": 465, "mode": "tls", "from_address": "pve@example.org", "mailto": ["a@example.org", "b@example.org"],
                                                "mailto_user": ["root@pam"], "username": "kaji", "password": SMTP_PW, "author": "Proxmox Lab", "comment": "labo", "confirm": True})
    assert r.status_code == 201 and no_secret(r.text) and r.json()["server"] == "mail.example.org" and "password" not in r.json()
    assert CALLS[-1] == ("POST", f"{B}/endpoints/smtp", {"name": "smtp2", "server": "mail.example.org", "port": "465", "mode": "tls", "from-address": "pve@example.org", "mailto": ["a@example.org", "b@example.org"],
                                                         "mailto-user": ["root@pam"], "username": "kaji", "password": SMTP_PW, "author": "Proxmox Lab", "comment": "labo"})
    assert c.post(url(cid, "/targets/gotify"), json={"name": "g2", "server": "https://gotify.example.org", "token": TOKEN, "confirm": True}).status_code == 201
    assert CALLS[-1][2] == {"name": "g2", "server": "https://gotify.example.org", "token": TOKEN}
    r = c.post(url(cid, "/targets/webhook"), json={"name": "h2", "url": "https://hooks.example.org/y", "method": "put", "headers": [{"name": "X-Auth", "value": HDRV}], "secrets": [{"name": "key", "value": "v1"}],
                                                   "body": "{{ title }}", "disable": True, "confirm": True})
    assert r.status_code == 201 and no_secret(r.text) and r.json()["header_names"] == ["X-Auth"] and r.json()["secret_names"] == ["key"] and r.json()["body_set"] is True and r.json()["method"] == "put"
    assert CALLS[-1][2] == {"name": "h2", "url": "https://hooks.example.org/y", "method": "put", "header": [f"name=X-Auth,value={b64(HDRV)}"], "secret": [f"name=key,value={b64('v1')}"], "body": b64("{{ title }}"), "disable": "1"}
    assert c.post(url(cid, "/targets/sendmail"), json={"name": "s2", "mailto": ["a@example.org"], "from_address": "pve@example.org", "confirm": True}).status_code == 201
    assert CALLS[-1][2] == {"name": "s2", "mailto": ["a@example.org"], "from-address": "pve@example.org"}
    assert no_secret(audit_text(c)) and "password=défini" in audit_text(c) and "token=défini" in audit_text(c)


def test_confirm_dry_run_and_duplicates(api):
    c, cid = api
    base = {"name": "g2", "server": "https://gotify.example.org", "token": TOKEN}
    assert c.post(url(cid, "/targets/gotify"), json=base).status_code == 400 and not CALLS
    assert c.post(url(cid, "/targets/gotify"), json={**base, "confirm": "true"}).status_code == 422
    d = c.post(url(cid, "/targets/gotify"), json={**base, "dry_run": True})
    assert d.status_code == 201 and d.json()["dry_run"] is True and d.json()["params"]["token"] == "défini" and TOKEN not in d.text and not CALLS
    for name, typ in (("smtp1", "gotify"), ("mail-to-root", "smtp"), ("hook1", "webhook")):                       # le nom est unique tous types confondus
        assert c.post(url(cid, f"/targets/{typ}"), json={**base, "name": name, "from_address": "a@b.co", "url": "https://x.example.org", "method": "post", "confirm": True}).status_code in (409, 422)
    assert c.post(url(cid, "/targets/gotify"), json={**base, "name": "smtp1", "confirm": True}).status_code == 409 and not CALLS


def test_fields_of_another_type_and_missing_required_are_refused(api):
    c, cid = api
    ok = {"name": "x1", "confirm": True}
    cases = [("gotify", {"server": "https://g.example.org", "token": TOKEN, "password": SMTP_PW}), ("gotify", {"server": "https://g.example.org", "token": TOKEN, "mailto": ["a@b.co"]}),
             ("smtp", {"server": "mail.example.org", "from_address": "a@b.co", "token": TOKEN}), ("webhook", {"url": "https://h.example.org", "method": "post", "server": "x.example.org"}),
             ("sendmail", {"url": "https://h.example.org"}), ("gotify", {"server": "https://g.example.org"}), ("gotify", {"token": TOKEN}), ("smtp", {"server": "mail.example.org"}),
             ("smtp", {"from_address": "a@b.co"}), ("webhook", {"url": "https://h.example.org"}), ("webhook", {"method": "post"})]
    for typ, extra in cases:
        assert c.post(url(cid, f"/targets/{typ}"), json={**ok, **extra}).status_code == 422, (typ, extra)
    assert not CALLS


@pytest.mark.parametrize("typ,extra", [
    ("smtp", {"server": "127.0.0.1"}), ("smtp", {"server": "localhost"}), ("smtp", {"server": "::1"}), ("smtp", {"server": "a b"}), ("smtp", {"server": "host;ls"}), ("smtp", {"port": 0}), ("smtp", {"port": 65536}),
    ("smtp", {"port": "587"}), ("smtp", {"mode": "ssl"}), ("smtp", {"from_address": "pas un mail"}), ("smtp", {"mailto": ["bad"]}), ("smtp", {"mailto": ["a@b.co", "a@b.co"]}), ("smtp", {"mailto_user": ["root"]}),
    ("smtp", {"username": ""}), ("smtp", {"username": "a\nb"}), ("smtp", {"password": ""}), ("smtp", {"password": "a\nb"}), ("smtp", {"author": "a<b>"}), ("smtp", {"comment": "règle"}), ("smtp", {"comment": "a\nb"}),
    ("smtp", {"disable": "1"}), ("smtp", {"mailto": [f"u{i}@b.co" for i in range(21)]}),
    ("gotify", {"server": "http://127.0.0.1:8080"}), ("gotify", {"server": "https://user:pw@g.example.org"}), ("gotify", {"server": "ftp://g.example.org"}), ("gotify", {"server": "https://localhost"}),
    ("gotify", {"server": "https://g.example.org x"}), ("gotify", {"token": "a b"}), ("gotify", {"token": ""}), ("gotify", {"token": "x" * 513}),
    ("webhook", {"url": "http://169.254.1.1/x"}), ("webhook", {"url": "https://u:p@h.example.org"}), ("webhook", {"url": "javascript:alert(1)"}), ("webhook", {"method": "delete"}), ("webhook", {"method": "POST"}),
    ("webhook", {"headers": [{"name": "Bad Name", "value": "x"}]}), ("webhook", {"headers": [{"name": "X-A", "value": ""}]}), ("webhook", {"headers": [{"name": "X-A", "value": "x"}, {"name": "x-a", "value": "y"}]}),
    ("webhook", {"headers": [{"name": "X-A", "value": "a\nb"}]}), ("webhook", {"secrets": [{"name": "../x", "value": "v"}]}), ("webhook", {"body": "a\x00b"}), ("webhook", {"body": "x" * 4097}),
])
def test_invalid_values_are_refused_without_any_call(api, typ, extra):
    c, cid = api
    base = {"smtp": {"server": "mail.example.org", "from_address": "a@b.co"}, "gotify": {"server": "https://g.example.org", "token": TOKEN}, "webhook": {"url": "https://h.example.org", "method": "post"}}[typ]
    assert c.post(url(cid, f"/targets/{typ}"), json={"name": "x1", "confirm": True, **base, **extra}).status_code == 422 and not CALLS


@pytest.mark.parametrize("name", ["1abc", "a", "a b", "a/b", "../x", "x" * 65, ""])
def test_invalid_names_are_refused(api, name):
    c, cid = api
    assert c.post(url(cid, "/targets/gotify"), json={"name": name, "server": "https://g.example.org", "token": TOKEN, "confirm": True}).status_code == 422 and not CALLS


def test_unknown_type_in_path_and_unknown_fields_never_forwarded(api):
    c, cid = api
    assert c.post(url(cid, "/targets/group"), json={"name": "x1", "confirm": True}).status_code == 422
    assert c.post(url(cid, "/targets/gotify"), json={"name": "g3", "server": "https://g.example.org", "token": TOKEN, "origin": "builtin", "evil": SECRET, "confirm": True}).status_code == 201
    assert set(CALLS[-1][2]) == {"name", "server", "token"}


# ---------------------------------------------------------------- cibles : modification
def test_update_exact_params_clear_and_digest(api):
    c, cid = api
    d = c.get(url(cid, "/targets/smtp/smtp1")).json()
    assert no_secret(str(d)) and "password" not in d and len(d["digest"]) == 40
    r = c.put(url(cid, "/targets/smtp/smtp1"), json={"port": 465, "mailto": ["z@example.org"], "password": SMTP_PW + "2", "clear": ["mode"], "digest": d["digest"], "confirm": True})
    assert r.status_code == 200 and no_secret(r.text) and r.json()["port"] == 465
    assert CALLS[-1] == ("PUT", f"{B}/endpoints/smtp/smtp1", {"port": "465", "mailto": ["z@example.org"], "password": SMTP_PW + "2", "delete": ["mode"]})
    assert "mode" not in ST["endpoints"]["smtp"]["smtp1"]
    assert c.put(url(cid, "/targets/webhook/hook1"), json={"disable": False, "headers": [{"name": "X-New", "value": "v"}], "clear": ["body"], "confirm": True}).status_code == 200
    assert CALLS[-1][2] == {"disable": "0", "header": [f"name=X-New,value={b64('v')}"], "delete": ["body"]}


def test_clear_sends_proxmox_names_with_dashes(api):
    c, cid = api
    ST["endpoints"]["sendmail"]["mail-to-root"]["from-address"] = "pve@example.org"
    assert c.put(url(cid, "/targets/sendmail/mail-to-root"), json={"clear": ["from_address", "mailto_user"], "mailto": ["a@example.org"], "confirm": True}).status_code == 200
    assert CALLS[-1][2]["delete"] == ["from-address", "mailto-user"]
    assert "from-address" not in ST["endpoints"]["sendmail"]["mail-to-root"] and "mailto-user" not in ST["endpoints"]["sendmail"]["mail-to-root"]


def test_update_refusals_and_pve_digest(api):
    c, cid = api
    assert c.put(url(cid, "/targets/smtp/nope"), json={"port": 25, "confirm": True}).status_code == 404
    assert c.put(url(cid, "/targets/gotify/smtp1"), json={"comment": "x", "confirm": True}).status_code == 404                 # smtp1 n'est pas une cible gotify
    for b in ({}, {"clear": []}, {"port": 25, "clear": ["port"]}, {"clear": ["server"]}, {"clear": ["from_address"]}, {"clear": ["token"]}, {"clear": ["../x"]}, {"token": TOKEN}, {"comment": "règle"}):
        assert c.put(url(cid, "/targets/smtp/smtp1"), json={"confirm": True, **b}).status_code == 422, b
    assert c.put(url(cid, "/targets/smtp/smtp1"), json={"port": 25}).status_code == 400
    d = c.put(url(cid, "/targets/smtp/smtp1"), json={"port": 25, "dry_run": True})
    assert d.status_code == 200 and d.json() == {"dry_run": True, "params": {"port": 25}, "remove": []}
    assert not CALLS
    ST["pve_digest"] = "d" * 40
    assert c.put(url(cid, "/targets/smtp/smtp1"), json={"port": 25, "confirm": True}).status_code == 200 and CALLS[-1][2]["digest"] == "d" * 40


def test_stale_kaji_digest_is_409(api):
    c, cid = api
    d = c.get(url(cid, "/targets/gotify/gotify1")).json()["digest"]
    ST["endpoints"]["gotify"]["gotify1"]["server"] = "https://change-ailleurs.example.org"
    r = c.put(url(cid, "/targets/gotify/gotify1"), json={"comment": "x", "digest": d, "confirm": True})
    assert r.status_code == 409 and "digest périmé" in r.json()["detail"] and not CALLS


# ---------------------------------------------------------------- cibles : suppression
def test_delete_target_needs_confirm_retype_and_is_blocked_when_used_or_builtin(api):
    c, cid = api
    assert c.delete(url(cid, "/targets/sendmail/mail-to-root"), params={"confirm": True, "type_name": "mail-to-root"}).status_code == 422             # intégrée
    r = c.delete(url(cid, "/targets/smtp/smtp1"), params={"confirm": True, "type_name": "smtp1"})
    assert r.status_code == 409 and "m1" in r.json()["detail"]                                                                                       # utilisée par m1
    assert c.delete(url(cid, "/targets/gotify/gotify1")).status_code == 400
    assert c.delete(url(cid, "/targets/gotify/gotify1"), params={"confirm": True}).status_code == 400
    assert c.delete(url(cid, "/targets/gotify/gotify1"), params={"confirm": True, "type_name": "gotify2"}).status_code == 400
    assert c.delete(url(cid, "/targets/gotify/gotify1"), params={"type_name": "gotify1"}).status_code == 400
    assert c.delete(url(cid, "/targets/smtp/gotify1"), params={"confirm": True, "type_name": "gotify1"}).status_code == 404
    assert not CALLS and "gotify1" in ST["endpoints"]["gotify"]
    assert c.delete(url(cid, "/targets/gotify/gotify1"), params={"dry_run": True}).json() == {"dry_run": True, "remove": ["gotify1"], "retype": "gotify1"}
    r = c.delete(url(cid, "/targets/gotify/gotify1"), params={"confirm": True, "type_name": "gotify1"})
    assert r.status_code == 200 and CALLS == [("DELETE", f"{B}/endpoints/gotify/gotify1", {})] and "gotify1" not in ST["endpoints"]["gotify"]


# ---------------------------------------------------------------- test d'envoi
def test_test_send_needs_confirm_retype_and_is_rate_limited_per_target(api):
    c, cid = api
    t = url(cid, "/targets/gotify1/test")
    assert c.post(t, json={}).status_code == 400 and c.post(t, json={"confirm": True}).status_code == 400 and c.post(t, json={"confirm": True, "type_name": "autre"}).status_code == 400
    assert c.post(t, json={"confirm": "true", "type_name": "gotify1"}).status_code == 422
    r = c.post(t, json={"type_name": "gotify1"})                                                                                                     # le bon nom, mais sans confirm
    assert r.status_code == 400 and "VRAI message" in r.json()["detail"] and not CALLS
    d = c.post(t, json={"dry_run": True})
    assert d.status_code == 200 and d.json() == {"dry_run": True, "target": "gotify1", "type": "gotify", "sends_a_real_message": True} and not CALLS
    r = c.post(t, json={"confirm": True, "type_name": "gotify1"})
    assert r.status_code == 200 and r.json() == {"sent": True, "target": "gotify1"} and CALLS == [("POST", f"{B}/targets/gotify1/test", {})]
    assert (cid, "gotify1") in nw._LAST_TEST                                                                                                          # la limite est par connexion ET par cible
    again = c.post(t, json={"confirm": True, "type_name": "gotify1"})
    assert again.status_code == 429 and "moins d'une minute" in again.json()["detail"] and len(CALLS) == 1
    assert c.post(url(cid, "/targets/smtp1/test"), json={"confirm": True, "type_name": "smtp1"}).status_code == 200                              # une autre cible n'est pas bloquée
    c.clock["t"] += 59
    assert c.post(t, json={"confirm": True, "type_name": "gotify1"}).status_code == 429
    c.clock["t"] += 2
    assert c.post(t, json={"confirm": True, "type_name": "gotify1"}).status_code == 200 and len(CALLS) == 3


def test_test_send_refusals_and_failure_still_counts(api):
    c, cid = api
    assert c.post(url(cid, "/targets/nope/test"), json={"confirm": True, "type_name": "nope"}).status_code == 404
    assert c.post(url(cid, "/targets/hook1/test"), json={"confirm": True, "type_name": "hook1"}).status_code == 409 and not CALLS               # désactivée
    ST["fail"] = True
    t = url(cid, "/targets/gotify1/test")
    assert c.post(t, json={"confirm": True, "type_name": "gotify1"}).status_code == 502
    ST["fail"] = False
    assert c.post(t, json={"confirm": True, "type_name": "gotify1"}).status_code == 429                                                          # un échec ne permet pas de réessayer en boucle
    assert SECRET not in audit_text(c)


# ---------------------------------------------------------------- règles
def test_create_matcher_exact_params_and_checks(api):
    c, cid = api
    r = c.post(url(cid, "/matchers"), json={"name": "alertes", "target": ["gotify1", "smtp1"], "match_severity": ["warning", "error"], "match_field": ["exact:type=vzdump", "regex:hostname=^pve.*"],
                                            "match_calendar": ["mon..fri 08-18"], "mode": "any", "invert_match": True, "disable": False, "comment": "alertes", "confirm": True})
    assert r.status_code == 201 and r.json()["targets"] == ["gotify1", "smtp1"]
    assert CALLS[-1] == ("POST", f"{B}/matchers", {"name": "alertes", "target": ["gotify1", "smtp1"], "match-severity": ["warning", "error"], "match-field": ["exact:type=vzdump", "regex:hostname=^pve.*"],
                                                     "match-calendar": ["mon..fri 08-18"], "mode": "any", "invert-match": "1", "disable": "0", "comment": "alertes"})
    n = len(CALLS)
    assert c.post(url(cid, "/matchers"), json={"name": "alertes", "target": ["gotify1"], "confirm": True}).status_code == 409
    assert c.post(url(cid, "/matchers"), json={"name": "m9", "target": ["absente"], "confirm": True}).status_code == 422
    assert c.post(url(cid, "/matchers"), json={"name": "m9", "confirm": True}).status_code == 422                                              # sans cible : n'enverrait rien
    assert c.post(url(cid, "/matchers"), json={"name": "m9", "target": ["gotify1"]}).status_code == 400
    assert c.post(url(cid, "/matchers"), json={"name": "m9", "target": ["gotify1"], "dry_run": True}).status_code == 201
    assert len(CALLS) == n


@pytest.mark.parametrize("b", [
    {"mode": "some"}, {"match_severity": ["fatal"]}, {"match_severity": ["error", "error"]}, {"match_field": ["type=vzdump"]}, {"match_field": ["exact:../x=1"]}, {"match_field": ["exact:type=a\nb"]},
    {"match_field": ["exact:type=x", "exact:type=x"]}, {"match_calendar": [""]}, {"match_calendar": ["a;b"]}, {"target": ["../x"]}, {"target": ["gotify1", "gotify1"]}, {"disable": "1"}, {"invert_match": 1},
    {"comment": "règle"}, {"target": [f"t{i}1" for i in range(21)]},
])
def test_invalid_matcher_values_are_refused(api, b):
    c, cid = api
    assert c.post(url(cid, "/matchers"), json={"name": "m9", "target": ["gotify1"], "confirm": True, **b}).status_code == 422 and not CALLS


def test_update_and_delete_matcher(api):
    c, cid = api
    d = c.get(url(cid, "/matchers/m1")).json()
    r = c.put(url(cid, "/matchers/m1"), json={"match_severity": ["warning"], "clear": ["mode"], "target": ["smtp1", "gotify1"], "digest": d["digest"], "confirm": True})
    assert r.status_code == 200 and CALLS[-1] == ("PUT", f"{B}/matchers/m1", {"match-severity": ["warning"], "target": ["smtp1", "gotify1"], "delete": ["mode"]})
    for b in ({}, {"clear": ["target"]}, {"clear": ["name"]}, {"mode": "any", "clear": ["mode"]}, {"target": ["absente"]}):
        assert c.put(url(cid, "/matchers/m1"), json={"confirm": True, **b}).status_code in (422,), b
    assert c.put(url(cid, "/matchers/nope"), json={"mode": "all", "confirm": True}).status_code == 404
    assert c.put(url(cid, "/matchers/m1"), json={"mode": "all"}).status_code == 400
    assert c.put(url(cid, "/matchers/default-matcher"), json={"disable": True, "confirm": True}).status_code == 200                              # désactiver l'intégrée est permis
    ST["matchers"]["m1"]["comment"] = "change"
    assert c.put(url(cid, "/matchers/m1"), json={"mode": "all", "digest": d["digest"], "confirm": True}).status_code == 409                         # digest périmé
    n = len(CALLS)
    assert c.delete(url(cid, "/matchers/default-matcher"), params={"confirm": True, "type_name": "default-matcher"}).status_code == 422
    assert c.delete(url(cid, "/matchers/m1")).status_code == 400 and c.delete(url(cid, "/matchers/m1"), params={"confirm": True, "type_name": "x"}).status_code == 400 and len(CALLS) == n
    assert c.delete(url(cid, "/matchers/m1"), params={"dry_run": True}).json() == {"dry_run": True, "remove": ["m1"], "retype": "m1"}
    assert c.delete(url(cid, "/matchers/m1"), params={"confirm": True, "type_name": "m1"}).status_code == 200 and "m1" not in ST["matchers"]
    assert c.delete(url(cid, "/matchers/m1"), params={"confirm": True, "type_name": "m1"}).status_code == 404


# ---------------------------------------------------------------- relecture, audit, secrets
@pytest.mark.parametrize("call", [
    lambda c, cid: c.post(url(cid, "/targets/gotify"), json={"name": "g9", "server": "https://g.example.org", "token": TOKEN, "confirm": True}),
    lambda c, cid: c.put(url(cid, "/targets/smtp/smtp1"), json={"port": 25, "confirm": True}),
    lambda c, cid: c.delete(url(cid, "/targets/gotify/gotify1"), params={"confirm": True, "type_name": "gotify1"}),
    lambda c, cid: c.post(url(cid, "/matchers"), json={"name": "m9", "target": ["gotify1"], "confirm": True}),
    lambda c, cid: c.put(url(cid, "/matchers/m1"), json={"mode": "all", "confirm": True}),
    lambda c, cid: c.delete(url(cid, "/matchers/m1"), params={"confirm": True, "type_name": "m1"}),
], ids=["target-create", "target-update", "target-delete", "matcher-create", "matcher-update", "matcher-delete"])
def test_unapplied_change_is_a_502(api, call):
    c, cid = api
    ST["noapply"] = True
    r = call(c, cid)
    assert r.status_code == 502 and "n'a pas" in r.json()["detail"] and audit_pairs(c)[-1][1] == "error"


def test_every_write_and_refusal_is_audited_without_secret(api):
    c, cid = api
    c.post(url(cid, "/targets/gotify"), json={"name": "g9", "server": "https://g.example.org", "token": TOKEN})                                    # refus : pas de confirm
    c.post(url(cid, "/targets/gotify"), json={"name": "g9", "server": "https://g.example.org", "token": TOKEN, "confirm": True})                 # succès
    c.post(url(cid, "/targets/g9/test"), json={"confirm": True, "type_name": "g9"})                                                              # test envoyé
    pairs = audit_pairs(c)
    assert ("notif-target-create", "error") in pairs and ("notif-target-create", "started") in pairs and ("notif-test", "started") in pairs
    assert no_secret(audit_text(c))


def test_proxmox_error_never_leaks_its_message_or_secrets(api):
    c, cid = api
    ST["fail"] = True
    r = c.post(url(cid, "/targets/smtp"), json={"name": "s9", "server": "mail.example.org", "from_address": "a@b.co", "password": SMTP_PW, "confirm": True})
    assert r.status_code == 502 and no_secret(r.text, audit_text(c))


def test_requires_authentication(client):
    for m, p in (("post", "/targets/smtp"), ("put", "/targets/smtp/x1"), ("delete", "/targets/smtp/x1"), ("post", "/targets/x1/test"), ("post", "/matchers"), ("put", "/matchers/x1"),
                 ("delete", "/matchers/x1"), ("get", "/targets/smtp/x1"), ("get", "/matchers/x1")):
        assert getattr(client, m)(url(1, p)).status_code == 401


# ---------------------------------------------------------------- format réel des en-têtes et secrets (constaté en réel le 2026-11-13)
def test_the_strict_fake_refuses_the_old_header_format_like_the_real_proxmox():
    assert _pairs_error([f"Content-Type={b64('application/json')}"]) == 'error: unknown key "Content-Type"'      # ce que le vrai Proxmox a répondu (500)
    assert _pairs_error([f"name=Content-Type,value={b64('application/json')}"]) is None
    assert _pairs_error(["name=X-A"]) and _pairs_error(["name=X-A,value=x,extra=1"]) and _pairs_error(["name=Bad Name,value=eA=="]) and _pairs_error(["name=X-A,value=!!"])
    assert _pairs_error(["value=eA==,name=X-A"]) is None


def test_webhook_header_is_sent_as_a_property_string_the_real_failing_case(api):
    c, cid = api
    r = c.post(url(cid, "/targets/webhook"), json={"name": "h3", "url": "https://hooks.example.org/z", "method": "post", "disable": True,
                                                    "headers": [{"name": "Content-Type", "value": "application/json"}], "confirm": True})
    assert r.status_code == 201, r.text
    assert CALLS[-1][2]["header"] == [f"name=Content-Type,value={b64('application/json')}"]
    assert r.json()["header_names"] == ["Content-Type"] and "application/json" not in r.text and b64("application/json") not in r.text


def test_header_and_secret_named_like_a_property_key_are_still_sent_correctly(api):
    c, cid = api
    r = c.post(url(cid, "/targets/webhook"), json={"name": "h4", "url": "https://hooks.example.org/z", "method": "post",
                                                    "headers": [{"name": "name", "value": "v1"}, {"name": "value", "value": "v2"}], "secrets": [{"name": "name", "value": "s1"}], "confirm": True})
    assert r.status_code == 201, r.text
    assert CALLS[-1][2]["header"] == [f"name=name,value={b64('v1')}", f"name=value,value={b64('v2')}"] and CALLS[-1][2]["secret"] == [f"name=name,value={b64('s1')}"]
    assert r.json()["header_names"] == ["name", "value"] and r.json()["secret_names"] == ["name"]
