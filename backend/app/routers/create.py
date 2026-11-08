"""Création de machines virtuelles."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..lxcspec import LxcCreate, build_lxc_params
from ..models import AdminUser
from ..vmspec import VmCreate, build_params
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["create"], dependencies=[Depends(current_user)])


@router.get("/api/connections/{conn_id}/nextid")
async def next_id(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return {"vmid": int(await _px(db, factory, conn_id, "get", "/cluster/nextid"))}


@router.get("/api/connections/{conn_id}/pools")
async def pools(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    data = await _px(db, factory, conn_id, "get", "/pools")
    return sorted(({"poolid": p["poolid"], "comment": p.get("comment")} for p in data or [] if p.get("poolid")),
                  key=lambda p: p["poolid"])


@router.get("/api/connections/{conn_id}/nodes/{node}/storages")
async def storages(conn_id: int, node: str = Path(pattern=NODE),
                   content: Literal["images", "rootdir", "iso", "vztmpl", "backup"] = Query(default="images"),
                   db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Stockages du nœud qui acceptent ce type de contenu (par défaut : disques de VM)."""
    data = await _px(db, factory, conn_id, "get", f"/nodes/{node}/storage", content=content)
    return sorted(({"storage": s["storage"], "type": s.get("type"), "avail": s.get("avail"), "total": s.get("total"),
                    "shared": bool(s.get("shared")), "active": bool(s.get("active", 1))}
                   for s in data or [] if s.get("storage")), key=lambda s: s["storage"])


VMID_TAKEN = "Cet identifiant est déjà utilisé"
UNREADABLE = "Impossible de vérifier si cet identifiant est libre : la liste des machines est illisible"


async def vmid_state(px, vmid: int) -> str | None:
    """Pré-contrôle d'un identifiant choisi à la main : `None` s'il est libre, sinon le message de refus. Proxmox répondrait 500
    « already exists » (traduit en 502) : on refuse avant d'appeler la création, sans citer la valeur saisie."""
    rows = await px("get", "/cluster/resources", type="vm")
    if rows is not None and not isinstance(rows, list):
        return UNREADABLE
    for r in rows or []:
        if isinstance(r, dict) and str(r.get("vmid")) == str(vmid):
            return VMID_TAKEN
    return None


@router.post("/api/connections/{conn_id}/nodes/{node}/qemu", status_code=status.HTTP_202_ACCEPTED)
async def create_vm(body: VmCreate, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                    factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Crée une VM. Renvoie l'UPID de la tâche et le vmid retenu."""
    action, target = "create-vm", f"qemu/{body.vmid or '?'}@{node}"

    def fail(msg: str, code: int):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                     status="error", detail=msg)
        raise HTTPException(code, msg)

    async def px(method: str, path: str, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target,
                         status="error", detail=str(e.detail))
            raise

    vmid = body.vmid if body.vmid is not None else int(await px("get", "/cluster/nextid"))
    target = f"qemu/{vmid}@{node}"
    if body.vmid is not None and (problem := await vmid_state(px, vmid)):
        fail(problem, 409 if problem == VMID_TAKEN else 502)
    try:
        params = build_params(body, vmid)
    except ValueError as e:
        fail(str(e), 422)
    upid = await px("post", f"/nodes/{node}/qemu", **params)
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="started",
                 upid=upid if isinstance(upid, str) else None,
                 detail=f"{body.name}" + (f" · pool {body.pool}" if body.pool else ""))
    return {"upid": upid, "node": node, "vmid": vmid}


@router.post("/api/connections/{conn_id}/nodes/{node}/lxc", status_code=status.HTTP_202_ACCEPTED)
async def create_lxc(body: LxcCreate, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Crée un conteneur LXC à partir d'un modèle déjà présent. Le mot de passe n'est jamais journalisé."""
    action, target = "create-lxc", f"lxc/{body.vmid or '?'}@{node}"

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status=st, detail=detail, upid=upid)

    async def px(method: str, path: str, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    vmid = body.vmid if body.vmid is not None else int(await px("get", "/cluster/nextid"))
    target = f"lxc/{vmid}@{node}"
    if body.vmid is not None and (problem := await vmid_state(px, vmid)):
        log("error", problem)
        raise HTTPException(409 if problem == VMID_TAKEN else 502, problem)
    try:
        params = build_lxc_params(body, vmid)
    except ValueError as e:
        log("error", str(e))
        raise HTTPException(422, str(e))
    upid = await px("post", f"/nodes/{node}/lxc", **params)
    access = [x for x, on in (("mot de passe", body.password), ("clé SSH", body.ssh_public_keys)) if on]
    log("started", f"{body.hostname} · {body.template.split('/')[-1]}" + (f" · pool {body.pool}" if body.pool else "")
        + (f" · accès : {', '.join(access)}" if access else " · aucun accès configuré")
        + ("" if body.unprivileged else " · PRIVILÉGIÉ"), upid=upid if isinstance(upid, str) else None)
    return {"upid": upid, "node": node, "vmid": vmid}
