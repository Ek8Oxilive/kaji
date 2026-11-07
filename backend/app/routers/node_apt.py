"""Rafraîchir la liste des paquets d'un nœud (`apt update`, droit `Sys.Modify`).

Seule la **mise à jour de l'index** passe par l'API de Proxmox. L'installation des mises à jour (`apt dist-upgrade`) n'a pas
d'équivalent dans l'API : Proxmox la lance dans un terminal. Kaji ne l'exécute donc pas : il propose la commande à lancer dans la
console du nœud.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["node-apt"], dependencies=[Depends(current_user)])


@router.post("/nodes/{node}/apt/update", status_code=status.HTTP_202_ACCEPTED)
async def apt_refresh(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Lance `apt update` sur le nœud (tâche Proxmox). Sans effet sur les paquets installés : aucune confirmation n'est requise."""
    target = f"node/{node}"
    try:
        # aucun paramètre : ni `notify` (envoi de courriel) ni `quiet`, qui n'ont pas lieu d'être ici
        upid = await _px(db, factory, conn_id, "post", f"/nodes/{node}/apt/update")
    except HTTPException as e:
        audit.record(db, username=user.username, connection_id=conn_id, action="apt-refresh", target=target, status="error", detail=str(e.detail))
        raise
    audit.record(db, username=user.username, connection_id=conn_id, action="apt-refresh", target=target, status="started",
                 upid=upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "node": node}
