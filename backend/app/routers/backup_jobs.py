"""Sauvegardes planifiées (`/cluster/backup`) : lister, voir, créer, modifier, activer ou désactiver, supprimer."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..jobspec import (JOB_ID, JobCreate, JobUpdate, create_params, create_risks, describe_selection, parse_retention,
                       retention_string, selection_dict, shape_job, shape_jobs, update_params, update_risks)
from ..models import AdminUser
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/backup-jobs", tags=["backup-jobs"],
                   dependencies=[Depends(current_user)])


def _describe(b, sel=None) -> str:
    """Résumé pour l'audit : jamais le texte des notes."""
    parts = []
    for label, v in (("planification", b.schedule), ("stockage", b.storage), ("mode", b.mode), ("compression", b.compress)):
        if v is not None:
            parts.append(f"{label}={v}")
    if sel is not None:
        parts.append(f"sélection={describe_selection(sel)}")
    if b.retention is not None:
        parts.append(f"rétention={retention_string(b.retention)}")
    if b.enabled is not None:
        parts.append(f"actif={'oui' if b.enabled else 'non'}")
    if "node" in b.model_fields_set:
        parts.append(f"nœud={b.node or 'tous'}")
    if b.notes:
        parts.append("notes=définies")
    return " ".join(parts)


@router.get("")
async def list_jobs(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Jobs de sauvegarde planifiés du cluster, triés par identifiant. Lecture seule."""
    return shape_jobs(await _px(db, factory, conn_id, "get", "/cluster/backup"))


@router.get("/{job_id}")
async def get_job(conn_id: int, job_id: str = Path(pattern=JOB_ID), db: Session = Depends(get_db),
                  factory: Factory = Depends(get_client_factory)):
    job = next((j for j in shape_jobs(await _px(db, factory, conn_id, "get", "/cluster/backup")) if j["id"] == job_id), None)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job introuvable")
    return job


def _recorder(db, user, conn_id, action, target):
    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status=st,
                     detail=detail)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    return log, refuse


def _need_confirm(risks, confirm, refuse):
    if risks and not confirm:
        refuse("Confirmation requise (renvoie la requête avec confirm=true) : " + " ; ".join(risks), 400)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_job(body: JobCreate, conn_id: int, db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Crée un job planifié. Exige `confirm=true` si le mode est `stop` (arrête chaque machine) ou si la rétention peut
    supprimer des sauvegardes existantes (elle s'applique dès la première exécution)."""
    job_id = "kaji-" + secrets.token_hex(5)
    log, refuse = _recorder(db, user, conn_id, "backup-job-create", job_id)
    detail = _describe(body, selection_dict(body.selection))
    _need_confirm(create_risks(body), body.confirm, lambda m, c: refuse(f"{detail} · {m}", c))
    try:
        await _px(db, factory, conn_id, "post", "/cluster/backup", **create_params(body, job_id))
    except HTTPException as e:
        log("error", f"{detail} · {e.detail}")
        raise
    log("started", detail)
    return {"id": job_id}


async def _existing(db, factory, conn_id, job_id, log):
    try:
        data = await _px(db, factory, conn_id, "get", "/cluster/backup")
    except HTTPException as e:
        log("error", str(e.detail))
        raise
    old = next((j for j in data if isinstance(j, dict) and j.get("id") == job_id), None) if isinstance(data, list) else None
    if old is None:
        log("error", "job introuvable")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job introuvable")
    return old


@router.put("/{job_id}")
async def update_job(body: JobUpdate, conn_id: int, job_id: str = Path(pattern=JOB_ID), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Modifie un job (seuls les champs fournis changent). Exige `confirm=true` si la modification RÉDUIT la rétention,
    la reporte sur un autre stockage ou d'autres machines, ou active un job en mode `stop`."""
    log, refuse = _recorder(db, user, conn_id, "backup-job-update", job_id)
    detail = _describe(body, selection_dict(body.selection) if body.selection is not None else None)
    old = await _existing(db, factory, conn_id, job_id, log)
    _need_confirm(update_risks(body, old), body.confirm, lambda m, c: refuse(f"{detail} · {m}", c))
    params, delete = update_params(body, old)
    if delete:
        params["delete"] = ",".join(delete)
    try:
        await _px(db, factory, conn_id, "put", f"/cluster/backup/{job_id}", **params)
    except HTTPException as e:
        log("error", f"{detail} · {e.detail}")
        raise
    log("started", detail)
    return {"id": job_id, "updated": sorted(body.model_fields_set - {"confirm"})}


@router.delete("/{job_id}")
async def delete_job(conn_id: int, job_id: str = Path(pattern=JOB_ID), confirm: bool = Query(default=False),
                     db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                     user: AdminUser = Depends(current_user)):
    """Supprime un job planifié. Exige `confirm=true`. Les sauvegardes DÉJÀ FAITES ne sont pas supprimées."""
    log, refuse = _recorder(db, user, conn_id, "backup-job-delete", job_id)
    if not confirm:
        refuse("Suppression du job : renvoie la requête avec ?confirm=true (les sauvegardes déjà faites sont conservées)", 400)
    old = await _existing(db, factory, conn_id, job_id, log)
    shaped = shape_job(old) or {}
    try:
        await _px(db, factory, conn_id, "delete", f"/cluster/backup/{job_id}")
    except HTTPException as e:
        log("error", str(e.detail))
        raise
    log("started", f"job SUPPRIMÉ (planification={shaped.get('schedule')} stockage={shaped.get('storage')}) ; "
                   "les sauvegardes déjà faites sont conservées")
    return {"deleted": job_id, "note": "Les sauvegardes déjà faites n'ont pas été supprimées."}
