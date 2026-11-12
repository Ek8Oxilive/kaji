"""Lecture de l'état d'un cluster Proxmox via une connexion enregistrée."""
import re
from collections.abc import Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..proxmox import ProxmoxClient
from ..storagespec import shape_storages
from .auth import current_user
from ..tagspec import parse_tags
from .connections import _get_or_404, _params

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["cluster"],
                   dependencies=[Depends(current_user)])

Factory = Callable[..., ProxmoxClient]


FORBIDDEN_DETAIL = "Droits insuffisants pour cette opération"


CERT_MISMATCH_DETAIL = "Le certificat de Proxmox ne correspond pas à celui épinglé (ou n'est pas approuvé) : vérifie-le sur la page Connexions avant de continuer"


def http_error(e: Exception) -> HTTPException:
    """Traduit une erreur d'appel Proxmox en erreur HTTP lisible (sans jamais exposer de secret)."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        detail = {401: "Token refusé par Proxmox", 403: FORBIDDEN_DETAIL}.get(
            code, f"Proxmox a répondu {code} ({e.response.reason_phrase})")
        return HTTPException(status.HTTP_502_BAD_GATEWAY, detail)
    if isinstance(e, httpx.TimeoutException):
        return HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Proxmox ne répond pas")
    if isinstance(e, httpx.ConnectError) and "CERTIFICATE" in str(e).upper():
        return HTTPException(status.HTTP_502_BAD_GATEWAY, CERT_MISMATCH_DETAIL)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "Proxmox injoignable")


async def _px(db: Session, factory: Factory, conn_id: int, method: str, path: str, /, **params):
    # `path` est positionnel : un paramètre Proxmox nommé `path` (ex. /access/permissions) passe donc par `**params`.
    client = factory(**_params(_get_or_404(db, conn_id)))
    try:
        return await getattr(client, method)(path, **params)
    except httpx.HTTPError as e:
        raise http_error(e)
    finally:
        await client.aclose()


async def _px_get(db: Session, factory: Factory, conn_id: int, path: str, /, **params):
    return await _px(db, factory, conn_id, "get", path, **params)


POOL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")


def _pool(v) -> str | None:
    """Pool de ressources de la machine (absent chez Proxmox quand elle n'en a pas) ; une valeur de forme inattendue est écartée."""
    return v if isinstance(v, str) and POOL.fullmatch(v) else None


def _guest(r: dict) -> dict:
    return {
        "vmid": r.get("vmid"), "name": r.get("name"), "type": r.get("type"),  # qemu | lxc
        "node": r.get("node"), "status": r.get("status"), "template": bool(r.get("template")),
        "cpu": r.get("cpu", 0), "maxcpu": r.get("maxcpu"),
        "mem": r.get("mem", 0), "maxmem": r.get("maxmem"),
        "disk": r.get("disk", 0), "maxdisk": r.get("maxdisk"),
        "uptime": r.get("uptime", 0),
        "tags": parse_tags(r.get("tags")),
        "pool": _pool(r.get("pool")),
    }


def shape_status(items: list[dict]) -> dict:
    cluster = next((i for i in items if i.get("type") == "cluster"), None)
    nodes = [i for i in items if i.get("type") == "node"]
    return {
        "name": cluster.get("name") if cluster else None,
        "quorate": bool(cluster.get("quorate")) if cluster else None,
        "nodes": [{"name": n.get("name"), "online": bool(n.get("online")), "ip": n.get("ip")} for n in nodes],
    }


def shape_nodes(data: list[dict]) -> list[dict]:
    return sorted(
        ({k: n.get(k) for k in ("node", "status", "cpu", "maxcpu", "mem", "maxmem", "disk", "maxdisk", "uptime")}
         for n in data),
        key=lambda n: n["node"] or "",
    )


def shape_guests(data: list[dict], node: str | None = None) -> list[dict]:
    out = [_guest(r) for r in data if r.get("type") in ("qemu", "lxc")]
    if node:
        out = [g for g in out if g["node"] == node]
    return sorted(out, key=lambda g: g["vmid"] or 0)


@router.get("/cluster/status")
async def cluster_status(conn_id: int, db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory)):
    return shape_status(await _px_get(db, factory, conn_id, "/cluster/status"))


@router.get("/nodes")
async def nodes(conn_id: int, db: Session = Depends(get_db),
                factory: Factory = Depends(get_client_factory)):
    return shape_nodes(await _px_get(db, factory, conn_id, "/nodes"))


@router.get("/guests")
async def guests(conn_id: int, node: str | None = Query(default=None),
                 db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Liste unifiée des VM (qemu) et conteneurs (lxc) du cluster."""
    return shape_guests(await _px_get(db, factory, conn_id, "/cluster/resources", type="vm"), node)


@router.get("/storages")
async def storages(conn_id: int, db: Session = Depends(get_db),
                   factory: Factory = Depends(get_client_factory)):
    """Un stockage par nœud. Les champs historiques sont conservés ; `contents`, `used`, `total`, `free`,
    `active` et `nodes` s'y ajoutent (voir `docs/api/stockage.md`)."""
    return shape_storages(await _px_get(db, factory, conn_id, "/cluster/resources", type="storage"))
