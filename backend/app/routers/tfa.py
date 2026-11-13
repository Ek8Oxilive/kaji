"""Double authentification (TFA) des utilisateurs (Datacenter → Permissions → Two Factor) : lire, générer un secret TOTP, ajouter, activer / désactiver, supprimer. Lot #384.

Lecture avec le jeton de Kaji ; écritures par la SESSION ADMINISTRATEUR (`User.Modify`). Validation et liste blanche : `app/tfaspec.py`.
Jamais demandé ni transmis : le mot de passe de l'utilisateur. `root@pam`, le compte de Kaji et celui de la session administrateur ne sont jamais modifiés.
Le piège : ACTIVER la double authentification sur un compte dont le titulaire n'a pas le secret le verrouille. Verrou serveur : phrase `COUPURE POSSIBLE`.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy.orm import Session

from .. import audit
from ..adminsession import AdminSession
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..tfaspec import ENTRY_ID, PHRASE, USERID, TfaAdd, TfaUpdate, TotpSetup, add_params, enabled_count, new_totp, shape_entries, shape_tfa, update_params
from ..userwrite import protected_reason
from .admin_session import admin_call, require_admin
from .auth import current_user
from .cluster import FORBIDDEN_DETAIL, Factory, _px
from .connections import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}/access/tfa", tags=["tfa"])
UID = Path(pattern=USERID.pattern)
EID = Path(pattern=ENTRY_ID.pattern)
RECOVERY_CODE = re.compile(r"^[A-Za-z0-9\-]{4,64}$")


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
            self.refuse("Écriture de double authentification : renvoie la requête avec confirm=true et l'identifiant de l'utilisateur retapé", status.HTTP_400_BAD_REQUEST)
        if typed != expected:
            self.refuse("L'identifiant retapé ne correspond pas : écriture refusée", status.HTTP_400_BAD_REQUEST)

    def cut_lock(self, needed: bool, ack: bool, phrase: str | None):
        if needed and not (ack and phrase == PHRASE):
            self.refuse("Coupure possible : la double authentification va s'activer sur ce compte ; si son titulaire n'a pas le secret ou les codes, il ne pourra plus se connecter. "
                        f"Renvoie la requête avec acknowledge_cut_access=true et phrase=\"{PHRASE}\"", status.HTTP_409_CONFLICT)


TOKEN_FORBIDDEN = ("Proxmox interdit de modifier la double authentification avec un jeton d'API (schéma : allowtoken=0), quels que soient ses droits : "
                   "ferme la session et rouvre-la par mot de passe (bouton « Ouvrir avec un mot de passe… » de la page Accès)")


async def _call(c: Ctx, db, factory, conn_id, s, method, path, **params):
    try:
        return await admin_call(db, factory, conn_id, s, method, path, **params)
    except HTTPException as e:
        if e.detail == FORBIDDEN_DETAIL and method != "get" and path.startswith("/access/tfa/") and s.kind == "token":     # constaté en réel le 2026-11-13 : refus même avec le rôle Administrator (Kaji traduit le 403 de Proxmox)
            c.log("error", TOKEN_FORBIDDEN)
            raise HTTPException(status.HTTP_403_FORBIDDEN, TOKEN_FORBIDDEN) from None
        c.log("error", str(e.detail))
        raise


async def _entries(c: Ctx, db, factory, conn_id, s, userid: str) -> list[dict]:
    return shape_entries(await _call(c, db, factory, conn_id, s, "get", f"/access/tfa/{userid}"))


def _protected(c: Ctx, db, conn_id, s, userid: str):
    if reason := protected_reason(userid, _get_or_404(db, conn_id).user, s.user):
        c.refuse(reason, status.HTTP_403_FORBIDDEN)


def _masked(p: dict) -> dict:
    return {k: ("défini" if k in ("totp", "value") else v) for k, v in p.items()}


# ---------------------------------------------------------------- lecture (jeton de Kaji)
@router.get("")
async def list_tfa(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), _u: AdminUser = Depends(current_user)):
    """Entrées de double authentification des utilisateurs que le jeton de Kaji a le droit de voir (Proxmox renvoie tout ou seulement les siennes, selon ses privilèges)."""
    return shape_tfa(await _px(db, factory, conn_id, "get", "/access/tfa"))


@router.get("/{userid}")
async def user_tfa(conn_id: int, userid: str = UID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), _u: AdminUser = Depends(current_user)):
    return {"userid": userid, "entries": shape_entries(await _px(db, factory, conn_id, "get", f"/access/tfa/{userid}"))}


# ---------------------------------------------------------------- secret TOTP neuf (rien n'est gardé côté serveur)
@router.post("/totp-setup")
async def totp_setup(body: TotpSetup, conn_id: int, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    """Génère un secret TOTP et son URI. **Jamais gardés par Kaji** : l'URI revient avec la requête d'ajout, avec le code que l'application affiche.
    Réponse en `Cache-Control: no-store` (intergiciel de `main.py`, vérifié par les tests)."""
    audit.record(db, username=user.username, connection_id=conn_id, action="tfa-totp-setup", target=body.userid, status="started", detail="secret généré, non conservé")
    return new_totp(body.userid)


# ---------------------------------------------------------------- écritures (session administrateur)
@router.post("", status_code=status.HTTP_201_CREATED)
async def add_tfa(body: TfaAdd, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                  adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Ajoute un TOTP (URI de Kaji + code de vérification) ou des codes de secours (affichés une seule fois)."""
    user, s = adm
    c = Ctx(db, user, conn_id, "tfa-add", body.userid)
    try:
        params = add_params(body)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    _protected(c, db, conn_id, s, body.userid)
    turns_on = enabled_count(await _entries(c, db, factory, conn_id, s, body.userid)) == 0
    if body.dry_run:
        return {"dry_run": True, "params": _masked(params), "locks": {"turns_on": turns_on}}
    c.confirmed(body.confirm, body.type_name, body.userid)
    c.cut_lock(turns_on, body.acknowledge_cut_access, body.phrase)
    res = await _call(c, db, factory, conn_id, s, "post", f"/access/tfa/{body.userid}", **params)
    entry_id = res.get("id") if isinstance(res, dict) else None
    if not isinstance(entry_id, str) or not any(e["id"] == entry_id for e in await _entries(c, db, factory, conn_id, s, body.userid)):
        c.refuse("Proxmox n'a pas créé l'entrée", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"{body.type} ajouté (id {entry_id}{', description définie' if body.description else ''}{', double authentification activée' if turns_on else ''})")
    out: dict = {"id": entry_id, "type": body.type}
    if body.type == "recovery":
        codes = res.get("recovery") if isinstance(res, dict) else None
        out["recovery"] = [x for x in (codes if isinstance(codes, list) else [])[:20] if isinstance(x, str) and RECOVERY_CODE.fullmatch(x)]
    return out


class UnlockBody(BaseModel):
    confirm: StrictBool = False
    type_name: str | None = Field(default=None, max_length=80, description="Identifiant de l'utilisateur retapé")
    dry_run: StrictBool = False


@router.post("/{userid}/unlock")
async def unlock_tfa(body: UnlockBody, conn_id: int, userid: str = UID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                     adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Débloque la double authentification d'un compte verrouillé après trop d'échecs (`PUT /access/users/{userid}/unlock-tfa`, accepté avec un jeton).
    Ne baisse pas la sécurité (le compte garde ses entrées) : pas de phrase, mais `confirm` + identifiant retapé, et seulement si le compte est bien verrouillé."""
    user, s = adm
    c = Ctx(db, user, conn_id, "tfa-unlock", userid)

    async def locked() -> bool:
        return any(u["userid"] == userid and u["locked"] for u in shape_tfa(await _call(c, db, factory, conn_id, s, "get", "/access/tfa")))

    if not await locked():
        c.refuse("Ce compte n'est pas verrouillé", status.HTTP_409_CONFLICT)
    if body.dry_run:
        return {"dry_run": True, "locked": True}
    c.confirmed(body.confirm, body.type_name, userid)
    await _call(c, db, factory, conn_id, s, "put", f"/access/users/{userid}/unlock-tfa")
    if await locked():
        c.refuse("Proxmox n'a pas débloqué le compte", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "double authentification débloquée")
    return {"unlocked": userid}


@router.put("/{userid}/{entry}")
async def update_tfa(body: TfaUpdate, conn_id: int, userid: str = UID, entry: str = EID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                     adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Active, désactive ou change la description d'une entrée. Activer la première entrée d'un compte active la double authentification (phrase)."""
    user, s = adm
    c = Ctx(db, user, conn_id, "tfa-update", f"{userid}/{entry}")
    try:
        params = update_params(body)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    _protected(c, db, conn_id, s, userid)
    entries = await _entries(c, db, factory, conn_id, s, userid)
    cur = next((e for e in entries if e["id"] == entry), None)
    if cur is None:
        c.refuse("Entrée inconnue", status.HTTP_404_NOT_FOUND)
    turns_on = body.enable is True and not cur["enabled"] and enabled_count(entries) == 0
    if body.dry_run:
        return {"dry_run": True, "params": params, "locks": {"turns_on": turns_on}}
    c.confirmed(body.confirm, body.type_name, userid)
    c.cut_lock(turns_on, body.acknowledge_cut_access, body.phrase)
    await _call(c, db, factory, conn_id, s, "put", f"/access/tfa/{userid}/{entry}", **params)
    now = next((e for e in await _entries(c, db, factory, conn_id, s, userid) if e["id"] == entry), None)
    if now is None or (body.enable is not None and now["enabled"] != body.enable) or (body.description is not None and (now["description"] or "") != body.description):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", ", ".join(f"{k}={'défini' if k == 'description' else v}" for k, v in params.items()))
    return {"updated": entry, **now}


@router.delete("/{userid}/{entry}")
async def delete_tfa(conn_id: int, userid: str = UID, entry: str = EID, confirm: bool = Query(default=False), name: str = Query(default="", max_length=80),
                     dry_run: bool = Query(default=False), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                     adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Supprime une entrée. Retirer la dernière entrée active DÉSACTIVE la double authentification du compte (baisse de sécurité, jamais un verrouillage)."""
    user, s = adm
    c = Ctx(db, user, conn_id, "tfa-delete", f"{userid}/{entry}")
    _protected(c, db, conn_id, s, userid)
    entries = await _entries(c, db, factory, conn_id, s, userid)
    cur = next((e for e in entries if e["id"] == entry), None)
    if cur is None:
        c.refuse("Entrée inconnue", status.HTTP_404_NOT_FOUND)
    turns_off = cur["enabled"] and enabled_count(entries) == 1
    if dry_run:
        return {"dry_run": True, "locks": {"turns_off": turns_off}}
    c.confirmed(confirm, name, userid)
    await _call(c, db, factory, conn_id, s, "delete", f"/access/tfa/{userid}/{entry}")
    if any(e["id"] == entry for e in await _entries(c, db, factory, conn_id, s, userid)):
        c.refuse("Proxmox n'a pas supprimé l'entrée", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"supprimée ({cur['type']}{', double authentification désactivée' if turns_off else ''})")
    return {"deleted": entry}
