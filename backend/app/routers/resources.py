"""Listes de ressources pour les formulaires : bridges / VNets SDN d'un nœud, ISO disponibles."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["resources"], dependencies=[Depends(current_user)])

NODE_ARCH = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "armhf", "riscv64": "riscv64"}   # `uname -m` -> architecture du catalogue


async def _optional(coro):
    """Une source facultative (SDN absent, droits insuffisants…) ne doit pas casser la liste."""
    try:
        return await coro
    except HTTPException:
        return None


@router.get("/api/connections/{conn_id}/nodes/{node}/bridges")
async def bridges(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                  factory: Factory = Depends(get_client_factory)):
    """Réseaux sélectionnables pour une carte réseau : bridges locaux et VNets SDN."""
    local = await _px(db, factory, conn_id, "get", f"/nodes/{node}/network", type="any_bridge")
    vnets = await _optional(_px(db, factory, conn_id, "get", "/cluster/sdn/vnets"))
    out: dict[str, dict] = {}
    for n in local or []:
        name = n.get("iface")
        if not name:
            continue
        if n.get("type") == "vnet":      # selon la version, any_bridge peut déjà inclure les VNets
            out[name] = {"name": name, "kind": "vnet", "zone": n.get("zone"), "detail": n.get("alias"), "vlan_aware": False}
        else:
            out[name] = {"name": name, "kind": "bridge", "zone": None, "vlan_aware": bool(n.get("bridge_vlan_aware")),
                         "detail": n.get("cidr") or n.get("comments") or n.get("address")}
    for v in vnets or []:
        name = v.get("vnet")
        if name:
            out[name] = {"name": name, "kind": "vnet", "zone": v.get("zone"), "detail": v.get("alias"), "vlan_aware": False}
    return sorted(out.values(), key=lambda b: (b["kind"] != "bridge", b["name"]))


@router.get("/api/connections/{conn_id}/nodes/{node}/isos")
async def isos(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
               factory: Factory = Depends(get_client_factory)):
    """Images ISO disponibles sur les stockages du nœud."""
    storages = await _px(db, factory, conn_id, "get", f"/nodes/{node}/storage", content="iso")

    async def one(name: str):
        items = await _optional(_px(db, factory, conn_id, "get", f"/nodes/{node}/storage/{name}/content", content="iso"))
        return [{"volid": i["volid"], "storage": name, "name": i["volid"].split("/", 1)[-1], "size": i.get("size")}
                for i in items or [] if i.get("volid") and i.get("content", "iso") == "iso"]

    names = [s["storage"] for s in storages or [] if s.get("storage") and s.get("active", 1)]
    groups = await asyncio.gather(*(one(n) for n in names))
    return sorted((i for g in groups for i in g), key=lambda i: (i["storage"], i["name"].lower()))


@router.get("/api/connections/{conn_id}/nodes/{node}/templates")
async def lxc_templates(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory)):
    """Modèles de conteneur (LXC) : ceux déjà présents sur les stockages du nœud, et ceux proposés au téléchargement."""
    storages = await _px(db, factory, conn_id, "get", f"/nodes/{node}/storage", content="vztmpl")

    async def one(name: str):
        items = await _optional(_px(db, factory, conn_id, "get", f"/nodes/{node}/storage/{name}/content", content="vztmpl"))
        return [{"volid": i["volid"], "storage": name, "name": i["volid"].split("/", 1)[-1], "size": i.get("size")}
                for i in items or [] if i.get("volid") and i.get("content", "vztmpl") == "vztmpl"]

    names = [s["storage"] for s in storages or [] if s.get("storage") and s.get("active", 1)]
    groups = await asyncio.gather(*(one(n) for n in names))
    local = sorted((i for g in groups for i in g), key=lambda i: (i["storage"], i["name"].lower()))

    apl = await _optional(_px(db, factory, conn_id, "get", f"/nodes/{node}/aplinfo"))
    downloadable = None if apl is None else sorted(
        ({"template": a["template"], "os": a.get("os"), "version": a.get("version"), "section": a.get("section"),
          "architecture": a.get("architecture"), "description": a.get("headline") or a.get("description")}
         for a in apl if a.get("type") == "lxc" and a.get("template")),
        key=lambda a: (a["section"] or "", a["template"]))[:300]
    # Architecture du nœud (noms du catalogue de Proxmox), pour ne proposer par défaut que les modèles utilisables (ticket #205).
    st = await _optional(_px(db, factory, conn_id, "get", f"/nodes/{node}/status"))
    kernel = st.get("current-kernel") if isinstance(st, dict) else None
    machine = kernel.get("machine") if isinstance(kernel, dict) else None
    return {"storages": [s["storage"] for s in storages or [] if s.get("storage")], "local": local, "downloadable": downloadable,
            "node_architecture": NODE_ARCH.get(machine) if isinstance(machine, str) else None}
