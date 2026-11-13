"""Realms d'authentification (Datacenter → Permissions → Realms) : lire un realm, créer, modifier, supprimer, synchroniser (LDAP / AD). Lot #379.

Les écritures passent par la SESSION ADMINISTRATEUR (le jeton de Kaji n'a pas `Realm.Allocate`), comme les utilisateurs et les ACL. Validation et liste blanche par type : `app/realmspec.py`.
Un realm mal réglé peut verrouiller la connexion : tout est verrouillé côté serveur (identifiant retapé, `dry_run`, phrase `COUPURE POSSIBLE` quand des comptes peuvent perdre leur accès).
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..accessspec import shape_users
from ..adminsession import AdminSession
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..realmspec import BUILTIN, PHRASE, REALM, SECRETS, WIRE, RealmCreate, RealmSync, RealmUpdate, build_params, digest_of, shape_realm, touched_login_fields
from .admin_session import admin_call, require_admin
from .auth import current_user
from .cluster import Factory, _px
from .connections import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}/access", tags=["realms"])
RID = Path(pattern=REALM.pattern)
SECRET_WIRE = {WIRE[k] for k in SECRETS}


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
            self.refuse("Écriture d'un realm : renvoie la requête avec confirm=true et l'identifiant du realm retapé", status.HTTP_400_BAD_REQUEST)
        if typed != expected:
            self.refuse("L'identifiant retapé ne correspond pas : écriture refusée", status.HTTP_400_BAD_REQUEST)

    def cut_lock(self, needed: bool, ack: bool, phrase: str | None, why: str):
        if needed and not (ack and phrase == PHRASE):
            self.refuse(f"Coupure possible : {why}. Renvoie la requête avec acknowledge_cut_access=true et phrase=\"{PHRASE}\"", status.HTTP_409_CONFLICT)


def _masked(params: dict) -> dict:
    return {k: ("défini" if k in SECRET_WIRE else v) for k, v in params.items()}


async def _call(c: Ctx, db, factory, conn_id, s, method, path, **params):
    try:
        return await admin_call(db, factory, conn_id, s, method, path, **params)
    except HTTPException as e:
        c.log("error", str(e.detail))
        raise


async def _realms(c: Ctx, db, factory, conn_id, s) -> dict[str, dict]:
    raw = await _call(c, db, factory, conn_id, s, "get", "/access/domains")
    return {r["realm"]: r for r in (raw if isinstance(raw, list) else []) if isinstance(r, dict) and isinstance(r.get("realm"), str)}


async def _users_in(c: Ctx, db, factory, conn_id, s, realm: str) -> int:
    return sum(1 for u in shape_users(await _call(c, db, factory, conn_id, s, "get", "/access/users")) if u["realm"] == realm)


def _own_realms(db, conn_id, s) -> set[str]:
    """Realms qui portent le compte de Kaji ou celui de la session administrateur : jamais supprimés."""
    return {u.rpartition("@")[2] for u in (_get_or_404(db, conn_id).user, s.user) if "@" in u}


def _norm(v) -> str:
    return ("1" if v else "0") if isinstance(v, bool) else str(v).strip()


def _applied(after: dict, params: dict) -> bool:
    for wire, want in params.items():
        if wire in SECRET_WIRE:
            continue                                                    # Proxmox ne relit pas les secrets
        got = after.get(wire)
        if wire == "sync-defaults-options":
            if set(str(got or "").split(",")) != set(want.split(",")):
                return False
        elif _norm(got).rstrip("\n").lower() != want.rstrip("\n").lower():
            return False
    return True


# ---------------------------------------------------------------- lecture d'un realm (jeton de Kaji : Sys.Audit suffit)
@router.get("/realms/{realm}")
async def get_realm(conn_id: int, realm: str = RID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), _u: AdminUser = Depends(current_user)):
    """Configuration d'un realm, sans aucun secret, et `digest` de Kaji (à renvoyer avec une modification)."""
    raw = await _px(db, factory, conn_id, "get", f"/access/domains/{realm}")
    d = shape_realm(raw, realm)
    if d is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Configuration du realm illisible")
    return {**d, "digest": digest_of(d)}


# ---------------------------------------------------------------- création
@router.post("/realms", status_code=status.HTTP_201_CREATED)
async def create_realm(body: RealmCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Crée un realm LDAP, Active Directory ou OpenID. Mot de passe et clé : écriture seule."""
    user, s = adm
    c = Ctx(db, user, conn_id, "realm-create", body.realm)
    try:
        params, _ = build_params(body.type, body, [], creating=True)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.realm in await _realms(c, db, factory, conn_id, s):
        c.refuse("Ce realm existe déjà", status.HTTP_409_CONFLICT)
    if body.dry_run:
        return {"dry_run": True, "params": _masked({"realm": body.realm, "type": body.type, **params})}
    c.confirmed(body.confirm, body.type_name, body.realm)
    await _call(c, db, factory, conn_id, s, "post", "/access/domains", realm=body.realm, type=body.type, **params)
    made = await _realms(c, db, factory, conn_id, s)
    if made.get(body.realm, {}).get("type") != body.type:
        c.refuse("Proxmox n'a pas créé le realm", status.HTTP_502_BAD_GATEWAY)
    after = await _call(c, db, factory, conn_id, s, "get", f"/access/domains/{body.realm}")
    if not isinstance(after, dict) or not _applied(after, params):
        c.refuse("Proxmox n'a pas appliqué tous les réglages du realm", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"créé ({body.type}) : " + ", ".join(f"{k}={'défini' if k in SECRET_WIRE else v}" for k, v in sorted(params.items())))
    d = shape_realm(after, body.realm, body.type) or {}
    return {"created": body.realm, **d, "digest": digest_of(d)}


# ---------------------------------------------------------------- modification
@router.put("/realms/{realm}")
async def update_realm(body: RealmUpdate, conn_id: int, realm: str = RID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                       adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Modifie un realm (ou retire des réglages avec `clear`). `pam` et `pve` : commentaire et realm par défaut seulement."""
    user, s = adm
    c = Ctx(db, user, conn_id, "realm-update", realm)
    known = await _realms(c, db, factory, conn_id, s)
    if realm not in known:
        c.refuse("Realm inconnu", status.HTTP_404_NOT_FOUND)
    typ = known[realm].get("type")
    if typ not in ("ldap", "ad", "openid", *BUILTIN):
        c.refuse("Type de realm non géré", status.HTTP_422_UNPROCESSABLE_ENTITY)
    try:
        params, delete = build_params(typ, body, list(body.clear), creating=False)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    raw = await _call(c, db, factory, conn_id, s, "get", f"/access/domains/{realm}")
    cur = shape_realm(raw, realm, typ)
    if cur is None:
        c.refuse("Configuration du realm illisible", status.HTTP_502_BAD_GATEWAY)
    if body.digest is not None and body.digest != digest_of(cur):
        c.refuse("Le realm a changé depuis ta lecture (digest périmé) : recharge avant de modifier", status.HTTP_409_CONFLICT)
    touched = touched_login_fields(body, list(body.clear))
    n = await _users_in(c, db, factory, conn_id, s, realm) if touched else 0
    if body.dry_run:
        return {"dry_run": True, "params": _masked(params), "remove": delete, "locks": {"login_fields": touched, "users": n, "cut": bool(touched and n)}}
    c.confirmed(body.confirm, body.type_name, realm)
    c.cut_lock(bool(touched and n), body.acknowledge_cut_access, body.phrase, f"{n} compte(s) de ce realm peuvent ne plus pouvoir se connecter ({', '.join(touched)})")
    send = dict(params)
    if delete:
        send["delete"] = ",".join(delete)
    await _call(c, db, factory, conn_id, s, "put", f"/access/domains/{realm}", **send)
    after = await _call(c, db, factory, conn_id, s, "get", f"/access/domains/{realm}")
    if not isinstance(after, dict) or not _applied(after, params) or any(after.get(w) not in (None, "") for w in delete if w not in SECRET_WIRE):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", ", ".join(f"{k}={'défini' if k in SECRET_WIRE else v}" for k, v in sorted(params.items())) + (f" ; retiré : {','.join(delete)}" if delete else ""))
    d = shape_realm(after, realm, typ) or {}
    return {"updated": realm, **d, "digest": digest_of(d)}


# ---------------------------------------------------------------- suppression
@router.delete("/realms/{realm}")
async def delete_realm(conn_id: int, realm: str = RID, confirm: bool = Query(default=False), name: str = Query(default="", max_length=40),
                       acknowledge_cut_access: bool = Query(default=False), phrase: str | None = Query(default=None, max_length=40), dry_run: bool = Query(default=False),
                       db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Supprime un realm. Refusé pour `pam`, `pve` et le realm qui porte le compte de Kaji ou de la session administrateur."""
    user, s = adm
    c = Ctx(db, user, conn_id, "realm-delete", realm)
    if realm in BUILTIN:
        c.refuse("Realm intégré : il ne se supprime pas", status.HTTP_403_FORBIDDEN)
    if realm in _own_realms(db, conn_id, s):
        c.refuse("Ce realm porte le compte de Kaji ou celui de la session administrateur : le supprimer couperait Kaji", status.HTTP_403_FORBIDDEN)
    known = await _realms(c, db, factory, conn_id, s)
    if realm not in known:
        c.refuse("Realm inconnu", status.HTTP_404_NOT_FOUND)
    n = await _users_in(c, db, factory, conn_id, s, realm)
    is_default = _norm(known[realm].get("default")) in ("1", "true")
    if dry_run:
        return {"dry_run": True, "locks": {"users": n, "default": is_default, "cut": bool(n or is_default)}}
    c.confirmed(confirm, name, realm)
    c.cut_lock(bool(n or is_default), acknowledge_cut_access, phrase, f"{n} compte(s) perdraient leur connexion" + (" et c'est le realm par défaut" if is_default else ""))
    await _call(c, db, factory, conn_id, s, "delete", f"/access/domains/{realm}")
    if realm in await _realms(c, db, factory, conn_id, s):
        c.refuse("Proxmox n'a pas supprimé le realm", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"supprimé ({n} compte(s) concerné(s))")
    return {"deleted": realm}


# ---------------------------------------------------------------- synchronisation (LDAP / AD)
@router.post("/realms/{realm}/sync")
async def sync_realm(body: RealmSync, conn_id: int, realm: str = RID, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                     adm: tuple[AdminUser, AdminSession] = Depends(require_admin)):
    """Synchronise utilisateurs et groupes depuis l'annuaire. **Simulation par défaut** (`dry_run=true`) ; supprimer des comptes ou des droits exige la phrase."""
    user, s = adm
    c = Ctx(db, user, conn_id, "realm-sync", realm)
    known = await _realms(c, db, factory, conn_id, s)
    if realm not in known:
        c.refuse("Realm inconnu", status.HTTP_404_NOT_FOUND)
    if known[realm].get("type") not in ("ldap", "ad"):
        c.refuse("Seuls les realms LDAP et Active Directory se synchronisent", status.HTTP_422_UNPROCESSABLE_ENTITY)
    params: dict = {"dry-run": "1" if body.dry_run else "0"}
    if body.scope:
        params["scope"] = body.scope
    if body.enable_new is not None:
        params["enable-new"] = "1" if body.enable_new else "0"
    if body.remove_vanished:
        params["remove-vanished"] = ";".join(dict.fromkeys(body.remove_vanished))
    if not body.dry_run:
        c.confirmed(body.confirm, body.type_name, realm)
        c.cut_lock(bool(body.remove_vanished), body.acknowledge_cut_access, body.phrase, "la synchronisation supprimera ce qui a disparu de l'annuaire (" + ", ".join(body.remove_vanished) + ")")
    upid = await _call(c, db, factory, conn_id, s, "post", f"/access/domains/{realm}/sync", **params)
    c.log("started", ("simulation" if body.dry_run else "synchronisation") + " : " + ", ".join(f"{k}={v}" for k, v in sorted(params.items())))
    return {"upid": upid if isinstance(upid, str) else None, "dry_run": body.dry_run, "params": params}
