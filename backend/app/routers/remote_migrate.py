"""Migration distante d'une VM ou d'un conteneur vers un AUTRE cluster (lot #390). EXPERIMENTAL chez Proxmox : jamais essayée en réel (un seul cluster).

`POST /api/connections/{conn_id}/guests/{node}/{qemu|lxc}/{vmid}/remote-migrate`. Validation, secrets et verrous : `app/remotemigrate.py`.
Verrous serveur : machines de `KAJI_PROTECTED_VMIDS` (dont le CT de Kaji) refusées ; `confirm` ; `delete` (supprime l'ORIGINAL) exige le nom exact retapé et la phrase `COUPURE POSSIBLE` ;
une VM en marche exige `online`, un conteneur en marche `restart` ou `online` ; `dry_run`. Le jeton du cluster distant n'est jamais renvoyé, journalisé ni mis dans une erreur.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..remotemigrate import PHRASE, RemoteMigrate, build_params, clean_error, masked
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(tags=["remote-migrate"], dependencies=[Depends(current_user)])
BASE = "/api/connections/{conn_id}/guests/{node}/{gtype}/{vmid}/remote-migrate"
PROTECTED = "Machine protégée (KAJI_PROTECTED_VMIDS) : elle ne migre pas depuis Kaji"


@router.post(BASE, status_code=status.HTTP_202_ACCEPTED)
async def remote_migrate(body: RemoteMigrate, conn_id: int, node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999),
                         db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Migre la machine vers un autre cluster. Une machine en marche exige `online` (VM) ou `restart` / `online` (conteneur) ; `delete` supprime l'original."""
    target = f"{gtype}/{vmid}@{node}"

    def log(st, detail=None, upid=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="remote-migrate", target=target, status=st, detail=detail, upid=upid)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method, path, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            msg = clean_error(str(e.detail), body)
            log("error", msg)
            raise HTTPException(e.status_code, msg) from None

    if vmid in get_settings().protected_vmids:
        refuse(PROTECTED, status.HTTP_409_CONFLICT)
    try:
        params = build_params(body, gtype)
    except ValueError as e:
        refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    current = await px("get", f"/nodes/{node}/{gtype}/{vmid}/status/current")
    if not isinstance(current, dict):
        refuse("Machine introuvable", status.HTTP_404_NOT_FOUND)
    running = current.get("status") == "running"
    if running and gtype == "qemu" and not body.online:
        refuse("Une VM en marche ne migre vers un autre cluster qu'à chaud (online=true) ; éteins-la pour une migration à froid", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if running and gtype == "lxc" and not (body.restart or body.online):
        refuse("Un conteneur en marche migre avec un redémarrage (restart=true) ou à chaud (online=true, expérimental)", status.HTTP_422_UNPROCESSABLE_ENTITY)
    name = current.get("name") if isinstance(current.get("name"), str) and current.get("name") else str(vmid)
    info = {"host": body.target_host, "port": body.target_port, "token_id": body.target_token_id, "fingerprint": body.target_fingerprint}
    if body.dry_run:
        return {"dry_run": True, "target": info, "params": masked(params), "running": running, "name": name, "locks": {"delete": body.delete, "cut": body.delete, "running": running}}
    if not body.confirm:
        refuse("Migration vers un autre cluster (expérimentale) : renvoie la requête avec confirm=true", status.HTTP_400_BAD_REQUEST)
    if body.delete:
        if body.type_name != name:
            refuse("delete supprime la machine d'origine après la migration : retape son nom exact", status.HTTP_400_BAD_REQUEST)
        if not (body.acknowledge_cut_access and body.phrase == PHRASE):
            refuse("Suppression de l'original : si la migration échoue ou si la copie est incomplète, les données seront perdues. "
                   f"Renvoie la requête avec acknowledge_cut_access=true et phrase=\"{PHRASE}\"", status.HTTP_409_CONFLICT)
    upid = await px("post", f"/nodes/{node}/{gtype}/{vmid}/remote_migrate", **params)
    log("started", f"-> {body.target_host}{':' + str(body.target_port) if body.target_port else ''} (empreinte {body.target_fingerprint[:11]}…) · stockage {body.target_storage} · pont {body.target_bridge}"
        + (f" · id cible {body.target_vmid}" if body.target_vmid else "") + (" · à chaud" if body.online else "") + (" · avec redémarrage" if body.restart else "")
        + (" · ORIGINAL SUPPRIMÉ" if body.delete else ""), upid=upid if isinstance(upid, str) else None)
    return {"upid": upid if isinstance(upid, str) else None, "node": node, "target_host": body.target_host}
