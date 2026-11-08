"""Créer, lister et révoquer des tokens d'API (utilisateurs du realm pve), avec l'identité de la session administrateur."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..adminsession import AdminSession, TOKEN_ID
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..tokenwrite import MAX_TOKENS, TokenCreate, create_params, full_id, secret_of, shape_tokens
from ..userwrite import PVE_USER, protected_reason
from .admin_session import admin_call, require_admin
from .cluster import Factory
from .connections import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}/access/users/{userid}/tokens", tags=["access-write"])
UID = Path(pattern=PVE_USER.pattern)
TID = Path(pattern=TOKEN_ID.pattern)


class Ctx:
    def __init__(self, db, user, conn_id, action, target):
        self.db, self.user, self.conn_id, self.action, self.target = db, user, conn_id, action, target

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action, target=self.target, status=st, detail=detail)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)

    def confirmed(self, confirm: bool, typed: str | None, expected: str):
        if not confirm:
            self.refuse("Écriture de droits : renvoie la requête avec confirm=true et l'identifiant complet retapé", 400)
        if typed != expected:
            self.refuse("L'identifiant retapé ne correspond pas : écriture refusée", 400)


async def _list(db, factory, conn_id, s, userid) -> list[dict]:
    return shape_tokens(await admin_call(db, factory, conn_id, s, "get", f"/access/users/{userid}/token"))


async def _known_user(db, factory, conn_id, s, userid) -> bool:
    users = await admin_call(db, factory, conn_id, s, "get", "/access/users")
    return any(isinstance(u, dict) and u.get("userid") == userid for u in (users if isinstance(users, list) else []))


@router.get("")
async def list_tokens(conn_id: int, userid: str = UID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                      adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Tokens d'un utilisateur (nom, privilèges séparés, expiration, commentaire). Jamais de secret. Lecture seule."""
    _, s = adm
    return await _list(db, factory, conn_id, s, userid)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_token(body: TokenCreate, conn_id: int, userid: str = UID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Crée un token à privilèges séparés. **Le secret n'est renvoyé qu'ici, une seule fois** : il n'est ni journalisé ni relisible."""
    user, s = adm
    full = full_id(body.userid, body.tokenid)
    c = Ctx(db, user, conn_id, "token-create", full)
    if body.userid != userid:
        c.refuse("L'utilisateur du corps ne correspond pas à celui de l'adresse", 422)
    c.confirmed(body.confirm, body.type_name, full)
    if reason := protected_reason(body.userid, _get_or_404(db, conn_id).user, s.user):
        c.refuse(reason, 403)
    if not await _known_user(db, factory, conn_id, s, body.userid):
        c.refuse("Utilisateur inconnu", status.HTTP_404_NOT_FOUND)
    existing = await _list(db, factory, conn_id, s, body.userid)
    if any(t["tokenid"] == body.tokenid for t in existing):
        c.refuse("Ce token existe déjà", status.HTTP_409_CONFLICT)
    if len(existing) >= MAX_TOKENS:
        c.refuse(f"Trop de tokens pour cet utilisateur ({MAX_TOKENS} au plus) : révoque-en d'abord", status.HTTP_409_CONFLICT)
    try:
        created = await admin_call(db, factory, conn_id, s, "post", f"/access/users/{body.userid}/token/{body.tokenid}", **create_params(body))
    except HTTPException as e:
        c.log("error", str(e.detail))
        raise
    secret = secret_of(created)
    if secret is None:
        c.refuse("Réponse de Proxmox illisible : le token a peut-être été créé sans que son secret soit connu, révoque-le puis recommence", status.HTTP_502_BAD_GATEWAY)
    if not any(t["tokenid"] == body.tokenid and t["privsep"] for t in await _list(db, factory, conn_id, s, body.userid)):
        c.refuse("Proxmox n'a pas créé le token (ou sans privilèges séparés) : son secret n'est pas relayé", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "créé (privilèges séparés" + (f", expire {body.expire}" if body.expire else ", sans expiration") + ") ; secret affiché une seule fois")
    return {"created": full, "secret": secret, "privsep": True, "expire": body.expire or None,
            "warning": "Ce secret ne sera plus jamais affiché : note-le maintenant. Le token n'a aucun droit tant qu'une ACL ne lui en donne pas."}


@router.delete("/{tokenid}")
async def revoke_token(conn_id: int, userid: str = UID, tokenid: str = TID, confirm: bool = Query(default=False), name: str = Query(default="", max_length=150),
                       db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Révoque un token (immédiat, irréversible). Exige confirm=true et l'identifiant complet retapé ; jamais le token de Kaji ni ceux des comptes protégés."""
    user, s = adm
    full = full_id(userid, tokenid)
    c = Ctx(db, user, conn_id, "token-revoke", full)
    c.confirmed(confirm, name, full)
    if reason := protected_reason(userid, _get_or_404(db, conn_id).user, s.user):
        c.refuse(reason, 403)
    if not any(t["tokenid"] == tokenid for t in await _list(db, factory, conn_id, s, userid)):
        c.refuse("Token inconnu", status.HTTP_404_NOT_FOUND)
    try:
        await admin_call(db, factory, conn_id, s, "delete", f"/access/users/{userid}/token/{tokenid}")
    except HTTPException as e:
        c.log("error", str(e.detail))
        raise
    if any(t["tokenid"] == tokenid for t in await _list(db, factory, conn_id, s, userid)):
        c.refuse("Proxmox n'a pas révoqué le token", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "révoqué")
    return {"revoked": full}
