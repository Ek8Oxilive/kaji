"""Console SPICE d'une VM ou d'un conteneur : Kaji demande un ticket à Proxmox (`spiceproxy`) et renvoie le fichier `.vv` à ouvrir avec `virt-viewer`.

Droit Proxmox : `VM.Console` sur la machine. Le ticket est à usage unique (~40 s) : il n'est ni journalisé ni audité, la réponse n'est jamais mise en cache.
Une VM doit avoir une carte d'affichage `qxl` (sinon SPICE n'a pas d'écran à montrer) ; un conteneur ouvre un terminal.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..devicespec import parse_vga
from ..deps import get_client_factory
from ..models import AdminUser
from ..spicespec import SpiceError, build_vv, proxy_host
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px
from .connections import _get_or_404

router = APIRouter(tags=["console"], dependencies=[Depends(current_user)])


@router.post("/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}/spice")
async def open_spice(conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                     db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Renvoie un fichier `.vv` (type `application/x-virt-viewer`) contenant un ticket SPICE à usage unique. La machine doit être en marche."""
    conn = _get_or_404(db, conn_id)
    target = f"{gtype}/{vmid}@{node} (spice)"

    def refuse(code: int, msg: str):
        audit.record(db, username=user.username, connection_id=conn_id, action="spice-open", target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    cur = await _px(db, factory, conn_id, "get", f"/nodes/{node}/{gtype}/{vmid}/status/current")
    if not isinstance(cur, dict) or cur.get("status") != "running" or cur.get("template"):
        refuse(409, "La machine doit être en marche (et ne pas être un modèle) pour ouvrir sa console")
    if gtype == "qemu":
        cfg = await _px(db, factory, conn_id, "get", f"/nodes/{node}/qemu/{vmid}/config", current=1)     # la configuration EN COURS d'utilisation
        vga = parse_vga(cfg.get("vga")) if isinstance(cfg, dict) else None          # lit « qxl » comme « type=qxl,memory=32 » (la forme que Kaji écrit)
        if not (vga and str(vga["type"] or "").startswith("qxl")):
            refuse(409, "Cette VM n'a pas de carte d'affichage SPICE (qxl) : choisis-la dans l'onglet Périphériques, puis redémarre la VM")
    params = {}
    proxy = proxy_host(conn.host)
    if proxy:
        params["proxy"] = proxy                          # le nœud que le client joint (celui de la connexion), pas le nom interne du nœud
    try:
        reply = await _px(db, factory, conn_id, "post", f"/nodes/{node}/{gtype}/{vmid}/spiceproxy", **params)
    except HTTPException as e:
        audit.record(db, username=user.username, connection_id=conn_id, action="spice-open", target=target, status="error", detail=str(e.detail))
        raise
    try:
        text = build_vv(reply)
    except SpiceError as e:
        refuse(502, str(e))
    audit.record(db, username=user.username, connection_id=conn_id, action="spice-open", target=target, status="started")
    return Response(content=text, media_type="application/x-virt-viewer",
                    headers={"Content-Disposition": f'attachment; filename="kaji-{gtype}-{vmid}.vv"'})      # jamais mis en cache : le middleware pose `no-store` sur toute l'API
