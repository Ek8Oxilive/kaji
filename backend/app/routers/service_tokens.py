"""Jeton de SERVICE d'une connexion (lot #441, option A du cadrage) : celui que le planificateur d'actions et les alertes utilisent quand personne n'est connecté.

Pas le jeton d'un utilisateur, et **jamais Administrator** : à l'enregistrement, Kaji interroge Proxmox AVEC ce jeton (`GET /access/permissions`) et **refuse** tout jeton qui détient un
privilège hors de la liste dont ces deux fonctions ont besoin (`ALLOWED_PRIVILEGES`), ou dont les droits ne peuvent pas être lus (pas de vérification, pas de jeton).
Lecture : tous les rôles ; écriture : administrateurs (politique par défaut de `app/roles.py`). Même clé séparée, mêmes contrôles d'expiration et de privilèges séparés qu'un jeton
personnel (`routers/user_tokens.py::validate_token`). Jamais de secret renvoyé, journalisé ni recopié dans une erreur.
"""
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, tokenkey
from ..config import get_settings
from ..db import get_db
from ..deps import Factory, get_base_client_factory
from ..models import AdminUser, Connection, ServiceToken
from .auth import current_user
from .cluster import http_error
from .connections import _get_or_404
from .user_tokens import TokenIn, _aware, _key_problem, _refuse, _state, validate_token

router = APIRouter(prefix="/api/connections/{conn_id}/service-token", tags=["service-token"], dependencies=[Depends(current_user)])

# Ce dont le planificateur (démarrer, arrêter, redémarrer, snapshot) et les alertes (ressources, nœuds, tâches) ont besoin, et RIEN d'autre.
ALLOWED_PRIVILEGES = frozenset({"Sys.Audit", "VM.Audit", "VM.PowerMgmt", "VM.Snapshot", "Datastore.Audit", "Pool.Audit"})
MINIMUM_PRIVILEGES = frozenset({"Sys.Audit", "VM.Audit"})            # sans eux, rien ne marche : signalé (pas refusé)
ACTION = "service-token-set"


def _view(conn: Connection, t: ServiceToken | None, lacks: list[str] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    out = {"conn_id": conn.id, "name": conn.name, "state": _state(t, now), "pve_user": None, "token_id": None, "expires_at": None, "days_left": None, "verified": None, "created_by": None, "lacks": lacks}
    if t is not None:
        out.update(pve_user=t.pve_user, token_id=t.token_id, expires_at=_aware(t.expires_at).isoformat(), verified=t.verified, created_by=t.created_by,
                   days_left=max(0, (_aware(t.expires_at) - now).days))
    return out


@router.get("")
def get_service_token(conn_id: int = Path(ge=1), db: Session = Depends(get_db)):
    conn = _get_or_404(db, conn_id)
    s = get_settings()
    problem = _key_problem()
    row = db.scalars(select(ServiceToken).where(ServiceToken.conn_id == conn_id)).first()
    return {"enabled": problem is None, "problem": problem, "required": s.kaji_require_service_token, "max_days": s.kaji_service_token_max_days,
            "allowed_privileges": sorted(ALLOWED_PRIVILEGES), "token": _view(conn, row)}


async def _privileges(base: Factory, conn: Connection, body: TokenIn) -> set[str] | None:
    """Tous les privilèges que Proxmox accorde à ce jeton (tous chemins), lus AVEC le jeton. `None` si Proxmox ne les dit pas ou répond de façon inattendue."""
    client = base(host=conn.host, port=conn.port, user=body.pve_user, token_id=body.token_id, token_secret=body.secret.get_secret_value(),
                  verify_ssl=conn.verify_ssl, pinned_cert=conn.tls_cert_pem or None)
    try:
        data = await client.get("/access/permissions")
    except httpx.HTTPError:
        return None
    finally:
        await client.aclose()
    if not isinstance(data, dict) or not data:
        return None
    privs: set[str] = set()
    for path, granted in data.items():
        if not isinstance(path, str) or not isinstance(granted, dict):
            return None
        privs |= {p for p in granted if isinstance(p, str)}
    return privs


@router.put("")
async def set_service_token(body: TokenIn, conn_id: int = Path(ge=1), db: Session = Depends(get_db), user: AdminUser = Depends(current_user),
                            base: Factory = Depends(get_base_client_factory)):
    conn = _get_or_404(db, conn_id)
    target = f"{body.pve_user}!{body.token_id}"
    problem = _key_problem()
    if problem:
        _refuse(db, user, conn_id, target, problem, status.HTTP_409_CONFLICT, ACTION)
    s = get_settings()
    expires, verified = await validate_token(db, user, conn, body, base, s.kaji_service_token_max_days, action=ACTION, limit_name="KAJI_SERVICE_TOKEN_MAX_DAYS")
    privs = await _privileges(base, conn, body)
    if privs is None:
        _refuse(db, user, conn_id, target, "Proxmox ne dit pas quels droits a ce jeton : impossible de vérifier qu'il est limité, donc refusé (un jeton de service ne s'enregistre jamais « sur parole »).", action=ACTION)
    extra = sorted(privs - ALLOWED_PRIVILEGES)
    if extra:
        shown = ", ".join(extra[:12]) + (f" (+{len(extra) - 12})" if len(extra) > 12 else "")
        _refuse(db, user, conn_id, target, f"Ce jeton a des droits dont le planificateur et les alertes n'ont pas besoin : {shown}. "
                "Un jeton de service n'a que ces droits-là, jamais Administrator : retire-lui le reste dans Proxmox (Permissions).", action=ACTION)
    enc = tokenkey.encrypt(body.secret.get_secret_value())
    row = db.scalars(select(ServiceToken).where(ServiceToken.conn_id == conn_id)).first()
    if row is None:
        row = ServiceToken(conn_id=conn_id)
        db.add(row)
    row.pve_user, row.token_id, row.secret_enc, row.expires_at = body.pve_user, body.token_id, enc, expires
    row.verified, row.refused_at, row.created_by, row.created_at = verified, None, user.username, datetime.now(timezone.utc)
    db.commit()
    audit.record(db, username=user.username, connection_id=conn_id, action=ACTION, target=target, status="started",
                 detail=f"expire le {expires.date().isoformat()}, contrôlé par Proxmox : {'oui' if verified else 'non (déclaré)'}, droits limités vérifiés")
    return _view(conn, row, sorted(MINIMUM_PRIVILEGES - privs))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def remove_service_token(conn_id: int = Path(ge=1), db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    _get_or_404(db, conn_id)
    row = db.scalars(select(ServiceToken).where(ServiceToken.conn_id == conn_id)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun jeton de service pour cette connexion")
    target = f"{row.pve_user}!{row.token_id}"
    db.delete(row)
    db.commit()
    audit.record(db, username=user.username, connection_id=conn_id, action="service-token-removed", target=target, status="started",
                 detail="jeton de service retiré de Kaji (il reste valable chez Proxmox) : le planificateur et les alertes reprennent le jeton partagé, sauf KAJI_REQUIRE_SERVICE_TOKEN")
