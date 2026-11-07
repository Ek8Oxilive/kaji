"""Ceph, ÉCRITURE : initialisation (lot C5). `pveceph init` : réseaux et valeurs par défaut du cluster. L'INSTALLATION des paquets n'a pas
d'API chez Proxmox : elle se fait avec `pveceph install` dans le shell du nœud (l'interface l'explique). RIEN n'a été validé sur un vrai Ceph.
"""
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from ..cephinit import CephInit, init_params, init_risks
from ..cephspec import shape_conf_raw
from ..cephwrite import write_slot
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .ceph import _NotInstalled, _get
from .ceph_services import _Op
from .cluster import Factory

router = APIRouter(prefix="/api/connections/{conn_id}/ceph/nodes/{node}", tags=["ceph-write"], dependencies=[Depends(current_user)])


@router.post("/init", status_code=202)
async def init_ceph(body: CephInit, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                    factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Initialise Ceph (`pveceph init`) depuis ce nœud. Refusé si Ceph n'est pas installé (409), s'il a déjà une configuration (409), ou
    sans `confirm=true` (confirmation décidée par le serveur). `disable_cephx` n'existe pas ici : la sécurité de Ceph reste active."""
    base = f"initialisation : réseau={body.network}" + (f" réseau de cluster={body.cluster_network}" if body.cluster_network else "") \
           + f" size={body.size} min_size={body.min_size}"
    op = _Op(db, factory, conn_id, user, "ceph-init", f"ceph/{node}", base, node)
    with write_slot(conn_id):
        await op.node_online()
        try:
            raw = await _get(db, factory, conn_id, f"/nodes/{node}/ceph/cfg/raw")
        except _NotInstalled:
            op.refuse("Ceph n'est pas installé sur ce nœud : installe-le d'abord avec « pveceph install » (étape 1 de l'assistant)", 409)
        except HTTPException:
            raw = None                                   # pas de configuration lisible : cas attendu AVANT l'initialisation (hypothèse)
        if raw is not None and shape_conf_raw(raw)["text"].strip():
            op.refuse("Ceph est déjà initialisé : une configuration existe", 409)
        op.confirm(body.confirm, init_risks(body))
        res = await op.fire(f"/nodes/{node}/ceph/init", **init_params(body))
        return {**res, "initialized": True}
