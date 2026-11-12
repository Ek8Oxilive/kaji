"""DNS, fichier hosts et fuseau horaire d'un nœud (droit `Sys.Modify`). Garde-fous : `nodeconf`."""
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..nodeconf import DnsBody, HostsBody, TimeBody, hosts_problem
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-config"], dependencies=[Depends(current_user)])


@router.get("/nodes/{node}/hosts")
async def read_hosts(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Contenu du fichier `hosts` et son `digest` (à renvoyer tel quel pour modifier). Lecture seule."""
    r = await _px(db, factory, conn_id, "get", f"/nodes/{node}/hosts")
    r = r if isinstance(r, dict) else {}
    data, digest = r.get("data"), r.get("digest")
    return {"content": data[:8192] if isinstance(data, str) else "", "digest": digest if isinstance(digest, str) and len(digest) == 40 else None}


STALE = "Le fichier hosts a changé depuis ta lecture (digest périmé) : recharge avant de modifier"


async def _write(db, factory, user, conn_id, action, target, check, method, path, params):
    def fail(code: int, msg: str):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    refused = check()
    if refused:
        fail(*refused)
    try:
        await _px(db, factory, conn_id, method, path, **params)
    except HTTPException as e:
        # Proxmox répond 500 « detected modified configuration » quand le `digest` est périmé : c'est un conflit (409), pas une panne
        if "detected modified configuration" in str(e.detail):
            fail(409, STALE)
        fail(e.status_code, str(e.detail))
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="ok")
    return {"ok": True}


@router.put("/nodes/{node}/dns")
async def set_dns(body: DnsBody, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                  factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    params = {"search": body.search, **{f"dns{i + 1}": s for i, s in enumerate(body.servers)}}
    return await _write(db, factory, user, conn_id, "node-dns", f"node/{node}", lambda: None if body.confirm else (400, "Confirmation requise"),
                        "put", f"/nodes/{node}/dns", params)


@router.put("/nodes/{node}/hosts")
async def set_hosts(body: HostsBody, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                    factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    def check():
        if not body.confirm:
            return 400, "Confirmation requise"
        problem = hosts_problem(body.content, node)
        return (422, problem) if problem else None
    if body.confirm and not hosts_problem(body.content, node):
        # le `digest` est relu avant d'écrire : un fichier modifié depuis la lecture donne un 409 clair (Proxmox garde aussi la course)
        try:
            current = (await read_hosts(conn_id, node, db, factory))["digest"]
        except HTTPException as e:
            audit.record(db, username=user.username, connection_id=conn_id, action="node-hosts", target=f"node/{node}", status="error", detail=str(e.detail))
            raise
        if current is not None and current != body.digest:
            audit.record(db, username=user.username, connection_id=conn_id, action="node-hosts", target=f"node/{node}", status="error", detail=STALE)
            raise HTTPException(409, STALE)
    return await _write(db, factory, user, conn_id, "node-hosts", f"node/{node}", check, "post", f"/nodes/{node}/hosts",
                        {"data": body.content, "digest": body.digest})


@router.put("/nodes/{node}/time")
async def set_timezone(body: TimeBody, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                       factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    return await _write(db, factory, user, conn_id, "node-timezone", f"node/{node}", lambda: None, "put", f"/nodes/{node}/time", {"timezone": body.timezone})
