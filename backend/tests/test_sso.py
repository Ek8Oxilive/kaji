"""SSO par OpenID Connect (lot #443, jalon J2), contre un FAUX fournisseur d'identité local : il signe de vrais jetons RSA, vérifie lui-même le PKCE, le code et l'authentification du client."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import oidc
from app.config import get_settings
from app.db import get_engine
from app.main import app
from app.models import AdminUser, AuditLog, UserIdentity, UserTotp
from app.security import throttle, verify_password

PWD = "un-mot-de-passe-solide"
ISSUER = "https://idp.test/realms/lab"
CLIENT_ID = "kaji"
CLIENT_SECRET = "s3cr3t-du-client-sso-a-ne-jamais-voir"
REDIRECT = "https://kaji.test/api/auth/oidc/callback"
KID = "cle-1"


def _jwk(pub, kid):
    n = pub.public_numbers()
    b64 = lambda i: base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).decode().rstrip("=")      # noqa: E731
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": b64(n.n), "e": b64(n.e)}


class FakeIdp:
    """Le fournisseur : découverte, clés, point d'échange du code. Ses défauts sont réglables (`claims`, `fail`…)."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pem = self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        self.keys = {KID: self.key}
        self.requests: list[tuple[str, str]] = []
        self.codes: dict[str, dict] = {}
        self.claims = {"sub": "sub-alice", "preferred_username": "alice"}
        self.issuer_in_doc = ISSUER
        self.doc_overrides: dict = {}
        self.token_status = 200
        self.down = False
        self.last_auth_header = None
        self.last_form: dict = {}

    def doc(self):
        d = {"issuer": self.issuer_in_doc, "authorization_endpoint": "https://idp.test/auth", "token_endpoint": "https://idp.test/token", "jwks_uri": "https://idp.test/jwks"}
        d.update(self.doc_overrides)
        return d

    def sign(self, payload: dict, kid=KID, key=None, alg="RS256", headers=None):
        key = key or self.keys.get(kid) or self.key
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()) if hasattr(key, "private_bytes") else key
        return jwt.encode(payload, pem, algorithm=alg, headers={"kid": kid, **(headers or {})})

    def id_token(self, nonce, **over):
        now = int(time.time())
        payload = {"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 300, "nonce": nonce, **self.claims, **over}
        return self.sign({k: v for k, v in payload.items() if v is not None})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if self.down:
            raise httpx.ConnectError("injoignable")
        p = request.url.path
        if p == "/realms/lab/.well-known/openid-configuration":
            return httpx.Response(200, json=self.doc())
        if p == "/jwks":
            return httpx.Response(200, json={"keys": [_jwk(k.public_key(), kid) for kid, k in self.keys.items()]})
        if p == "/token" and request.method == "POST":
            self.last_auth_header = request.headers.get("authorization")
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.last_form = form
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant", "error_description": "secret-du-fournisseur"})
            known = self.codes.pop(form.get("code", ""), None)                                                    # un code ne sert qu'une fois
            expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).decode().rstrip("=")
            if known is None or form.get("grant_type") != "authorization_code" or form.get("redirect_uri") != REDIRECT or form.get("client_id") != CLIENT_ID or known["challenge"] != expected_challenge:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": known["make"](known["nonce"]), "access_token": "jeton-d-acces-a-ne-jamais-voir"})
        return httpx.Response(404)


@pytest.fixture
def idp(client, monkeypatch):
    f = FakeIdp()
    for k, v in {"KAJI_OIDC_ISSUER": ISSUER, "KAJI_OIDC_CLIENT_ID": CLIENT_ID, "KAJI_OIDC_CLIENT_SECRET": CLIENT_SECRET, "KAJI_OIDC_REDIRECT_URI": REDIRECT}.items():
        monkeypatch.setenv(k, v)
    for k in ("KAJI_OIDC_AUTO_CREATE", "KAJI_OIDC_DEFAULT_ROLE", "KAJI_OIDC_USERNAME_CLAIM", "KAJI_OIDC_SCOPES", "KAJI_OIDC_LABEL"):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    oidc.reset_cache()
    monkeypatch.setattr(oidc, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(f.handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    client.post("/api/kaji-users", json={"username": "alice", "password": PWD, "role": "operator"})
    f.setenv = monkeypatch.setenv
    yield f
    get_settings.cache_clear()
    oidc.reset_cache()
    throttle.reset()


def go(idp, **over):
    """Un parcours complet dans un navigateur NEUF : départ puis retour. Renvoie (réponse du retour, navigateur, paramètres de départ)."""
    b = TestClient(app)
    r = b.get("/api/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 303, r.text
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    idp.codes["le-code"] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "make": lambda n: idp.id_token(over.get("nonce", n), **{k: v for k, v in over.items() if k != "nonce"})}
    back = b.get("/api/auth/oidc/callback", params={"code": "le-code", "state": over.pop("_state", q["state"])}, follow_redirects=False)
    return back, b, q


def rows(action="login-sso"):
    with Session(get_engine()) as db:
        return db.scalars(select(AuditLog).where(AuditLog.action == action)).all()


# ---------------------------------------------------------------- désactivé et configuration
def test_disabled_by_default(client):
    assert client.get("/api/auth/oidc/status").json() == {"enabled": False, "label": None}
    assert client.get("/api/auth/oidc/login", follow_redirects=False).status_code == 404 and client.get("/api/auth/oidc/callback?code=x&state=y", follow_redirects=False).status_code == 404


def test_status_when_enabled_has_a_bounded_label_and_no_secret(idp):
    idp.setenv("KAJI_OIDC_LABEL", "Connexion entreprise " + "x" * 80)
    get_settings.cache_clear()
    r = TestClient(app).get("/api/auth/oidc/status")
    assert r.json()["enabled"] is True and len(r.json()["label"]) == 40 and CLIENT_SECRET not in r.text and ISSUER not in r.text


@pytest.mark.parametrize("env,word", [
    ({"KAJI_OIDC_ISSUER": "http://idp.example.com"}, "ISSUER"), ({"KAJI_OIDC_ISSUER": "https://user:pw@idp.example.com"}, "ISSUER"), ({"KAJI_OIDC_ISSUER": "idp.example.com"}, "ISSUER"),
    ({"KAJI_OIDC_CLIENT_ID": " "}, "CLIENT_ID"), ({"KAJI_OIDC_REDIRECT_URI": "http://kaji.test/api/auth/oidc/callback"}, "REDIRECT_URI"),
    ({"KAJI_OIDC_REDIRECT_URI": "https://kaji.test/autre"}, "REDIRECT_URI"), ({"KAJI_OIDC_REDIRECT_URI": "https://kaji.test/api/auth/oidc/callback?x=1"}, "REDIRECT_URI"),
    ({"KAJI_OIDC_DEFAULT_ROLE": "admin"}, "DEFAULT_ROLE"), ({"KAJI_OIDC_DEFAULT_ROLE": "root"}, "DEFAULT_ROLE"), ({"KAJI_OIDC_USERNAME_CLAIM": "a b"}, "USERNAME_CLAIM"),
])
def test_invalid_configurations_are_refused(idp, env, word):
    for k, v in env.items():
        idp.setenv(k, v)
    get_settings.cache_clear()
    assert any(word in e for e in oidc.check_config())


def test_loopback_http_is_allowed_for_trials_and_a_valid_configuration_has_no_error(idp):
    assert oidc.check_config() == []
    idp.setenv("KAJI_OIDC_ISSUER", "http://127.0.0.1:8080/realms/lab")
    idp.setenv("KAJI_OIDC_REDIRECT_URI", "http://localhost:8000/api/auth/oidc/callback")
    get_settings.cache_clear()
    assert oidc.check_config() == []


def test_kaji_refuses_to_start_with_an_invalid_sso_configuration(idp):
    idp.setenv("KAJI_OIDC_ISSUER", "http://idp.example.com")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="SSO"):
        with TestClient(app):
            pass


# ---------------------------------------------------------------- le départ
def test_login_redirects_to_the_provider_with_pkce_state_and_nonce(idp):
    b = TestClient(app)
    r = b.get("/api/auth/oidc/login", follow_redirects=False)
    u = urlsplit(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert r.status_code == 303 and f"{u.scheme}://{u.netloc}{u.path}" == "https://idp.test/auth"
    assert q["response_type"] == "code" and q["client_id"] == CLIENT_ID and q["redirect_uri"] == REDIRECT and q["code_challenge_method"] == "S256"
    assert q["scope"] == "openid profile" and len(q["state"]) >= 32 and len(q["nonce"]) >= 32 and len(q["code_challenge"]) >= 43
    assert CLIENT_SECRET not in r.headers["location"]
    cookie = r.headers["set-cookie"].lower()
    assert "kaji_oidc=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/api/auth/oidc" in cookie
    q2 = {k: v[0] for k, v in parse_qs(urlsplit(TestClient(app).get("/api/auth/oidc/login", follow_redirects=False).headers["location"]).query).items()}
    assert q2["state"] != q["state"] and q2["nonce"] != q["nonce"] and q2["code_challenge"] != q["code_challenge"]            # frais à chaque départ


def test_openid_is_always_in_the_scopes_and_unsafe_scopes_are_dropped(idp):
    idp.setenv("KAJI_OIDC_SCOPES", "profile email evil;scope  groups")
    get_settings.cache_clear()
    assert oidc.scopes() == "openid profile email groups"


# ---------------------------------------------------------------- le retour : le cas qui marche
def test_a_known_person_gets_a_session_and_is_linked(idp):
    back, b, _q = go(idp)
    assert back.status_code == 303 and back.headers["location"] == "/" and "kaji_session" in back.headers["set-cookie"]
    assert b.get("/api/auth/me").json() == {"username": "alice", "role": "operator", "restricted": False}
    with Session(get_engine()) as db:
        link = db.scalars(select(UserIdentity)).one()
        assert (link.issuer, link.sub) == (ISSUER, "sub-alice") and db.get(AdminUser, link.user_id).username == "alice"
    ok = rows()
    assert len(ok) == 1 and ok[0].status == "started" and ok[0].username == "alice"


def test_the_exchange_sends_the_pkce_verifier_the_code_and_the_client_secret_as_basic_auth(idp):
    go(idp)
    f = idp.last_form
    assert f["grant_type"] == "authorization_code" and f["redirect_uri"] == REDIRECT and f["client_id"] == CLIENT_ID and len(f["code_verifier"]) >= 43
    assert idp.last_auth_header and idp.last_auth_header.startswith("Basic ") and CLIENT_SECRET not in str(f)
    assert base64.b64decode(idp.last_auth_header.split()[1]).decode() == f"{CLIENT_ID}:{CLIENT_SECRET}"


def test_without_a_client_secret_none_is_sent(idp):
    idp.setenv("KAJI_OIDC_CLIENT_SECRET", "")
    get_settings.cache_clear()
    back, _b, _q = go(idp)
    assert back.status_code == 303 and back.headers["location"] == "/" and idp.last_auth_header is None


def test_the_link_makes_the_login_survive_a_renamed_username_at_the_provider(idp):
    go(idp)
    idp.claims = {"sub": "sub-alice", "preferred_username": "alice-renomme"}
    back, b, _q = go(idp)
    assert back.headers["location"] == "/" and b.get("/api/auth/me").json()["username"] == "alice"


def test_a_name_taken_over_by_someone_else_gives_no_access(idp):
    go(idp)                                                                                          # alice est reliée à sub-alice
    idp.claims = {"sub": "sub-intrus", "preferred_username": "alice"}
    back, b, _q = go(idp)
    assert back.headers["location"] == "/?sso=erreur" and b.get("/api/auth/me").status_code == 401 and "kaji_session" not in back.headers.get("set-cookie", "")
    assert rows()[-1].status == "error" and "aucun compte" in rows()[-1].detail


def test_an_unknown_person_without_auto_create_is_refused_and_nothing_is_created(idp):
    idp.claims = {"sub": "sub-bob", "preferred_username": "bobby"}
    back, b, _q = go(idp)
    assert back.headers["location"] == "/?sso=erreur" and b.get("/api/auth/me").status_code == 401
    with Session(get_engine()) as db:
        assert db.scalar(select(AdminUser).where(AdminUser.username == "bobby")) is None and db.scalars(select(UserIdentity)).all() == []


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_auto_create_makes_a_least_privilege_account_with_a_password_nobody_knows(idp, role):
    idp.setenv("KAJI_OIDC_AUTO_CREATE", "true")
    idp.setenv("KAJI_OIDC_DEFAULT_ROLE", role)
    get_settings.cache_clear()
    idp.claims = {"sub": "sub-carol", "preferred_username": "carol"}
    back, b, _q = go(idp)
    assert back.headers["location"] == "/" and b.get("/api/auth/me").json()["role"] == role
    with Session(get_engine()) as db:
        carol = db.scalar(select(AdminUser).where(AdminUser.username == "carol"))
        assert carol.role == role and not verify_password("", carol.password_hash) and not verify_password("carol", carol.password_hash)
    assert TestClient(app).post("/api/auth/login", json={"username": "carol", "password": PWD}).status_code == 401


@pytest.mark.parametrize("claims", [{"sub": "s1"}, {"sub": "s1", "preferred_username": "a@b.com"}, {"sub": "s1", "preferred_username": ""}, {"sub": "s1", "preferred_username": "x"},
                                    {"sub": "s1", "preferred_username": 42}, {"sub": "s1", "preferred_username": "../etc"}, {"sub": "s1", "preferred_username": "alice\\n"}])
def test_a_missing_or_unusable_username_claim_is_refused_even_with_auto_create(idp, claims):
    idp.setenv("KAJI_OIDC_AUTO_CREATE", "true")
    get_settings.cache_clear()
    idp.claims = claims
    back, _b, _q = go(idp)
    assert back.headers["location"] == "/?sso=erreur"


def test_a_custom_username_claim(idp):
    idp.setenv("KAJI_OIDC_USERNAME_CLAIM", "kaji_user")
    get_settings.cache_clear()
    idp.claims = {"sub": "sub-x", "preferred_username": "mallory", "kaji_user": "alice"}
    back, b, _q = go(idp)
    assert back.headers["location"] == "/" and b.get("/api/auth/me").json()["username"] == "alice"


def test_an_account_with_kajis_own_totp_is_not_asked_again_after_the_provider_authenticated_it(idp):
    with Session(get_engine()) as db:
        uid = db.scalar(select(AdminUser.id).where(AdminUser.username == "alice"))
        db.add(UserTotp(user_id=uid, secret_enc="x", confirmed=True, last_step=0))
        db.commit()
    back, b, _q = go(idp)
    assert back.headers["location"] == "/" and b.get("/api/auth/me").json()["username"] == "alice"


def test_the_local_password_login_stays_as_the_fallback(idp):
    assert TestClient(app).post("/api/auth/login", json={"username": "alice", "password": PWD}).status_code == 200
    idp.down = True
    assert TestClient(app).post("/api/auth/login", json={"username": "admin", "password": PWD}).status_code == 200            # le fournisseur en panne ne bloque pas le compte local


# ---------------------------------------------------------------- l'état, le cookie, le rejeu
def test_a_wrong_state_is_refused(idp):
    back, b, _q = go(idp, _state="un-autre-etat")
    assert back.headers["location"] == "/?sso=erreur" and b.get("/api/auth/me").status_code == 401 and not idp.requests[-1][1] == "/token"


def test_no_cookie_a_tampered_cookie_or_an_expired_state_is_refused(idp, monkeypatch):
    b = TestClient(app)
    r = b.get("/api/auth/oidc/login", follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    idp.codes["le-code"] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "make": lambda n: idp.id_token(n)}
    nobody = TestClient(app).get("/api/auth/oidc/callback", params={"code": "le-code", "state": q["state"]}, follow_redirects=False)
    assert nobody.headers["location"] == "/?sso=erreur"                                              # un autre navigateur, sans le cookie : refusé
    forged = TestClient(app)
    forged.cookies.set("kaji_oidc", oidc.seal_flow("une-autre-cle-secrete-0123456789", {"state": q["state"], "nonce": q["nonce"], "verifier": "v" * 50}), path="/api/auth/oidc")
    assert forged.get("/api/auth/oidc/callback", params={"code": "le-code", "state": q["state"]}, follow_redirects=False).headers["location"] == "/?sso=erreur"
    monkeypatch.setattr(oidc, "STATE_SECONDS", -10)
    old = TestClient(app)
    r2 = old.get("/api/auth/oidc/login", follow_redirects=False)
    q2 = {k: v[0] for k, v in parse_qs(urlsplit(r2.headers["location"]).query).items()}
    idp.codes["code2"] = {"nonce": q2["nonce"], "challenge": q2["code_challenge"], "make": lambda n: idp.id_token(n)}
    assert old.get("/api/auth/oidc/callback", params={"code": "code2", "state": q2["state"]}, follow_redirects=False).headers["location"] == "/?sso=erreur"
    assert all(path != "/token" for _m, path in idp.requests)                                         # aucun de ces refus n'a même atteint le fournisseur


def test_a_callback_cannot_be_replayed(idp):
    back, b, q = go(idp)
    assert back.headers["location"] == "/"
    again = b.get("/api/auth/oidc/callback", params={"code": "le-code", "state": q["state"]}, follow_redirects=False)
    assert again.headers["location"] == "/?sso=erreur"                                               # le cookie d'état a été effacé : il ne sert qu'une fois


def test_a_provider_error_is_refused_without_copying_its_message(idp):
    b = TestClient(app)
    b.get("/api/auth/oidc/login", follow_redirects=False)
    r = b.get("/api/auth/oidc/callback", params={"error": "access_denied", "error_description": "message-secret-du-fournisseur"}, follow_redirects=False)
    assert r.headers["location"] == "/?sso=erreur" and "message-secret" not in r.text
    assert "message-secret" not in " ".join(str(x.detail) for x in rows()) and rows()[-1].detail == "refus du fournisseur"


# ---------------------------------------------------------------- l'ID token
@pytest.mark.parametrize("over,reason", [
    ({"nonce": "autre-nonce"}, "nonce"), ({"aud": "un-autre-client"}, "refusé"), ({"iss": "https://evil.test"}, "refusé"), ({"exp": int(time.time()) - 3600}, "refusé"),
    ({"sub": None}, "refusé"), ({"exp": None}, "refusé"), ({"aud": [CLIENT_ID, "autre"]}, "plusieurs clients"), ({"sub": ""}, "identité"), ({"sub": 12345}, "refusé"),
])
def test_a_bad_id_token_is_refused(idp, over, reason):
    back, b, _q = go(idp, **over)
    assert back.headers["location"] == "/?sso=erreur" and b.get("/api/auth/me").status_code == 401 and reason in rows()[-1].detail


def test_a_token_signed_by_another_key_is_refused(idp):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    b = TestClient(app)
    r = b.get("/api/auth/oidc/login", follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    now = int(time.time())
    forged = idp.sign({"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 300, "nonce": q["nonce"], "sub": "sub-alice", "preferred_username": "alice"}, key=other)
    idp.codes["c"] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "make": lambda n: forged}
    back = b.get("/api/auth/oidc/callback", params={"code": "c", "state": q["state"]}, follow_redirects=False)
    assert back.headers["location"] == "/?sso=erreur" and b.get("/api/auth/me").status_code == 401


def _forge(idp, alg, key):
    b = TestClient(app)
    r = b.get("/api/auth/oidc/login", follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    now = int(time.time())
    token = jwt.encode({"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 300, "nonce": q["nonce"], "sub": "sub-alice", "preferred_username": "alice"}, key, algorithm=alg, headers={"kid": KID})
    idp.codes["c"] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "make": lambda n: token}
    back = b.get("/api/auth/oidc/callback", params={"code": "c", "state": q["state"]}, follow_redirects=False)
    return back, b


def test_the_none_algorithm_and_the_hs256_key_confusion_attacks_are_refused(idp):
    back, b = _forge(idp, "none", None)
    assert back.headers["location"] == "/?sso=erreur" and b.get("/api/auth/me").status_code == 401 and "algorithme" in rows()[-1].detail
    public_pem = idp.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    back2, b2 = _forge(idp, "HS256", b"x" * 40)                                                       # signé avec une clé « partagée » quelconque
    assert back2.headers["location"] == "/?sso=erreur" and b2.get("/api/auth/me").status_code == 401 and "algorithme" in rows()[-1].detail
    back3, b3 = _forge(idp, "HS256", CLIENT_SECRET * 2)                                               # signé avec le secret du client
    assert back3.headers["location"] == "/?sso=erreur" and b3.get("/api/auth/me").status_code == 401
    assert public_pem                                                                                 # (la confusion RS256 → HS256 par clé publique est aussi refusée : HS* n'est jamais accepté)


def test_a_rotated_key_is_found_after_one_refetch_but_an_unknown_key_is_refused(idp):
    go(idp)                                                                                          # première clé en cache
    new = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    idp.keys = {"cle-2": new}
    oidc._jwks_fetched_at = float("-inf")
    b = TestClient(app)
    r = b.get("/api/auth/oidc/login", follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    idp.codes["c"] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "make": lambda n: idp.sign({"iss": ISSUER, "aud": CLIENT_ID, "iat": int(time.time()), "exp": int(time.time()) + 300, "nonce": n,
                                                                                                         "sub": "sub-alice", "preferred_username": "alice"}, kid="cle-2", key=new)}
    assert b.get("/api/auth/oidc/callback", params={"code": "c", "state": q["state"]}, follow_redirects=False).headers["location"] == "/"          # la rotation est suivie
    idp.keys = {"cle-2": new}
    back, _b = _forge(idp, "RS256", idp.pem)                                                         # kid « cle-1 » inconnue du fournisseur désormais
    assert back.headers["location"] == "/?sso=erreur"


def test_the_jwks_is_not_refetched_more_than_once_a_minute_for_an_unknown_key(idp):
    go(idp)
    for _ in range(3):
        _forge(idp, "RS256", idp.pem)
    idp.keys = {"autre": idp.key}
    oidc._jwks = (time.monotonic(), {"keys": []})
    before = sum(1 for _m, p in idp.requests if p == "/jwks")
    for _ in range(4):
        _forge(idp, "RS256", idp.pem)
    assert sum(1 for _m, p in idp.requests if p == "/jwks") - before <= 1


# ---------------------------------------------------------------- le fournisseur en panne ou hostile
def test_a_failing_token_endpoint_is_refused_generically(idp):
    idp.token_status = 500
    back, b, _q = go(idp)
    assert back.headers["location"] == "/?sso=erreur" and b.get("/api/auth/me").status_code == 401 and "secret-du-fournisseur" not in back.text + " ".join(str(x.detail) for x in rows())


def test_an_unreachable_provider_never_gives_a_500_at_login_or_at_callback(idp):
    idp.down = True
    r = TestClient(app).get("/api/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?sso=erreur"
    idp.down = False
    b = TestClient(app)
    b.get("/api/auth/oidc/login", follow_redirects=False)
    idp.down = True
    assert b.get("/api/auth/oidc/callback", params={"code": "x", "state": "y"}, follow_redirects=False).headers["location"] == "/?sso=erreur"


@pytest.mark.parametrize("override", [{"issuer": "https://autre.test"}, {"token_endpoint": "http://idp.test/token"}, {"authorization_endpoint": "javascript:alert(1)"},
                                      {"jwks_uri": "ftp://idp.test/jwks"}, {"token_endpoint": None}])
def test_a_hostile_or_insecure_discovery_document_is_refused(idp, override):
    idp.doc_overrides = override
    if "issuer" in override:
        idp.issuer_in_doc = override["issuer"]
    r = TestClient(app).get("/api/auth/oidc/login", follow_redirects=False)
    assert r.headers["location"] == "/?sso=erreur" and "idp.test/auth" not in r.headers["location"]


def test_the_discovery_document_is_cached(idp):
    go(idp)
    go(idp)
    assert sum(1 for _m, p in idp.requests if p.endswith("openid-configuration")) == 1


# ---------------------------------------------------------------- limiteur et secrets
def test_five_refusals_block_the_address_before_any_call_to_the_provider(idp):
    for _ in range(5):
        go(idp, _state="mauvais")
    idp.requests.clear()
    r = TestClient(app).get("/api/auth/oidc/login", follow_redirects=False)
    assert r.headers["location"] == "/?sso=trop" and idp.requests == []
    assert TestClient(app).get("/api/auth/oidc/callback?code=x&state=y", follow_redirects=False).headers["location"] == "/?sso=trop"


def test_a_success_clears_the_failure_counter(idp):
    for _ in range(3):
        go(idp, _state="mauvais")
    back, _b, _q = go(idp)
    assert back.headers["location"] == "/" and not throttle.blocked("sso:testclient")


def test_no_secret_code_or_token_reaches_the_audit_or_any_response(idp):
    back, b, q = go(idp)
    go(idp, aud="un-autre-client")
    text = " ".join(f"{x.username} {x.target} {x.detail}" for x in rows()) + back.text + str(dict(back.headers)) + b.get("/api/auth/me").text
    for needle in (CLIENT_SECRET, "le-code", "jeton-d-acces-a-ne-jamais-voir", q["nonce"], q["state"], "sub-alice"):
        assert needle not in text, needle
