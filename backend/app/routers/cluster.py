"""Lecture de l'état d'un cluster Proxmox via une connexion enregistrée."""
from collections.abc import Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..proxmox import ProxmoxClient
from .auth import current_user
from .connections import _get_or_404, _params

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["cluster"],
                   dependencies=[Depends(current_user)])

Factory = Callable[..., ProxmoxClient]


async def _px(db: Session, factory: Factory, conn_id: int, method: str, path: str, **params):
    client = factory(**_params(_get_or_404(db, conn_id)))
    try:
        return await getattr(client, method)(path, **params)
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        detail = {401: "Token refusé par Proxmox", 403: "Droits insuffisants pour cette opération"}.get(
            code, f"Proxmox a répondu {code} ({e.response.reason_phrase})")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail)
    except httpx.TimeoutException:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Proxmox ne répond pas")
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Proxmox injoignable")
    finally:
        await client.aclose()


async def _px_get(db: Session, factory: Factory, conn_id: int, path: str, **params):
    return await _px(db, factory, conn_id, "get", path, **params)


def _guest(r: dict) -> dict:
    return {
        "vmid": r.get("vmid"), "name": r.get("name"), "type": r.get("type"),  # qemu | lxc
        "node": r.get("node"), "status": r.get("status"), "template": bool(r.get("template")),
        "cpu": r.get("cpu", 0), "maxcpu": r.get("maxcpu"),
        "mem": r.get("mem", 0), "maxmem": r.get("maxmem"),
        "disk": r.get("disk", 0), "maxdisk": r.get("maxdisk"),
        "uptime": r.get("uptime", 0),
    }


@router.get("/cluster/status")
async def cluster_status(conn_id: int, db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory)):
    items = await _px_get(db, factory, conn_id, "/cluster/status")
    cluster = next((i for i in items if i.get("type") == "cluster"), None)
    nodes = [i for i in items if i.get("type") == "node"]
    return {
        "name": cluster.get("name") if cluster else None,
        "quorate": bool(cluster.get("quorate")) if cluster else None,
        "nodes": [{"name": n.get("name"), "online": bool(n.get("online")), "ip": n.get("ip")} for n in nodes],
    }


@router.get("/nodes")
async def nodes(conn_id: int, db: Session = Depends(get_db),
                factory: Factory = Depends(get_client_factory)):
    data = await _px_get(db, factory, conn_id, "/nodes")
    return sorted(
        ({k: n.get(k) for k in ("node", "status", "cpu", "maxcpu", "mem", "maxmem", "disk", "maxdisk", "uptime")}
         for n in data),
        key=lambda n: n["node"] or "",
    )


@router.get("/guests")
async def guests(conn_id: int, node: str | None = Query(default=None),
                 db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Liste unifiée des VM (qemu) et conteneurs (lxc) du cluster."""
    data = await _px_get(db, factory, conn_id, "/cluster/resources", type="vm")
    out = [_guest(r) for r in data if r.get("type") in ("qemu", "lxc")]
    if node:
        out = [g for g in out if g["node"] == node]
    return sorted(out, key=lambda g: g["vmid"] or 0)


@router.get("/storages")
async def storages(conn_id: int, db: Session = Depends(get_db),
                   factory: Factory = Depends(get_client_factory)):
    data = await _px_get(db, factory, conn_id, "/cluster/resources", type="storage")
    return sorted(
        ({"storage": r.get("storage"), "node": r.get("node"), "type": r.get("plugintype"),
          "status": r.get("status"), "shared": bool(r.get("shared")),
          "disk": r.get("disk", 0), "maxdisk": r.get("maxdisk"), "content": r.get("content")}
         for r in data),
        key=lambda s: (s["storage"] or "", s["node"] or ""),
    )
