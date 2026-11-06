"""Migration d'une VM ou d'un LXC vers un autre nœud du cluster."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..vmspec import STORAGE
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["migrate"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}/migrate"


class MigrateBody(BaseModel):
    target_node: str
    online: bool = Field(default=False, description="VM en marche : migration à chaud. LXC en marche : arrêt, migration, redémarrage.")
    with_local_disks: bool = Field(default=False, description="VM en marche : copier aussi les disques locaux")
    target_storage: str | None = Field(default=None, description="Stockage de destination pour les disques locaux")
    confirm: bool = False

    @field_validator("target_node")
    @classmethod
    def _node(cls, v):
        if not re.match(NODE, v):
            raise ValueError("Nom de nœud invalide")
        return v

    @field_validator("target_storage")
    @classmethod
    def _storage(cls, v):
        if v is not None and not STORAGE.match(v):
            raise ValueError("Nom de stockage invalide")
        return v


def shape_preflight(raw: dict | None, source: str, online_nodes: list[str]) -> dict:
    """Vérifications préalables de Proxmox, ou repli (tous les autres nœuds en ligne) si elles sont indisponibles."""
    if not isinstance(raw, dict) or "allowed_nodes" not in raw:
        return {"preflight": False, "running": None, "allowed_nodes": [n for n in online_nodes if n != source],
                "not_allowed": [], "local_disks": [], "local_resources": []}
    def reasons_of(v: dict | None) -> list[str]:
        v = v or {}
        out = [f"stockage indisponible : {st}" for st in v.get("unavailable_storages", []) or []]
        if v.get("unavailable_resources"):
            out.append("ressources locales non transférables")
        out += [f"{k}" for k, val in v.items() if val and k not in ("unavailable_storages", "unavailable_resources")]
        return out

    allowed = [n for n in raw.get("allowed_nodes", []) if n != source]
    refused = {n: reasons_of(v) for n, v in sorted((raw.get("not_allowed_nodes") or {}).items())}
    # Un nœud à la fois autorisé et « refusé » sans aucune raison n'est pas refusé : on ne garde que les refus motivés.
    allowed = sorted(n for n in allowed if not refused.get(n))
    not_allowed = [{"node": n, "reasons": r} for n, r in refused.items() if r and n != source]
    return {"preflight": True, "running": bool(raw.get("running")),
            "allowed_nodes": allowed, "not_allowed": not_allowed,
            "local_disks": [{"volid": d.get("volid"), "size": d.get("size")} for d in raw.get("local_disks", []) if not d.get("cdrom")],
            "local_resources": list(raw.get("local_resources", []))}


@router.get(BASE)
async def preflight(conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                    vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                    factory: Factory = Depends(get_client_factory)):
    """Nœuds possibles, disques locaux et ressources qui bloquent la migration."""
    try:
        raw = await _px(db, factory, conn_id, "get", f"/nodes/{node}/{gtype}/{vmid}/migrate")
    except HTTPException:
        raw = None                                  # vérifications indisponibles (version, droits) : repli
    nodes = await _px(db, factory, conn_id, "get", "/nodes")
    return shape_preflight(raw, node, [n["node"] for n in nodes if n.get("status") == "online"])


@router.post(BASE, status_code=status.HTTP_202_ACCEPTED)
async def migrate(body: MigrateBody, conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(),
                  vmid: int = Path(ge=100, le=999999999), db: Session = Depends(get_db),
                  factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Migre la machine. Une machine en marche exige `confirm` (coupure ou migration à chaud)."""
    target = f"{gtype}/{vmid}@{node}"

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="migrate", target=target, status=st, detail=detail, upid=upid)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method, path, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    if body.target_node == node:
        refuse("La machine est déjà sur ce nœud", 422)
    if body.target_storage and gtype == "lxc":
        refuse("Le stockage de destination ne s'applique qu'aux VM", 422)
    if body.with_local_disks and gtype == "lxc":
        refuse("L'option « disques locaux » ne concerne que les VM", 422)
    current = await px("get", f"/nodes/{node}/{gtype}/{vmid}/status/current")
    running = (current or {}).get("status") == "running"
    if running and not body.confirm:
        refuse("La machine est en marche : la migration la coupe (LXC) ou la déplace à chaud (VM). Renvoie la requête avec {\"confirm\": true}", 400)
    if running and gtype == "qemu" and not body.online:
        refuse("Une VM en marche ne peut migrer qu'à chaud (online=true) ; éteins-la pour une migration à froid", 422)

    params: dict = {"target": body.target_node}
    if running and gtype == "qemu":
        params["online"] = 1
        if body.with_local_disks:
            params["with-local-disks"] = 1
    if running and gtype == "lxc":
        params["restart"] = 1
    if body.target_storage:
        params["targetstorage"] = body.target_storage
    upid = await px("post", f"/nodes/{node}/{gtype}/{vmid}/migrate", **params)
    log("started", f"-> {body.target_node}" + (" · à chaud" if params.get("online") else " · avec redémarrage" if params.get("restart") else "")
        + (f" · stockage {body.target_storage}" if body.target_storage else ""), upid=upid if isinstance(upid, str) else None)
    return {"upid": upid, "node": node, "target_node": body.target_node}
