"""Configuration des stockages Proxmox : lire, ajouter, modifier, supprimer (la configuration, jamais les données du disque)."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import Field
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..storageconf import (DIGEST, SECRETS, StorageFields, StorageType, WIRE, check, reset_keys, shape_config)
from ..vmspec import STORAGE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/storage-config", tags=["storage-config"],
                   dependencies=[Depends(current_user)])
META = {"storage", "type", "reset", "digest", "confirm"}


class StorageCreate(StorageFields):
    storage: str = Field(pattern=STORAGE.pattern)
    type: StorageType


class StorageUpdate(StorageFields):
    reset: list[str] = Field(default_factory=list, max_length=10, description="Réglages à retirer (nodes, options, prune_backups…)")
    digest: str | None = Field(default=None, pattern=DIGEST.pattern, description="Refuse si la configuration a changé entre-temps")


class Ctx:
    """Appels Proxmox et audit d'une opération : tout est journalisé, y compris les refus."""

    def __init__(self, db, factory, user, conn_id, action, target):
        self.db, self.factory, self.user, self.conn_id, self.action, self.target = db, factory, user, conn_id, action, target

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action,
                     target=self.target, status=st, detail=detail)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method, path, /, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise

    async def current(self):
        """Configuration actuelle du stockage (relue chez Proxmox), ou refus 404."""
        rows = await self.px("get", "/storage")
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("storage") == self.target:
                return r
        self.refuse("Stockage inconnu", 404)


def _detail(params: dict[str, str]) -> str:
    """Résumé pour l'audit : les secrets ne sont jamais écrits, seulement « défini »."""
    wire_secrets = {WIRE.get(s, s) for s in SECRETS}
    return ", ".join(f"{k}=défini" if k in wire_secrets else f"{k}={v}" for k, v in sorted(params.items()))[:480]


@router.get("")
async def list_configs(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    rows = await _px(db, factory, conn_id, "get", "/storage")
    return [c for c in (shape_config(r) for r in (rows if isinstance(rows, list) else [])) if c]


@router.get("/{storage}")
async def get_config(conn_id: int, storage: str = Path(pattern=STORAGE.pattern), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory)):
    rows = await _px(db, factory, conn_id, "get", "/storage")
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("storage") == storage:
            cfg = shape_config(r)
            if cfg:
                return cfg
    raise HTTPException(404, "Stockage inconnu")


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_storage(body: StorageCreate, conn_id: int, db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Ajoute un stockage. Ne modifie aucune donnée existante ; n'importe quel champ hors de la liste du type est refusé."""
    c = Ctx(db, factory, user, conn_id, "storage-add", body.storage)
    sent = body.model_fields_set - META
    try:
        params = check(body.type, body, creating=True, sent=sent)
    except ValueError as e:
        c.refuse(str(e), 422)
    rows = await c.px("get", "/storage")
    if any(isinstance(r, dict) and r.get("storage") == body.storage for r in (rows if isinstance(rows, list) else [])):
        c.refuse("Un stockage porte déjà ce nom", 409)
    await c.px("post", "/storage", storage=body.storage, type=body.type, **params)
    c.log("started", f"{body.type}: {_detail(params)}")
    return {"storage": body.storage, "type": body.type}


@router.put("/{storage}")
async def update_storage(body: StorageUpdate, conn_id: int, storage: str = Path(pattern=STORAGE.pattern),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                         user: AdminUser = Depends(current_user)):
    """Modifie un stockage existant (le type et les champs de création ne changent pas)."""
    c = Ctx(db, factory, user, conn_id, "storage-edit", storage)
    cur = await c.current()
    stype = cur.get("type")
    sent = body.model_fields_set - META
    try:
        params = check(stype, body, creating=False, sent=sent)
        delete = reset_keys(stype, body.reset) if body.reset else None
    except ValueError as e:
        c.refuse(str(e), 422)
    if delete and {WIRE.get(k, k) for k in delete.split(",")} & set(params):
        c.refuse("Un même réglage ne peut pas être modifié et retiré à la fois", 422)
    if not params and not delete:
        c.refuse("Aucune modification demandée", 422)
    extra = {"delete": delete} if delete else {}
    if body.digest:
        extra["digest"] = body.digest
    await c.px("put", f"/storage/{storage}", **params, **extra)
    c.log("started", _detail(params) + (f"; retiré : {delete}" if delete else ""))
    return {"storage": storage, "type": stype}


@router.delete("/{storage}")
async def delete_storage(conn_id: int, storage: str = Path(pattern=STORAGE.pattern), confirm: bool = Query(default=False),
                         name: str = Query(default="", max_length=60), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Retire le stockage de la configuration. Les fichiers restent sur le disque, mais les machines qui l'utilisent ne
    trouveront plus leurs disques. Exige confirm=true et le nom exact du stockage."""
    c = Ctx(db, factory, user, conn_id, "storage-delete", storage)
    if not confirm:
        c.refuse("Suppression : renvoie la requête avec ?confirm=true et le nom du stockage (?name=)", 400)
    if name != storage:
        c.refuse("Le nom du stockage ne correspond pas : suppression refusée", 400)
    cur = await c.current()
    await c.px("delete", f"/storage/{storage}")
    c.log("started", f"{cur.get('type')} retiré de la configuration")
    return {"deleted": storage}
