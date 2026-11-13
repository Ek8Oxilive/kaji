import re
from urllib.parse import parse_qs, quote, unquote

import httpx
import pytest

from app import adminsession as A
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
PERM_SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": PERM_SECRET}
ROOT_PW = "correct-horse-battery-staple"
TFA_PW = "pw-du-compte-tfa"
CODE = "123456"
TICKET = "PVE:root@pam:65A1B2C3::c2lnbmF0dXJlK3NsYXNoLz0="                 # « + », « / », « = » : le cookie doit être encodé
CSRF = "65A1B2C3:Y3NyZitzbGFzaC89"
CHALLENGE = 'PVE:!tfa!{"totp":true,"ticket":"x"}'
SEEN: list[httpx.Request] = []
ST: dict = {}


def _json(data, code=200):
    return httpx.Response(code, json={"data": data})


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    m = request.method
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    if p == "/access/ticket" and m == "POST":
        if "authorization" in request.headers or "cookie" in request.headers:        # allowtoken=0 : la connexion se fait SANS jeton ni cookie
            return _json(None, 401)
        if ST.get("down"):
            raise httpx.ConnectError("injoignable")
        if ST.get("weird"):                                                          # une seule des deux valeurs est illisible à la fois
            return _json({"ticket": "PVE:x" if ST["weird"] == "ticket" else TICKET, "CSRFPreventionToken": "y" if ST["weird"] == "csrf" else CSRF})
        u, pw = body.get("username"), body.get("password")
        if u == "root@pam" and pw == ROOT_PW and set(body) == {"username", "password"}:
            return _json({"ticket": TICKET, "CSRFPreventionToken": CSRF, "username": u})
        if u == "tfa@pam" and pw == TFA_PW and "tfa-challenge" not in body:
            return _json({"ticket": CHALLENGE, "NeedTFA": 1, "username": u})
        if u == "tfa@pam" and body.get("tfa-challenge") == CHALLENGE and pw == f"totp:{CODE}":
            if ST.get("still_tfa"):                                                  # Proxmox renvoie encore un défi : ce n'est pas un vrai ticket
                return _json({"ticket": CHALLENGE, "CSRFPreventionToken": CSRF, "username": u})
            return _json({"ticket": TICKET.replace("root@pam", "tfa@pam"), "CSRFPreventionToken": CSRF, "username": u})
        return httpx.Response(401, json={"data": None, "message": f"authentication failure ({u} {pw})"})
    cookie = unquote(request.headers.get("cookie", ""))
    if not cookie.startswith("PVEAuthCookie=PVE:") or "authorization" in request.headers:
        return httpx.Response(401, json={"data": None, "message": PERM_SECRET})
    if p == "/access/permissions" and m == "GET":
        return _json({"/": {"Permissions.Modify": 1, "User.Modify": 1}})
    if p == "/access/tfa/bob@pve":
        if m == "GET":
            return _json(list(ST.get("tfa", [])))
        if m == "POST":
            if request.headers.get("csrfpreventiontoken") != CSRF:
                return httpx.Response(401, json={"data": None, "message": "invalid CSRF"})
            if ST.get("tfa_forbidden"):
                return httpx.Response(403, json={"data": None, "message": PERM_SECRET})
            ST.setdefault("tfa", []).append({"id": "r1", "type": "recovery", "created": 1700000000, "enable": 1})
            return _json({"id": "r1", "recovery": ["1111-2222-3333", "4444-5555-6666"]})
    if p == "/access/users" and m == "GET":
        return _json([{"userid": u, "enable": 1} for u in ST["users"]])
    if p == "/access/users" and m == "POST":
        if request.headers.get("csrfpreventiontoken") != CSRF:                       # toute écriture exige le CSRF
            return httpx.Response(401, json={"data": None, "message": "invalid CSRF"})
        ST["users"].append(body["userid"])
        return _json(None)
    return httpx.Response(404, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client, monkeypatch):
    SEEN.clear(); ST.clear(); ST["users"] = ["kaji@pve", "root@pam"]
    A.sessions.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    A.sessions.clear()
    app.dependency_overrides.clear()


def u(cid, tail=""):
    return f"/api/connections/{cid}/admin-session{tail}"


def login(c, cid, **over):
    return c.post(u(cid, "/ticket"), json={"username": "root@pam", "password": ROOT_PW, **over})


def audit_text(c):
    return c.get("/api/audit").text


def no_secret(*texts):
    return all(s not in t for t in texts for s in (ROOT_PW, TFA_PW, TICKET, CSRF, PERM_SECRET, CODE + "x"))


# ------------------------------------------------------------------ ouverture
def test_login_opens_a_ticket_session_without_any_token_header(api):
    c, cid = api
    r = login(c, cid)
    assert r.status_code == 201
    j = r.json()
    assert j["active"] is True and j["kind"] == "ticket" and j["user"] == "root@pam" and 1790 <= j["seconds_left"] <= 1800 and j["can_modify_permissions"] is True
    first = SEEN[0]
    assert first.url.path.endswith("/access/ticket") and "authorization" not in first.headers and "cookie" not in first.headers
    assert no_secret(r.text, c.get(u(cid)).text, c.get(u(cid, "/whoami")).text, audit_text(c), str(r.headers))
    assert "(mot de passe)" in audit_text(c) and "root@pam" in audit_text(c)


def test_ticket_calls_send_the_encoded_cookie_and_the_csrf_on_writes(api):
    c, cid = api
    assert login(c, cid).status_code == 201
    r = c.post(f"/api/connections/{cid}/access/users", json={"userid": "bob@pve", "enable": True, "confirm": True, "type_name": "bob@pve"})
    assert r.status_code == 201 and "bob@pve" in ST["users"]
    last_get = next(x for x in SEEN if x.url.path.endswith("/access/permissions") and x.method == "GET")
    assert last_get.headers["cookie"] == f"PVEAuthCookie={quote(TICKET, safe='')}" and "authorization" not in last_get.headers
    write = next(x for x in SEEN if x.method == "POST" and x.url.path.endswith("/access/users"))
    assert write.headers["csrfpreventiontoken"] == CSRF and "authorization" not in write.headers


def test_wrong_password_is_refused_with_a_fixed_message_and_opens_nothing(api):
    c, cid = api
    r = login(c, cid, password="mauvais-mot-de-passe")
    assert r.status_code == 403 and r.json()["detail"] == "Identifiants refusés par Proxmox (compte, mot de passe ou code de double authentification)"
    assert "mauvais-mot-de-passe" not in r.text and "mauvais-mot-de-passe" not in audit_text(c) and "authentication failure" not in r.text
    assert c.get(u(cid)).json() == {"active": False}


def test_unknown_account_is_refused_the_same_way(api):
    c, cid = api
    r = login(c, cid, username="nobody@pam")
    assert r.status_code == 403 and "nobody" not in r.json()["detail"]


def test_account_with_tfa_needs_the_code(api):
    c, cid = api
    r = login(c, cid, username="tfa@pam", password=TFA_PW)
    assert r.status_code == 409 and "double authentification" in r.json()["detail"] and c.get(u(cid)).json() == {"active": False}
    bad = login(c, cid, username="tfa@pam", password=TFA_PW, code="654321")
    assert bad.status_code == 403
    ok = login(c, cid, username="tfa@pam", password=TFA_PW, code=CODE)
    assert ok.status_code == 201 and ok.json()["user"] == "tfa@pam"
    assert no_secret(ok.text, audit_text(c))
    second = [x for x in SEEN if x.url.path.endswith("/access/ticket")][-1]
    assert parse_qs(second.content.decode())["password"] == [f"totp:{CODE}"]


@pytest.mark.parametrize("over", [
    {"username": "root"}, {"username": "root@"}, {"username": "@pam"}, {"username": "a b@pam"}, {"username": "a;b@pam"}, {"username": "root@pam\n"}, {"username": "x" * 80 + "@pam"},
    {"password": ""}, {"password": "a\nb"}, {"password": "a\x00b"}, {"password": "x" * 600}, {"code": "12345"}, {"code": "123456789"}, {"code": "12345a"}, {"code": "１２３４５６"},
])
def test_invalid_input_never_reaches_proxmox_and_is_never_echoed(api, over):
    c, cid = api
    r = login(c, cid, **over)
    assert r.status_code == 422 and not SEEN
    for v in over.values():
        assert not v or len(str(v)) < 4 or str(v) not in r.text


def test_a_second_tfa_challenge_is_not_a_ticket(api):
    c, cid = api
    ST["still_tfa"] = True
    r = login(c, cid, username="tfa@pam", password=TFA_PW, code=CODE)
    assert r.status_code == 502 and c.get(u(cid)).json() == {"active": False}


def test_unreadable_login_answer_opens_nothing(api):
    c, cid = api
    for which in ("ticket", "csrf"):
        ST["weird"] = which
        r = login(c, cid)
        assert r.status_code == 502 and c.get(u(cid)).json() == {"active": False}
        A.sessions._attempts.clear()


def test_proxmox_down_is_a_clean_error(api):
    c, cid = api
    ST["down"] = True
    r = login(c, cid)
    assert r.status_code in (502, 504) and no_secret(r.text, audit_text(c))


def test_attempts_are_limited(api):
    c, cid = api
    codes = [login(c, cid, password="faux").status_code for _ in range(7)]
    assert codes[:5] == [403] * 5 and codes[5:] == [429, 429]


def test_requires_a_kaji_login(client):
    assert client.post("/api/connections/1/admin-session/ticket", json={"username": "root@pam", "password": "x"}).status_code == 401


def _add_recovery(c, cid):
    return c.post(f"/api/connections/{cid}/access/tfa", json={"userid": "bob@pve", "type": "recovery", "confirm": True, "type_name": "bob@pve",
                                                               "acknowledge_cut_access": True, "phrase": "COUPURE POSSIBLE"})


def test_tfa_write_works_with_a_ticket_session(api):
    c, cid = api
    assert login(c, cid).status_code == 201
    r = _add_recovery(c, cid)
    assert r.status_code == 201 and r.json()["id"] == "r1" and len(r.json()["recovery"]) == 2
    write = next(x for x in SEEN if x.method == "POST" and x.url.path.endswith("/access/tfa/bob@pve"))
    assert write.headers["csrfpreventiontoken"] == CSRF and "authorization" not in write.headers and write.headers["cookie"].startswith("PVEAuthCookie=PVE%3A")


def test_a_403_on_a_ticket_session_is_not_reported_as_the_token_rule(api):
    c, cid = api
    assert login(c, cid).status_code == 201
    ST["tfa_forbidden"] = True
    r = _add_recovery(c, cid)
    assert r.status_code >= 400 and "allowtoken" not in r.text and PERM_SECRET not in r.text


def test_session_repr_never_shows_the_ticket(api):
    c, cid = api
    login(c, cid)
    s = next(iter(A.sessions._items.values()))
    assert s.kind == "ticket" and TICKET not in repr(s) and CSRF not in repr(s) and "ticket" in repr(s)


def test_closing_removes_the_ticket(api):
    c, cid = api
    login(c, cid)
    assert c.delete(u(cid)).status_code == 204 and c.get(u(cid)).json() == {"active": False} and not A.sessions._items
