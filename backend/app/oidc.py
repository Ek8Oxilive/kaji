"""SSO par OpenID Connect (lot #443, jalon J2) : Authorization Code + PKCE, sans dépendance de plus (httpx et PyJWT sont déjà là).

Ce qui est vérifié, dans l'ordre, et qui REFUSE la connexion si une seule vérification échoue :
1. **état** (`state`, anti-CSRF de connexion) : un cookie signé, posé au départ, doit correspondre à celui que le fournisseur renvoie (temps constant) ;
2. **PKCE** (S256) : l'échange du code envoie le `code_verifier` que seul ce navigateur-ci connaît ;
3. **signature** de l'ID token par la clé publique du fournisseur (JWKS), algorithmes **asymétriques seulement** (jamais `none`, jamais `HS*`) ;
4. **émetteur** exact, **audience** = notre client, **expiration**, **nonce** (anti-rejeu du jeton), `sub` présent ;
5. l'adresse du fournisseur et ses points d'accès sont en **https** (seule la boucle locale fait exception : essais).
Rien n'est jamais journalisé ni renvoyé : ni code, ni jeton, ni secret du client. Une panne du fournisseur donne un refus générique, jamais une page d'erreur détaillée.
"""
import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AdminUser, UserIdentity
from .security import hash_password

ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384")       # asymétriques seulement
STATE_SECONDS = 600
CACHE_SECONDS = 600
JWKS_REFETCH_MIN_SECONDS = 60
CALLBACK_PATH = "/api/auth/oidc/callback"
LOOPBACK = ("localhost", "127.0.0.1", "[::1]", "::1")
USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}")


class OidcError(Exception):
    """Refus de la connexion SSO. Le message est un MOTIF COURT pour l'audit (jamais une valeur reçue du fournisseur)."""


def enabled(s=None) -> bool:
    return bool((s or get_settings()).kaji_oidc_issuer)


def _secure(url: str) -> bool:
    p = urlsplit(url)
    return bool(p.hostname) and not p.username and not p.fragment and (p.scheme == "https" or (p.scheme == "http" and p.netloc.split(":")[0] in LOOPBACK))


def check_config(s=None) -> list[str]:
    """Erreurs de configuration (liste vide = valide ou SSO désactivé). Appelée au démarrage : une erreur empêche de démarrer."""
    s = s or get_settings()
    if not s.kaji_oidc_issuer:
        return []
    errors = []
    if not _secure(s.kaji_oidc_issuer):
        errors.append("KAJI_OIDC_ISSUER doit être une adresse https")
    if not s.kaji_oidc_client_id.strip():
        errors.append("KAJI_OIDC_CLIENT_ID est obligatoire")
    if not _secure(s.kaji_oidc_redirect_uri) or urlsplit(s.kaji_oidc_redirect_uri).path != CALLBACK_PATH or urlsplit(s.kaji_oidc_redirect_uri).query:
        errors.append(f"KAJI_OIDC_REDIRECT_URI doit être une adresse https qui se termine par {CALLBACK_PATH}")
    if s.kaji_oidc_default_role not in ("operator", "viewer"):
        errors.append("KAJI_OIDC_DEFAULT_ROLE doit être operator ou viewer (jamais admin)")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", s.kaji_oidc_username_claim):
        errors.append("KAJI_OIDC_USERNAME_CLAIM : nom de champ invalide")
    return errors


def scopes(s=None) -> str:
    wanted = (s or get_settings()).kaji_oidc_scopes.split()
    return " ".join(["openid"] + [x for x in wanted if x != "openid" and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,64}", x)])


def client() -> httpx.AsyncClient:
    """Client HTTP vers le fournisseur : délai court, aucune redirection suivie. Les tests le remplacent."""
    return httpx.AsyncClient(timeout=8.0, follow_redirects=False)


# ---------------------------------------------------------------- l'état de la connexion (cookie signé, 10 minutes)
def _state_key(secret_key: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kaji-oidc-state-v1").derive(secret_key.encode())


def new_flow() -> dict:
    return {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32), "verifier": secrets.token_urlsafe(48)}


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def seal_flow(secret_key: str, flow: dict) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({**flow, "iat": now, "exp": now + timedelta(seconds=STATE_SECONDS), "purpose": "oidc"}, _state_key(secret_key), algorithm="HS256")


def open_flow(secret_key: str, token: str | None) -> dict | None:
    if not token:
        return None
    try:
        data = jwt.decode(token, _state_key(secret_key), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if data.get("purpose") != "oidc" or not all(isinstance(data.get(k), str) and data[k] for k in ("state", "nonce", "verifier")):
        return None
    return {k: data[k] for k in ("state", "nonce", "verifier")}


# ---------------------------------------------------------------- le fournisseur : découverte et clés (mises en cache 10 minutes)
_discovery: tuple[float, dict] | None = None
_jwks: tuple[float, dict] | None = None
_jwks_fetched_at = float("-inf")


def reset_cache() -> None:
    global _discovery, _jwks, _jwks_fetched_at
    _discovery, _jwks, _jwks_fetched_at = None, None, float("-inf")


async def _get_json(url: str) -> dict:
    try:
        async with client() as c:
            r = await c.get(url)
        data = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        raise OidcError("fournisseur injoignable") from None
    if not isinstance(data, dict):
        raise OidcError("réponse du fournisseur illisible")
    return data


async def discovery(s=None) -> dict:
    global _discovery
    s = s or get_settings()
    if _discovery and time.monotonic() - _discovery[0] < CACHE_SECONDS:
        return _discovery[1]
    issuer = s.kaji_oidc_issuer.rstrip("/")
    doc = await _get_json(f"{issuer}/.well-known/openid-configuration")
    if str(doc.get("issuer", "")).rstrip("/") != issuer:
        raise OidcError("émetteur annoncé différent de celui configuré")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(doc.get(key), str) or not _secure(doc[key]):
            raise OidcError("point d'accès du fournisseur absent ou non sécurisé")
    _discovery = (time.monotonic(), doc)
    return doc


def authorize_url(doc: dict, flow: dict, s=None) -> str:
    s = s or get_settings()
    q = {"response_type": "code", "client_id": s.kaji_oidc_client_id, "redirect_uri": s.kaji_oidc_redirect_uri, "scope": scopes(s), "state": flow["state"], "nonce": flow["nonce"],
         "code_challenge": challenge(flow["verifier"]), "code_challenge_method": "S256"}
    return f"{doc['authorization_endpoint']}{'&' if '?' in doc['authorization_endpoint'] else '?'}{urlencode(q)}"


async def exchange_code(doc: dict, code: str, verifier: str, s=None) -> str:
    """Échange le code contre l'ID token (avec le `code_verifier` PKCE). Renvoie l'ID token."""
    s = s or get_settings()
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": s.kaji_oidc_redirect_uri, "client_id": s.kaji_oidc_client_id, "code_verifier": verifier}
    auth = (s.kaji_oidc_client_id, s.kaji_oidc_client_secret) if s.kaji_oidc_client_secret else None
    try:
        async with client() as c:
            r = await c.post(doc["token_endpoint"], data=data, auth=auth, headers={"Accept": "application/json"})
        body = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        raise OidcError("échange du code impossible") from None
    token = body.get("id_token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        raise OidcError("le fournisseur a refusé le code")
    return token


async def _key_for(doc: dict, kid: str | None) -> "jwt.PyJWK":
    global _jwks, _jwks_fetched_at
    for attempt in (0, 1):
        if _jwks is None or time.monotonic() - _jwks[0] >= CACHE_SECONDS or attempt == 1:
            if attempt == 1 and time.monotonic() - _jwks_fetched_at < JWKS_REFETCH_MIN_SECONDS:
                break                                                   # rotation : on ne harcèle pas le fournisseur (une relecture par minute au plus)
            _jwks_fetched_at = time.monotonic()
            _jwks = (time.monotonic(), await _get_json(doc["jwks_uri"]))
        keys = [k for k in _jwks[1].get("keys", []) if isinstance(k, dict) and k.get("use", "sig") == "sig"]
        match = [k for k in keys if k.get("kid") == kid] if kid else (keys if len(keys) == 1 else [])
        if match:
            try:
                return jwt.PyJWK.from_dict(match[0])
            except (jwt.PyJWTError, ValueError, KeyError):
                raise OidcError("clé du fournisseur illisible") from None
    raise OidcError("clé de signature inconnue")


async def verify_id_token(doc: dict, id_token: str, nonce: str, s=None) -> dict:
    """Les claims de l'ID token SI toutes les vérifications passent, sinon `OidcError`."""
    s = s or get_settings()
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError:
        raise OidcError("jeton mal formé") from None
    alg = header.get("alg")
    if alg not in ALGORITHMS:
        raise OidcError("algorithme de signature refusé")                 # `none`, `HS256` (clé publique prise pour un secret) et consorts
    key = await _key_for(doc, header.get("kid") if isinstance(header.get("kid"), str) else None)
    try:
        claims = jwt.decode(id_token, key.key, algorithms=[alg], audience=s.kaji_oidc_client_id, issuer=doc["issuer"],          # doc["issuer"] = celui configuré (vérifié à la découverte)
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=60)
    except jwt.PyJWTError:
        raise OidcError("jeton refusé (signature, émetteur, audience ou expiration)") from None
    if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"].encode(), nonce.encode()):
        raise OidcError("nonce différent")
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != s.kaji_oidc_client_id:
        raise OidcError("jeton émis pour plusieurs clients")
    if not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 255:
        raise OidcError("identité absente")
    return claims


# ---------------------------------------------------------------- de l'identité du fournisseur au compte de Kaji
def resolve_user(db: Session, issuer: str, claims: dict, s=None) -> AdminUser | None:
    """Le compte de Kaji de cette personne, ou `None` (refus).
    1. déjà reliée : `(émetteur, sub)` → son compte (le nom a pu changer chez le fournisseur : le lien fait foi) ;
    2. sinon, le champ `KAJI_OIDC_USERNAME_CLAIM` désigne un compte EXISTANT qui n'est relié à personne d'autre : on le relie ;
    3. sinon, avec `KAJI_OIDC_AUTO_CREATE`, un compte neuf (rôle par défaut, jamais administrateur, mot de passe inconnu de tous)."""
    s = s or get_settings()
    sub = claims["sub"]
    ident = db.scalar(select(UserIdentity).where(UserIdentity.issuer == issuer, UserIdentity.sub == sub))
    if ident is not None:
        return db.get(AdminUser, ident.user_id)
    name = claims.get(s.kaji_oidc_username_claim)
    if not isinstance(name, str) or not USERNAME.fullmatch(name):
        return None
    user = db.scalar(select(AdminUser).where(AdminUser.username == name))
    if user is not None:
        if db.scalar(select(UserIdentity).where(UserIdentity.issuer == issuer, UserIdentity.user_id == user.id)) is not None:
            return None                                                  # ce compte est déjà relié à UNE AUTRE personne : un nom repris ne donne pas accès
    elif s.kaji_oidc_auto_create and s.kaji_oidc_default_role in ("operator", "viewer"):
        user = AdminUser(username=name, password_hash=hash_password(secrets.token_urlsafe(48)), role=s.kaji_oidc_default_role)
        db.add(user)
        db.flush()
    else:
        return None
    db.add(UserIdentity(user_id=user.id, issuer=issuer, sub=sub))
    db.commit()
    return user
