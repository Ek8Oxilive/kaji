"""Réseau d'un nœud et pare-feu (LECTURE SEULE). Les écritures sont à risque élevé : banc d'essai imbriqué d'abord (`docs/m7-reseau-firewall.md`)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..networkspec import (NAME, shape_aliases, shape_ipset_entries, shape_named, shape_network, shape_options, shape_rules)
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px, _px_get

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["network"], dependencies=[Depends(current_user)])
NAMED = Path(pattern=NAME.pattern)                    # déjà ancré (^…$)


async def _part(coro, shape):
    """Une partie du pare-feu qui ne répond pas (droit manquant, fonction absente) ne casse pas les autres : elle porte son erreur."""
    try:
        return shape(await coro)
    except HTTPException as e:
        return {"error": str(e.detail)}


@router.get("/nodes/{node}/network")
async def network(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Interfaces du nœud (bridges, bonds, VLAN…) et **modifications en attente** (`changes`, le diff texte de Proxmox). Lecture seule."""
    return shape_network(await _px(db, factory, conn_id, "get_envelope", f"/nodes/{node}/network"))


@router.get("/firewall/cluster")
async def firewall_cluster(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Pare-feu du datacenter : options, règles, alias, IPSets, groupes de sécurité. Chaque partie porte sa propre erreur éventuelle."""
    g = lambda p: _px_get(db, factory, conn_id, p)  # noqa: E731
    return {"options": await _part(g("/cluster/firewall/options"), lambda r: shape_options("cluster", r)),
            "rules": await _part(g("/cluster/firewall/rules"), shape_rules),
            "aliases": await _part(g("/cluster/firewall/aliases"), shape_aliases),
            "ipsets": await _part(g("/cluster/firewall/ipset"), lambda r: shape_named(r, "name")),
            "groups": await _part(g("/cluster/firewall/groups"), lambda r: shape_named(r, "group"))}


@router.get("/firewall/cluster/ipsets/{name}")
async def firewall_ipset(conn_id: int, name: str = NAMED, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_ipset_entries(await _px_get(db, factory, conn_id, f"/cluster/firewall/ipset/{name}"))


@router.get("/firewall/cluster/groups/{name}")
async def firewall_group(conn_id: int, name: str = NAMED, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Règles d'un groupe de sécurité."""
    return shape_rules(await _px_get(db, factory, conn_id, f"/cluster/firewall/groups/{name}"))


@router.get("/firewall/nodes/{node}")
async def firewall_node(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    g = lambda p: _px_get(db, factory, conn_id, p)  # noqa: E731
    return {"options": await _part(g(f"/nodes/{node}/firewall/options"), lambda r: shape_options("node", r)),
            "rules": await _part(g(f"/nodes/{node}/firewall/rules"), shape_rules)}


@router.get("/firewall/guests/{node}/{gtype}/{vmid}")
async def firewall_guest(conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    g = lambda p: _px_get(db, factory, conn_id, p)  # noqa: E731
    base = f"/nodes/{node}/{gtype}/{vmid}/firewall"
    return {"options": await _part(g(f"{base}/options"), lambda r: shape_options("guest", r)), "rules": await _part(g(f"{base}/rules"), shape_rules)}
