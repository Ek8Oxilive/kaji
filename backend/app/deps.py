"""Fabrique de clients Proxmox, **consciente de l'utilisateur connecté** (lot #440, option A du cadrage).

`get_client_factory` est la dépendance de ~390 routes : elle renvoie une fonction qui construit le client d'une connexion. Si l'utilisateur de Kaji a enregistré son jeton Proxmox
PERSONNEL pour cette connexion, c'est lui qui est utilisé (Proxmox applique ses droits à lui, son journal le nomme) ; sinon le jeton partagé de la connexion est utilisé, sauf si
`KAJI_REQUIRE_USER_TOKEN=true` (accès refusé). Les tâches de fond (planificateur, alertes) gardent le jeton partagé : ticket du jeton de service.

`get_base_client_factory` est ce que les tests remplacent (pour injecter un faux Proxmox) : toute la logique du choix du jeton reste donc réellement exécutée.
"""
import hmac
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from . import tokenkey
from .config import get_settings
from .crypto import decrypt
from .db import get_db, get_engine
from .models import Connection, ServiceToken, UserToken
from .proxmox import ProxmoxClient

Factory = Callable[..., ProxmoxClient]

NO_TOKEN_DETAIL = "Aucun jeton Proxmox personnel enregistré : ajoute le tien dans « Compte » → « Mon jeton Proxmox »."
EXPIRED_DETAIL = "Ton jeton Proxmox personnel a expiré : crée-en un nouveau dans Proxmox et enregistre-le dans « Compte » → « Mon jeton Proxmox »."
REFUSED_DETAIL = "Proxmox refuse ton jeton personnel (révoqué, expiré ou supprimé chez lui) : enregistre-en un nouveau dans « Compte » → « Mon jeton Proxmox »."
KEY_DETAIL = "Les jetons personnels sont illisibles : la clé KAJI_TOKEN_KEY est absente ou a changé. Préviens l'administrateur de Kaji."


class PersonalTokenRefused(httpx.HTTPStatusError):
    """Proxmox a répondu 401 à un jeton PERSONNEL. Sous-classe de `HTTPStatusError` : les routes qui interceptent `httpx.HTTPError` la traduisent comme avant (`http_error`)."""


class ServiceTokenRefused(PersonalTokenRefused):
    """Proxmox a répondu 401 au jeton de SERVICE d'une connexion (message distinct de celui d'un jeton personnel)."""


def get_base_client_factory() -> Factory:
    """Fabrique de clients Proxmox (surchargée dans les tests)."""
    return ProxmoxClient


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _mark_refused(token_id: int) -> None:
    with Session(get_engine()) as s:
        row = s.get(UserToken, token_id)
        if row is not None and row.refused_at is None:
            row.refused_at = datetime.now(timezone.utc)
            s.commit()


def _is_stored_secret(conn: Connection, given) -> bool:
    """Le secret reçu est-il celui de la connexion ENREGISTRÉE (appel construit par `_params`) et non un secret saisi à l'écran ?"""
    try:
        return isinstance(given, str) and hmac.compare_digest(decrypt(get_settings().kaji_secret_key, conn.token_secret_enc), given)
    except ValueError:
        return False


def personal_factory(base: Factory, user_id: int) -> Factory:
    settings = get_settings()

    def lookup(kw: dict) -> tuple[Connection | None, UserToken | None]:
        with Session(get_engine()) as s:
            conn = s.scalars(select(Connection).where(
                Connection.host == kw.get("host"), Connection.port == kw.get("port", 8006),
                Connection.user == kw.get("user"), Connection.token_id == kw.get("token_id"))).first()
            if conn is not None and not _is_stored_secret(conn, kw.get("token_secret")):
                conn = None                          # identifiants SAISIS (test d'une connexion, modification) : on les respecte, on ne les remplace pas par un jeton personnel
            token = s.scalars(select(UserToken).where(UserToken.user_id == user_id, UserToken.conn_id == conn.id)).first() if conn else None
            if conn:
                s.expunge(conn)
            if token:
                s.expunge(token)
            return conn, token

    def factory(**kw) -> ProxmoxClient:
        if kw.get("ticket") is not None or kw.get("anonymous"):          # session par mot de passe, ou appel anonyme : jamais un jeton
            return base(**kw)
        conn, token = lookup(kw)
        if conn is None:
            return base(**kw)
        if token is None:
            if settings.kaji_require_user_token:
                raise HTTPException(status.HTTP_403_FORBIDDEN, NO_TOKEN_DETAIL)
            return base(**kw)
        if _aware(token.expires_at) <= datetime.now(timezone.utc):          # l'échéance est celle que Kaji a retenue : on ne la dépasse jamais, même si Proxmox accepte encore
            raise HTTPException(status.HTTP_403_FORBIDDEN, EXPIRED_DETAIL)
        if token.refused_at is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, REFUSED_DETAIL)
        try:
            secret = tokenkey.decrypt(token.secret_enc)
        except tokenkey.TokenKeyError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, KEY_DETAIL)
        client = base(**{**kw, "user": token.pve_user, "token_id": token.token_id, "token_secret": secret})
        if hasattr(client, "add_response_hook"):
            async def refused(response: httpx.Response) -> None:
                if response.status_code == 401:
                    _mark_refused(token.id)
                    raise PersonalTokenRefused("jeton personnel refusé", request=response.request, response=response)
            client.add_response_hook(refused)
        return client

    def scope_for(conn_id: int) -> int:
        """0 si les appels de cet utilisateur pour cette connexion utilisent le jeton PARTAGÉ (le flux temps réel peut alors être commun) ; sinon son identifiant (flux à part)."""
        with Session(get_engine()) as s:
            has = s.scalars(select(UserToken.id).where(UserToken.user_id == user_id, UserToken.conn_id == conn_id)).first() is not None
        return user_id if has or settings.kaji_require_user_token else 0

    factory.scope_for = scope_for                    # type: ignore[attr-defined]
    return factory


SERVICE_MISSING_DETAIL = "Aucun jeton de service pour cette connexion (KAJI_REQUIRE_SERVICE_TOKEN) : l'administrateur doit en enregistrer un."
SERVICE_EXPIRED_DETAIL = "Le jeton de service de cette connexion a expiré : l'administrateur doit en enregistrer un nouveau."
SERVICE_REFUSED_DETAIL = "Proxmox refuse le jeton de service de cette connexion (révoqué, expiré ou supprimé chez lui) : l'administrateur doit en enregistrer un nouveau."


def _mark_service_refused(token_id: int) -> None:
    with Session(get_engine()) as s:
        row = s.get(ServiceToken, token_id)
        if row is not None and row.refused_at is None:
            row.refused_at = datetime.now(timezone.utc)
            s.commit()


def service_factory(base: Factory) -> Factory:
    """Fabrique des TÂCHES DE FOND (planificateur, alertes) : le jeton de SERVICE de la connexion s'il existe (limité aux droits de ces fonctions), sinon le jeton partagé comme avant,
    sauf `KAJI_REQUIRE_SERVICE_TOKEN=true` (refus). Expiré, refusé par Proxmox ou clé changée : erreur claire, jamais de repli silencieux sur le jeton partagé."""
    def factory(**kw) -> ProxmoxClient:
        settings = get_settings()
        if kw.get("ticket") is not None or kw.get("anonymous"):
            return base(**kw)
        with Session(get_engine()) as s:
            conn = s.scalars(select(Connection).where(
                Connection.host == kw.get("host"), Connection.port == kw.get("port", 8006),
                Connection.user == kw.get("user"), Connection.token_id == kw.get("token_id"))).first()
            if conn is not None and not _is_stored_secret(conn, kw.get("token_secret")):
                conn = None
            token = s.scalars(select(ServiceToken).where(ServiceToken.conn_id == conn.id)).first() if conn else None
            if token:
                s.expunge(token)
        if conn is None:
            return base(**kw)
        if token is None:
            if settings.kaji_require_service_token:
                raise HTTPException(status.HTTP_403_FORBIDDEN, SERVICE_MISSING_DETAIL)
            return base(**kw)
        if _aware(token.expires_at) <= datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_403_FORBIDDEN, SERVICE_EXPIRED_DETAIL)
        if token.refused_at is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, SERVICE_REFUSED_DETAIL)
        try:
            secret = tokenkey.decrypt(token.secret_enc)
        except tokenkey.TokenKeyError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, KEY_DETAIL)
        client = base(**{**kw, "user": token.pve_user, "token_id": token.token_id, "token_secret": secret})
        if hasattr(client, "add_response_hook"):
            async def refused(response: httpx.Response) -> None:
                if response.status_code == 401:
                    _mark_service_refused(token.id)
                    raise ServiceTokenRefused("jeton de service refusé", request=response.request, response=response)
            client.add_response_hook(refused)
        return client
    return factory


def get_client_factory(request: HTTPConnection, db: Session = Depends(get_db), base: Factory = Depends(get_base_client_factory)) -> Factory:
    """La fabrique à utiliser dans une route : choisit le jeton de l'utilisateur de la session (cookie), sinon la fabrique de base."""
    from .routers.auth import _session_of
    found = _session_of(request, db, enforce=False)         # type: ignore[arg-type]  (seuls les cookies sont lus)
    if found is None:
        return base
    return personal_factory(base, found[0].id)
