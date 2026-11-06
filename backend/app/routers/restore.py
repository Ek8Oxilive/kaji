"""Restauration d'une sauvegarde vers une NOUVELLE machine. Ne remplace jamais une machine existante."""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..restorespec import RestoreBody, parse_volid, restore_request
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["restore"], dependencies=[Depends(current_user)])


@router.post("/nodes/{node}/restore", status_code=status.HTTP_202_ACCEPTED)
async def restore_backup(body: RestoreBody, conn_id: int, node: str = Path(pattern=NODE),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                         user: AdminUser = Depends(current_user)):
    """Restaure une sauvegarde sous un NOUVEL identifiant et renvoie l'UPID. Refuse tout identifiant déjà utilisé
    (VM ou conteneur, sur n'importe quel nœud) : l'option `force` de Proxmox n'est jamais exposée ni envoyée.
    Le type (VM ou conteneur) est lu dans le nom du fichier. La machine restaurée n'est pas démarrée."""
    bstorage, bfile, gtype = parse_volid(body.volid)
    target = f"{gtype}/{body.vmid or '?'}@{node}"
    base = f"depuis {body.volid} · stockage={body.storage}" + (f" · pool={body.pool}" if body.pool else "")

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="backup-restore", target=target,
                     status=st, detail=detail, upid=upid)

    def refuse(msg, code):
        log("error", f"{base} · {msg}")
        raise HTTPException(code, msg)

    async def px(method, path, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", f"{base} · {e.detail}")
            raise

    listing = await px("get", f"/nodes/{node}/storage/{bstorage}/content", content="backup")
    found = next((v for v in listing if isinstance(v, dict) and v.get("volid") == body.volid), None) \
        if isinstance(listing, list) else None
    if found is None:
        refuse("Sauvegarde introuvable sur ce stockage", 404)
    if found.get("content") not in (None, "backup"):
        refuse("Ce volume n'est pas une sauvegarde", 409)

    if body.vmid is None:
        raw = await px("get", "/cluster/nextid")
        try:
            vmid = int(raw)
        except (TypeError, ValueError):
            refuse("Réponse inattendue de Proxmox pour le prochain identifiant libre", 502)
        target = f"{gtype}/{vmid}@{node}"
    else:
        vmid = body.vmid
        resources = await px("get", "/cluster/resources", type="vm")
        used = {r.get("vmid") for r in resources if isinstance(r, dict)} if isinstance(resources, list) else set()
        if vmid in used or str(vmid) in {str(u) for u in used}:
            refuse(f"L'identifiant {vmid} est déjà utilisé : la restauration ne remplace jamais une machine existante",
                   409)

    _, params = restore_request(body, vmid)
    upid = await px("post", f"/nodes/{node}/{gtype}", **params)
    log("started", f"{base} · nouvelle machine {vmid}", upid=upid if isinstance(upid, str) else None)
    return {"upid": upid, "node": node, "vmid": vmid, "type": gtype, "archive": bfile}
