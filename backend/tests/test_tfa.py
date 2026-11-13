"""Double authentification (lot #384) : faux Proxmox STRICT (`/access/tfa`, clés autorisées, URI TOTP et code validés, jamais de mot de passe, secrets non relus).

RIEN de ce fichier n'a tourné sur un vrai cluster : activer la double authentification sur un compte peut le verrouiller.
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app import adminsession as A
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.tfaspec import check_totp_uri, new_totp, shape_tfa

PWD = "un-mot-de-passe-solide"
PERM_SECRET = "s3cr3t-value-xyz"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
URI = f"otpauth://totp/Kaji%3Aeve%40pve?secret={TOTP_SECRET}&issuer=Kaji&algorithm=SHA1&digits=6&period=30"
CODE = "123456"
RECOVERY = ["1111-2222-3333", "4444-5555-6666"]
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": PERM_SECRET}
UUID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
ADMIN = {"user": "admin@pve", "token_id": "kaji-admin", "secret": UUID}
AUTHS = {f"PVEAPIToken=admin@pve!kaji-admin={UUID}", f"PVEAPIToken=kaji@pve!kaji={PERM_SECRET}"}
SEEN: list[httpx.Request] = []
WRITES: list[tuple[str, str, dict]] = []
ST: dict = {}
CLOCK = {"t": 1000.0}
PHRASE = "COUPURE POSSIBLE"
URI_RX = re.compile(r"otpauth://totp/[^?\s/]+\?secret=[A-Z2-7]{16,128}(&(issuer|algorithm|digits|period)=[^&\s]*)*")


def fresh():
    ST.clear()
    ST["tfa"] = {"bob@pve": [{"id": "t1", "type": "totp", "description": "téléphone", "created": 1700000000, "enable": 1}, {"id": "r1", "type": "recovery", "created": 1700000100, "enable": 1}],
                 "eve@pve": [], "carl@ldap": [{"id": "w1", "type": "webauthn", "description": "clé", "created": 1700000200, "enable": 0}],
                 "root@pam": [{"id": "x1", "type": "totp", "created": 1, "enable": 1}], "kaji@pve": [], "admin@pve": []}
    ST.update(noapply=False, fail=False, next=1, locked={"carl@ldap"})


def _bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    m = request.method
    if request.headers.get("authorization") not in AUTHS:
        return httpx.Response(401, json={"data": None, "message": PERM_SECRET})
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    ok = lambda d=None: httpx.Response(200, json={"data": d})
    if m == "GET" and p == "/access/permissions":
        return ok({"/pool/kaji-test": {"Permissions.Modify": 1}})
    if m == "GET" and p == "/access/tfa":
        return ok([{"userid": u, "entries": list(e), **({"totp-locked": True} if u in ST["locked"] else {})} for u, e in ST["tfa"].items() if e])
    um = re.fullmatch(r"/access/users/([^/]+)/unlock-tfa", p)
    if um:                                                       # allowtoken=1 chez Proxmox : la route accepte un jeton, contrairement à /access/tfa
        if m != "PUT":
            return httpx.Response(501, json={"data": None, "message": "méthode inconnue"})
        if ST["fail"]:
            return httpx.Response(403, json={"data": None, "message": PERM_SECRET})
        WRITES.append((m, p, body))
        if not ST.get("unlock_noop"):
            ST["locked"].discard(um.group(1))
        return ok()
    mm = re.fullmatch(r"/access/tfa/([^/]+)(?:/([^/]+))?", p)
    if not mm:
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    uid, eid = mm.group(1), mm.group(2)
    if uid not in ST["tfa"]:
        return httpx.Response(500, json={"data": None, "message": "utilisateur inconnu"})
    entries = ST["tfa"][uid]
    if m == "GET" and eid is None:
        return ok(list(entries))
    if ST["fail"]:
        return httpx.Response(403, json={"data": None, "message": PERM_SECRET})
    if "password" in body:
        return _bad("Kaji ne doit jamais envoyer de mot de passe")
    if m == "POST" and eid is None:
        extra = set(body) - {"type", "description", "totp", "value", "challenge"}
        if extra or body.get("type") not in ("totp", "u2f", "webauthn", "recovery", "yubico"):
            return _bad(f"paramètres refusés {sorted(extra)}")
        if body["type"] == "totp" and (not URI_RX.fullmatch(body.get("totp", "")) or not re.fullmatch(r"[0-9]{6,8}", body.get("value", ""))):
            return _bad("totp : URI ou valeur invalide")
        if body["type"] == "recovery" and ("totp" in body or "value" in body):
            return _bad("recovery : pas de totp ni de valeur")
        if body["type"] not in ("totp", "recovery"):
            return _bad("type non géré par le faux")
        WRITES.append((m, p, body))
        new_id = f"n{ST['next']}"
        ST["next"] += 1
        if not ST["noapply"]:
            entries.append({"id": new_id, "type": body["type"], "created": 1800000000, "enable": 1, **({"description": body["description"]} if "description" in body else {})})
        return ok({"id": new_id, **({"recovery": ST.get("recovery", RECOVERY)} if body["type"] == "recovery" else {})})
    cur = next((e for e in entries if e["id"] == eid), None)
    if cur is None:
        return httpx.Response(500, json={"data": None, "message": "entrée inconnue"})
    if m == "PUT":
        if set(body) - {"description", "enable"} or body.get("enable", "1") not in ("0", "1"):
            return _bad(f"paramètres refusés {sorted(set(body) - {'description', 'enable'})}")
        WRITES.append((m, p, body))
        if not ST["noapply"]:
            if "enable" in body:
                cur["enable"] = int(body["enable"])
            if "description" in body:
                cur["description"] = body["description"]
        return ok()
    if m == "DELETE":
        if body:
            return _bad("aucun paramètre attendu")
        WRITES.append((m, p, body))
        if not ST["noapply"]:
            entries.remove(cur)
        return ok()
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
    return f"/api/connections/{cid}/access/tfa{tail}"


def audit_text(c):
    return c.get("/api/audit").text


def no_secret(*texts):
    return all(s not in t for t in texts for s in (TOTP_SECRET, CODE, PERM_SECRET, UUID, PWD, "1111-2222"))


def add_totp(c, cid, **over):
    body = {"userid": "bob@pve", "type": "totp", "totp": URI, "value": CODE, "description": "appli", "confirm": True, "type_name": "bob@pve", **over}
    return c.post(u(cid), json={k: v for k, v in body.items() if v is not None})


# ---------------------------------------------------------------- lecture
def test_list_is_shaped_without_secret_and_hostile_rows_are_dropped(api):
    c, cid = api
    r = c.get(u(cid))
    assert r.status_code == 200 and [x["userid"] for x in r.json()] == ["bob@pve", "carl@ldap", "root@pam"]
    bob = r.json()[0]
    assert bob["entries"] == [{"id": "t1", "type": "totp", "description": "téléphone", "created": 1700000000, "enabled": True}, {"id": "r1", "type": "recovery", "description": None, "created": 1700000100, "enabled": True}]
    assert r.json()[1]["locked"] is True and bob["locked"] is False and no_secret(r.text)


def test_shape_drops_invalid_entries_and_ids():
    s = shape_tfa([{"userid": "../x", "entries": []}, {"userid": "ok@pve", "entries": [{"id": "../x", "type": "totp"}, {"id": "a", "type": "bogus"}, {"id": "b", "type": "totp", "enable": "0", "totp": TOTP_SECRET},
                                                                                       "junk", {"id": "c", "type": "webauthn", "description": "x" * 400}]}, "junk"])
    assert [x["userid"] for x in s] == ["ok@pve"] and [e["id"] for e in s[0]["entries"]] == ["b", "c"] and s[0]["entries"][0]["enabled"] is False
    assert len(s[0]["entries"][1]["description"]) == 255 and TOTP_SECRET not in repr(s)


def test_one_users_entries(api):
    c, cid = api
    assert [e["id"] for e in c.get(u(cid, "/bob@pve")).json()["entries"]] == ["t1", "r1"]
    assert c.get(u(cid, "/pas-un-id")).status_code == 422


def test_reads_need_a_session(client):
    assert client.get(u(1)).status_code == 401 and client.get(u(1, "/bob@pve")).status_code == 401


# ---------------------------------------------------------------- secret TOTP neuf
def test_totp_setup_returns_a_fresh_valid_secret_and_keeps_nothing(api):
    c, cid = api
    r1, r2 = c.post(u(cid, "/totp-setup"), json={"userid": "eve@pve"}), c.post(u(cid, "/totp-setup"), json={"userid": "eve@pve"})
    assert r1.status_code == 200 and r1.headers["cache-control"] == "no-store" and r1.json()["secret"] != r2.json()["secret"]
    j = r1.json()
    assert re.fullmatch(r"[A-Z2-7]{32}", j["secret"]) and check_totp_uri(j["uri"]) == j["uri"] and j["secret"] in j["uri"] and "eve%40pve" in j["uri"] and not SEEN
    assert no_secret(audit_text(c)) and j["secret"] not in audit_text(c)


@pytest.mark.parametrize("uid", ["eve", "../x@pve", "a b@pve", "@pve", "eve@", "x" * 70 + "@pve", 5])
def test_totp_setup_validates_the_user(api, uid):
    c, cid = api
    assert c.post(u(cid, "/totp-setup"), json={"userid": uid}).status_code == 422


def test_new_totp_helper_is_random_and_well_formed():
    a, b = new_totp("x@pve"), new_totp("x@pve")
    assert a["secret"] != b["secret"] and check_totp_uri(a["uri"])


# ---------------------------------------------------------------- ajout
def test_add_totp_sends_exact_params_and_nothing_secret_comes_back(api):
    c, cid = api
    r = add_totp(c, cid)
    assert r.status_code == 201, r.text
    assert WRITES[-1] == ("POST", "/access/tfa/bob@pve", {"type": "totp", "description": "appli", "totp": URI, "value": CODE}) and "password" not in WRITES[-1][2]
    assert r.json() == {"id": "n1", "type": "totp"} and no_secret(r.text, audit_text(c)) and r.headers["cache-control"] == "no-store"
    assert "totp ajouté (id n1, description définie)" in audit_text(c)


def test_add_recovery_codes_are_shown_once_and_never_logged(api):
    c, cid = api
    r = c.post(u(cid), json={"userid": "bob@pve", "type": "recovery", "confirm": True, "type_name": "bob@pve"})
    assert r.status_code == 201 and r.json()["recovery"] == RECOVERY and WRITES[-1][2] == {"type": "recovery"}
    assert "1111-2222" not in audit_text(c) and "recovery" in audit_text(c)


def test_recovery_codes_from_proxmox_are_filtered_and_bounded(api):
    c, cid = api
    ST["recovery"] = ["ok-1111-2222", "<script>alert(1)</script>", 5, None, "x" * 100, "a b", "ok-3333"] + [f"zz-{i:04d}" for i in range(40)]
    r = c.post(u(cid), json={"userid": "bob@pve", "type": "recovery", "confirm": True, "type_name": "bob@pve"})
    codes = r.json()["recovery"]
    assert r.status_code == 201 and codes[:2] == ["ok-1111-2222", "ok-3333"] and len(codes) <= 20 and all(re.fullmatch(r"[A-Za-z0-9\-]{4,64}", x) for x in codes) and "<script>" not in r.text


def test_a_16_character_secret_is_the_minimum():
    check_totp_uri("otpauth://totp/x?secret=" + "A" * 16)
    with pytest.raises(ValueError):
        check_totp_uri("otpauth://totp/x?secret=" + "A" * 15)


def test_add_needs_confirm_and_the_user_retyped(api):
    c, cid = api
    assert add_totp(c, cid, confirm=False).status_code == 400 and add_totp(c, cid, type_name="eve@pve").status_code == 400 and add_totp(c, cid, type_name=None).status_code == 400 and not WRITES


def test_turning_two_factor_on_for_an_account_needs_the_phrase(api):
    c, cid = api
    body = {"userid": "eve@pve", "type": "totp", "totp": URI, "value": CODE, "confirm": True, "type_name": "eve@pve"}
    r = c.post(u(cid), json=body)
    assert r.status_code == 409 and "ne pourra plus se connecter" in r.json()["detail"] and not WRITES
    assert c.post(u(cid), json={**body, "acknowledge_cut_access": True}).status_code == 409
    assert c.post(u(cid), json={**body, "phrase": PHRASE}).status_code == 409
    assert c.post(u(cid), json={**body, "acknowledge_cut_access": True, "phrase": "coupure possible"}).status_code == 409
    r = c.post(u(cid), json={**body, "acknowledge_cut_access": True, "phrase": PHRASE})
    assert r.status_code == 201 and "double authentification activée" in audit_text(c)
    assert add_totp(c, cid, description="second").status_code == 201                                           # bob a déjà une entrée active : pas de phrase


def test_an_account_with_only_disabled_entries_also_needs_the_phrase(api):
    c, cid = api
    r = c.post(u(cid), json={"userid": "carl@ldap", "type": "recovery", "confirm": True, "type_name": "carl@ldap"})
    assert r.status_code == 409 and not WRITES


def test_add_dry_run_reports_the_lock_and_writes_nothing(api):
    c, cid = api
    r = c.post(u(cid), json={"userid": "eve@pve", "type": "totp", "totp": URI, "value": CODE, "dry_run": True})
    assert r.status_code == 201 and r.json() == {"dry_run": True, "params": {"type": "totp", "totp": "défini", "value": "défini"}, "locks": {"turns_on": True}} and not WRITES and TOTP_SECRET not in r.text
    assert c.post(u(cid), json={"userid": "bob@pve", "type": "recovery", "dry_run": True}).json()["locks"]["turns_on"] is False


@pytest.mark.parametrize("over", [
    {"totp": None}, {"value": None}, {"totp": None, "value": None},
    {"totp": "http://x"}, {"totp": "otpauth://hotp/x?secret=" + TOTP_SECRET}, {"totp": f"otpauth://totp/x?secret=abc"}, {"totp": "otpauth://totp/x?secret=ABCDEFG"}, {"totp": "otpauth://totp/x?secret=" + "A" * 15}, {"totp": f"otpauth://totp/x?secret={TOTP_SECRET}&algorithm=SHA256"},
    {"totp": f"otpauth://totp/x?secret={TOTP_SECRET}&period=60"}, {"totp": f"otpauth://totp/x?secret={TOTP_SECRET}&digits=9"}, {"totp": f"otpauth://totp/x?secret={TOTP_SECRET}&evil=1"},
    {"totp": f"otpauth://totp/x?secret={TOTP_SECRET}&secret={TOTP_SECRET}"}, {"totp": f"otpauth://totp/x?secret={TOTP_SECRET}&issuer=a b"}, {"totp": f"otpauth://totp/x?secret={TOTP_SECRET}\n"},
    {"totp": "otpauth://totp/?secret=" + TOTP_SECRET}, {"totp": "x" * 800},
    {"value": "12345"}, {"value": "123456789"}, {"value": "12345a"}, {"value": " 123456"}, {"value": "123456\n"},
    {"type": "u2f"}, {"type": "webauthn"}, {"type": "yubico"}, {"type": "bogus"}, {"type": ""},
    {"description": "a\x00b"}, {"description": "a\nb"}, {"description": "x" * 256},
    {"userid": "bob"}, {"userid": "../x@pve"}, {"confirm": "true"},
])
def test_add_values_are_validated_before_anything_is_sent(api, over):
    c, cid = api
    assert add_totp(c, cid, **over).status_code == 422 and not WRITES


def test_recovery_codes_accept_neither_an_uri_nor_a_code(api):
    c, cid = api
    for extra in ({"totp": URI}, {"value": CODE}):
        r = c.post(u(cid), json={"userid": "bob@pve", "type": "recovery", "confirm": True, "type_name": "bob@pve", **extra})
        assert r.status_code == 422 and not WRITES


@pytest.mark.parametrize("typ", ["u2f", "webauthn", "yubico", "bogus", ""])
def test_types_that_need_the_browser_are_refused_even_without_uri_or_code(api, typ):
    c, cid = api
    r = c.post(u(cid), json={"userid": "bob@pve", "type": typ, "confirm": True, "type_name": "bob@pve"})
    assert r.status_code == 422 and "totp ou recovery" in r.text and not WRITES


def test_a_password_field_is_ignored_and_never_forwarded(api):
    c, cid = api
    r = add_totp(c, cid, password="le-mot-de-passe-de-bob")
    assert r.status_code == 201 and "password" not in WRITES[-1][2] and "le-mot-de-passe" not in audit_text(c)


def test_add_not_created_by_proxmox_is_a_bad_gateway(api):
    c, cid = api
    ST["noapply"] = True
    r = add_totp(c, cid)
    assert r.status_code == 502 and "n'a pas créé" in r.json()["detail"]


# ---------------------------------------------------------------- comptes protégés
@pytest.mark.parametrize("uid", ["root@pam", "kaji@pve", "admin@pve"])
def test_protected_accounts_are_never_touched(api, uid):
    c, cid = api
    assert add_totp(c, cid, userid=uid, type_name=uid).status_code == 403
    assert c.put(u(cid, f"/{uid}/x1"), json={"enable": False, "confirm": True, "type_name": uid}).status_code == 403
    assert c.delete(u(cid, f"/{uid}/x1?confirm=true&name={uid}")).status_code == 403
    assert not WRITES and all(r.method == "GET" for r in SEEN)


# ---------------------------------------------------------------- modification
def test_update_sends_the_exact_params_and_reads_back(api):
    c, cid = api
    r = c.put(u(cid, "/bob@pve/t1"), json={"enable": False, "description": "ancien téléphone", "confirm": True, "type_name": "bob@pve"})
    assert r.status_code == 200, r.text
    assert WRITES[-1] == ("PUT", "/access/tfa/bob@pve/t1", {"enable": "0", "description": "ancien téléphone"})
    assert r.json()["enabled"] is False and r.json()["description"] == "ancien téléphone"


def test_enabling_the_first_entry_of_an_account_needs_the_phrase(api):
    c, cid = api
    body = {"enable": True, "confirm": True, "type_name": "carl@ldap"}
    r = c.put(u(cid, "/carl@ldap/w1"), json=body)
    assert r.status_code == 409 and not WRITES
    assert c.put(u(cid, "/carl@ldap/w1"), json={**body, "acknowledge_cut_access": True, "phrase": PHRASE}).status_code == 200
    assert c.put(u(cid, "/bob@pve/t1"), json={"enable": True, "confirm": True, "type_name": "bob@pve"}).status_code == 200            # déjà active : aucun verrou
    assert c.put(u(cid, "/bob@pve/t1"), json={"enable": False, "confirm": True, "type_name": "bob@pve"}).status_code == 200            # désactiver : aucun verrou


def test_update_refusals(api):
    c, cid = api
    assert c.put(u(cid, "/bob@pve/t1"), json={"enable": False}).status_code == 400
    assert c.put(u(cid, "/bob@pve/t1"), json={"enable": False, "confirm": True, "type_name": "eve@pve"}).status_code == 400
    assert c.put(u(cid, "/bob@pve/t1"), json={"confirm": True, "type_name": "bob@pve"}).status_code == 422
    assert c.put(u(cid, "/bob@pve/zzz"), json={"enable": False, "confirm": True, "type_name": "bob@pve"}).status_code == 404
    for bad in ({"enable": "0"}, {"enable": 1}, {"description": "a\x00b"}, {"description": "x" * 256}):
        assert c.put(u(cid, "/bob@pve/t1"), json={**bad, "confirm": True, "type_name": "bob@pve"}).status_code == 422
    assert not WRITES


def test_update_dry_run_and_not_applied(api):
    c, cid = api
    assert c.put(u(cid, "/carl@ldap/w1"), json={"enable": True, "dry_run": True}).json() == {"dry_run": True, "params": {"enable": "1"}, "locks": {"turns_on": True}} and not WRITES
    ST["noapply"] = True
    r = c.put(u(cid, "/bob@pve/t1"), json={"enable": False, "confirm": True, "type_name": "bob@pve"})
    assert r.status_code == 502 and "n'a pas appliqué" in r.json()["detail"]


# ---------------------------------------------------------------- suppression
def test_delete_an_entry_with_the_user_retyped(api):
    c, cid = api
    assert c.delete(u(cid, "/bob@pve/r1")).status_code == 400 and c.delete(u(cid, "/bob@pve/r1?confirm=true&name=eve@pve")).status_code == 400 and not WRITES
    r = c.delete(u(cid, "/bob@pve/r1?confirm=true&name=bob@pve"))
    assert r.status_code == 200 and r.json() == {"deleted": "r1"} and WRITES[-1] == ("DELETE", "/access/tfa/bob@pve/r1", {}) and [e["id"] for e in ST["tfa"]["bob@pve"]] == ["t1"]


def test_deleting_the_last_active_entry_is_announced_not_locked(api):
    c, cid = api
    assert c.delete(u(cid, "/bob@pve/t1?dry_run=true")).json() == {"dry_run": True, "locks": {"turns_off": False}}
    c.delete(u(cid, "/bob@pve/r1?confirm=true&name=bob@pve"))
    assert c.delete(u(cid, "/bob@pve/t1?dry_run=true")).json()["locks"]["turns_off"] is True
    assert c.delete(u(cid, "/bob@pve/t1?confirm=true&name=bob@pve")).status_code == 200 and "double authentification désactivée" in audit_text(c)


def test_delete_unknown_and_not_applied(api):
    c, cid = api
    assert c.delete(u(cid, "/bob@pve/zzz?confirm=true&name=bob@pve")).status_code == 404
    ST["noapply"] = True
    r = c.delete(u(cid, "/bob@pve/r1?confirm=true&name=bob@pve"))
    assert r.status_code == 502 and "n'a pas supprimé" in r.json()["detail"]


# ---------------------------------------------------------------- session, audit, erreurs
def test_every_write_needs_the_admin_session(api):
    c, cid = api
    assert c.delete(f"/api/connections/{cid}/admin-session").status_code in (200, 204)
    for method, tail, body in (("POST", "", {"userid": "bob@pve", "type": "recovery"}), ("PUT", "/bob@pve/t1", {"enable": False}), ("DELETE", "/bob@pve/t1?confirm=true&name=bob@pve", None)):
        r = c.request(method, u(cid, tail), **({"json": body} if body is not None else {}))
        assert r.status_code in (401, 403), (method, r.status_code)
    assert not WRITES


def test_writes_need_a_kaji_session(client):
    for method, tail in (("POST", ""), ("PUT", "/bob@pve/t1"), ("DELETE", "/bob@pve/t1"), ("POST", "/totp-setup")):
        assert client.request(method, u(1, tail), json={}).status_code == 401


def test_every_write_and_refusal_is_audited_without_secret(api):
    c, cid = api
    add_totp(c, cid)
    add_totp(c, cid, type_name="eve@pve")                                                                     # refus
    c.put(u(cid, "/bob@pve/t1"), json={"enable": False, "confirm": True, "type_name": "bob@pve"})
    c.delete(u(cid, "/bob@pve/r1?confirm=true&name=bob@pve"))
    add_totp(c, cid, userid="root@pam", type_name="root@pam")                                                 # refus protégé
    pairs = {(a["action"], a["status"]) for a in c.get("/api/audit").json()}
    assert {("tfa-add", "started"), ("tfa-add", "error"), ("tfa-update", "started"), ("tfa-delete", "started")} <= pairs and no_secret(audit_text(c))


def test_proxmox_error_is_passed_on_without_leaking_its_message(api):
    c, cid = api
    ST["fail"] = True
    r = add_totp(c, cid)
    assert r.status_code in (403, 502) and no_secret(r.text, audit_text(c))
    # constaté en réel (2026-11-13) : Proxmox refuse la TFA aux jetons d'API (allowtoken=0) même avec le rôle Administrator ; Kaji le dit
    assert r.status_code == 403 and "allowtoken=0" in r.json()["detail"] and "allowtoken=0" in audit_text(c)


# ---------------------------------------------------------------- débloquer un compte (unlock-tfa)
def unlock(c, cid, uid="carl@ldap", **body):
    return c.post(u(cid, f"/{uid}/unlock"), json=body)


def test_unlock_dry_run_writes_nothing(api):
    c, cid = api
    r = unlock(c, cid, dry_run=True)
    assert r.status_code == 200 and r.json() == {"dry_run": True, "locked": True} and not WRITES


def test_unlock_needs_confirm_and_the_typed_name(api):
    c, cid = api
    assert unlock(c, cid).status_code == 400 and unlock(c, cid, confirm=True).status_code == 400
    assert unlock(c, cid, confirm=True, type_name="autre@ldap").status_code == 400 and not WRITES and "carl@ldap" in ST["locked"]


def test_unlock_works_and_is_read_back(api):
    c, cid = api
    r = unlock(c, cid, confirm=True, type_name="carl@ldap")
    assert r.status_code == 200 and r.json() == {"unlocked": "carl@ldap"}
    assert WRITES == [("PUT", "/access/users/carl@ldap/unlock-tfa", {})] and "carl@ldap" not in ST["locked"]
    assert ("tfa-unlock", "started") in {(a["action"], a["status"]) for a in c.get("/api/audit").json()}


def test_unlock_refuses_an_account_that_is_not_locked(api):
    c, cid = api
    r = unlock(c, cid, uid="bob@pve", confirm=True, type_name="bob@pve")
    assert r.status_code == 409 and "pas verrouillé" in r.json()["detail"] and not WRITES


def test_unlock_not_applied_by_proxmox_is_a_502(api):
    c, cid = api
    ST["unlock_noop"] = True
    r = unlock(c, cid, confirm=True, type_name="carl@ldap")
    assert r.status_code == 502 and "pas débloqué" in r.json()["detail"]


def test_unlock_requires_the_admin_session(api):
    c, cid = api
    assert c.delete(f"/api/connections/{cid}/admin-session").status_code == 204
    assert unlock(c, cid, confirm=True, type_name="carl@ldap").status_code == 403 and not WRITES


def test_unlock_forbidden_by_proxmox_is_not_reported_as_the_tfa_token_rule(api):
    """unlock-tfa accepte les jetons (allowtoken=1) : un 403 ici n'est PAS la règle « TFA interdite aux jetons »."""
    c, cid = api
    ST["fail"] = True
    assert "allowtoken" not in unlock(c, cid, confirm=True, type_name="carl@ldap").text
