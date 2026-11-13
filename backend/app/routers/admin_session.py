"""Session administrateur : ouvrir, consulter, renouveler, fermer. Socle des écritures de droits (voir `docs/m6-ecriture.md`).

Ce fichier n'écrit **aucun droit**. Il garde en mémoire, le temps d'une session, un token d'administration collé par le propriétaire, et fournit
`require_admin` / `admin_client` aux futurs lots d'écriture. Le secret n'est jamais renvoyé, journalisé ni stocké en base.
"""
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.orm import Session

from .. import audit
from ..adminsession import SECRET, TOKEN_ID, USER, AdminSession, sessions
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser, UserSession
from .auth import _session_of
from .cluster import Factory, http_error
from .connections import _get_or_404, _params

router = APIRouter(prefix="/api/connections/{conn_id}/admin-session", tags=["admin-session"])
MAX_PATHS = 50


def kaji_session(request: Request, db: Session = Depends(get_db)) -> tuple[AdminUser, UserSession]:
    """L'utilisateur de Kaji et sa session de connexion (la session administrateur lui est liée)."""
    found = _session_of(request, db)
    if found is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non authentifié")
    return found


class OpenBody(BaseModel):
    user: str = Field(pattern=USER.pattern, description="Compte Proxmox du token, ex. admin@pve")
    token_id: str = Field(pattern=TOKEN_ID.pattern, description="Nom du token, ex. kaji-admin")
    secret: SecretStr = Field(description="Secret du token (UUID) : jamais stocké, jamais renvoyé")

    @field_validator("secret")
    @classmethod
    def _secret(cls, v: SecretStr):
        if not SECRET.fullmatch(v.get_secret_value()):
            raise ValueError("Secret de token invalide")
        return v


def _iso(seconds_left: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds_left)).isoformat()


def _status(s: AdminSession | None) -> dict:
    if s is None:
        return {"active": False}
    left = s.seconds_left()
    return {"active": True, "user": s.user, "token_id": s.token_id, "seconds_left": left, "expires_at": _iso(left), "renewals": s.renewals}


def shape_permissions(raw) -> dict:
    """Droits effectifs d'un token, réduits à ce dont l'interface a besoin : sur quels chemins il peut modifier les droits."""
    paths = raw if isinstance(raw, dict) else {}
    modify = sorted(p for p, privs in paths.items()
                    if isinstance(p, str) and len(p) <= 200 and isinstance(privs, dict) and privs.get("Permissions.Modify") in (1, True))
    return {"can_modify_permissions": bool(modify), "modify_paths": modify[:MAX_PATHS], "paths": min(len(paths), 100000)}


class Ctx:
    def __init__(self, db, user, conn_id, action, target):
        self.db, self.user, self.conn_id, self.action, self.target = db, user, conn_id, action, target

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action,
                     target=self.target, status=st, detail=detail)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)


def admin_client(db: Session, factory: Factory, conn_id: int, s: AdminSession):
    """Client Proxmox qui agit avec l'identité de la session administrateur (à fermer avec `aclose`)."""
    p = _params(_get_or_404(db, conn_id))
    return factory(host=p["host"], port=p["port"], user=s.user, token_id=s.token_id, token_secret=s.secret.get_secret_value(),
                   verify_ssl=p["verify_ssl"], pinned_cert=p.get("pinned_cert"))


def require_admin(conn_id: int, found: tuple[AdminUser, UserSession] = Depends(kaji_session)) -> tuple[AdminUser, AdminSession]:
    """Dépendance des routes d'écriture de droits : refuse (403) s'il n'y a pas de session administrateur active pour cette connexion."""
    user, ksess = found
    s = sessions.get(ksess.id, conn_id)
    if s is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Session administrateur requise : ouvre-la depuis la page Accès")
    return user, s


async def admin_call(db: Session, factory: Factory, conn_id: int, s: AdminSession, method: str, path: str, /, **params):
    """Appel Proxmox avec l'identité de la session administrateur (`method` : get, post, put, delete). Erreurs traduites sans secret."""
    client = admin_client(db, factory, conn_id, s)
    try:
        return await getattr(client, method)(path, **params)
    except httpx.HTTPError as e:
        raise http_error(e) from None
    finally:
        await client.aclose()


async def admin_get(db: Session, factory: Factory, conn_id: int, s: AdminSession, path: str, /, **params):
    return await admin_call(db, factory, conn_id, s, "get", path, **params)


@router.get("")
def get_status(conn_id: int, found: tuple[AdminUser, UserSession] = Depends(kaji_session)):
    return _status(sessions.get(found[1].id, conn_id))


@router.post("", status_code=status.HTTP_201_CREATED)
async def open_session(body: OpenBody, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       found: tuple[AdminUser, UserSession] = Depends(kaji_session)):
    """Ouvre une session de 30 minutes avec un token d'administration. Le token est **vérifié auprès de Proxmox** avant d'être gardé."""
    user, ksess = found
    c = Ctx(db, user, conn_id, "admin-session-open", f"{body.user}!{body.token_id}")
    conn = _get_or_404(db, conn_id)
    if not sessions.allow_attempt(user.id):
        c.refuse("Trop d'essais : attends une minute", status.HTTP_429_TOO_MANY_REQUESTS)
    if body.user == conn.user and body.token_id == conn.token_id:
        c.refuse("Utilise un token distinct de celui de Kaji : le token permanent ne doit pas pouvoir écrire de droits", 422)
    p = _params(conn)
    client = factory(host=p["host"], port=p["port"], user=body.user, token_id=body.token_id,
                     token_secret=body.secret.get_secret_value(), verify_ssl=p["verify_ssl"], pinned_cert=p.get("pinned_cert"))
    try:
        perms = await client.get("/access/permissions")
    except httpx.HTTPError as e:
        err = http_error(e)
        c.log("error", str(err.detail))
        raise err from None
    finally:
        await client.aclose()
    s = sessions.open(ksess.id, user.id, conn_id, body.user, body.token_id, body.secret)
    c.log("started", "session de 30 minutes ouverte (secret non conservé en base)")
    return {**_status(s), **shape_permissions(perms)}


KAJI_TOKEN_OFF = "Option désactivée : ajoute KAJI_ADMIN_USE_KAJI_TOKEN=true au .env de Kaji (et donne les droits d'administration à son token), puis redémarre"


@router.get("/kaji-token")
def kaji_token_allowed(conn_id: int, found: tuple[AdminUser, UserSession] = Depends(kaji_session)):
    """L'option « ouvrir la session avec le token permanent de Kaji » est-elle activée ? (lecture seule)"""
    return {"allowed": bool(get_settings().kaji_admin_use_kaji_token)}


@router.post("/kaji-token", status_code=status.HTTP_201_CREATED)
async def open_with_kaji_token(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                               found: tuple[AdminUser, UserSession] = Depends(kaji_session)):
    """Ouvre la session administrateur avec le token permanent de la connexion (option `KAJI_ADMIN_USE_KAJI_TOKEN`). Même durée, mêmes verrous d'écriture."""
    user, ksess = found
    conn = _get_or_404(db, conn_id)
    c = Ctx(db, user, conn_id, "admin-session-open", f"{conn.user}!{conn.token_id}")
    if not get_settings().kaji_admin_use_kaji_token:
        c.refuse(KAJI_TOKEN_OFF, status.HTTP_403_FORBIDDEN)
    if not sessions.allow_attempt(user.id):
        c.refuse("Trop d'essais : attends une minute", status.HTTP_429_TOO_MANY_REQUESTS)
    p = _params(conn)
    client = factory(**p)
    try:
        perms = await client.get("/access/permissions")
    except httpx.HTTPError as e:
        err = http_error(e)
        c.log("error", str(err.detail))
        raise err from None
    finally:
        await client.aclose()
    s = sessions.open(ksess.id, user.id, conn_id, conn.user, conn.token_id, SecretStr(p["token_secret"]))
    c.log("started", "session de 30 minutes ouverte avec le token permanent de Kaji (option activée)")
    return {**_status(s), **shape_permissions(perms)}


@router.post("/renew")
def renew(conn_id: int, db: Session = Depends(get_db), found: tuple[AdminUser, UserSession] = Depends(kaji_session)):
    user, ksess = found
    s = sessions.get(ksess.id, conn_id)
    c = Ctx(db, user, conn_id, "admin-session-renew", f"{s.user}!{s.token_id}" if s else "—")
    if s is None:
        c.refuse("Aucune session administrateur active", status.HTTP_404_NOT_FOUND)
    if sessions.at_age_limit(ksess.id):
        c.refuse("Âge maximal atteint (4 h) : ferme la session et rouvre-la", status.HTTP_409_CONFLICT)
    s = sessions.renew(ksess.id, conn_id)
    if s is None:                                     # expirée entre-temps
        c.refuse("Aucune session administrateur active", status.HTTP_404_NOT_FOUND)
    c.log("started", f"prolongée de 30 minutes ({s.renewals} renouvellement(s))")
    return _status(s)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def close_session(conn_id: int, db: Session = Depends(get_db), found: tuple[AdminUser, UserSession] = Depends(kaji_session)):
    user, ksess = found
    s = sessions.get(ksess.id, conn_id)
    if s is not None:
        sessions.close(ksess.id)
        audit.record(db, username=user.username, connection_id=conn_id, action="admin-session-close",
                     target=f"{s.user}!{s.token_id}", status="started", detail="fermée")


@router.get("/whoami")
async def whoami(conn_id: int = Path(), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                 adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Droits effectifs de la session administrateur (lecture seule, faite avec l'identité du token collé)."""
    _, s = adm
    return {**_status(s), **shape_permissions(await admin_get(db, factory, conn_id, s, "/access/permissions"))}
