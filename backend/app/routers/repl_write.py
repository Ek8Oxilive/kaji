"""Réplication en ÉCRITURE : créer, modifier, supprimer un job, lancer maintenant. Verrous et validation : `app/replwrite.py`.

Supprimer un job le MARQUE pour suppression (`remove_job`) : Proxmox le retire au prochain passage sur le nœud source (et détruit les copies, sauf `keep`). Kaji relit donc
« absent OU marqué ». Le cluster réel n'a pas de ZFS : seul `dry_run` y est utilisable (il liste les bloqueurs).
"""
from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..hardware import DISK_KEY, MP_KEY, parse_disk
from ..haspec import shape_jobs
from ..hawrite import Locks
from ..models import AdminUser
from ..replwrite import JOB, JobCreate, JobUpdate, blockers, build_job, next_job_id
from .auth import current_user
from .cluster import Factory, shape_guests, shape_status
from .ha_write import Ctx

router = APIRouter(prefix="/api/connections/{conn_id}/replication", tags=["replication-write"], dependencies=[Depends(current_user)])


def _job(jobs: list[dict], job_id: str) -> dict | None:
    return next((j for j in jobs if j["id"] == job_id), None)


def _ok(after: dict | None, params: dict, delete: list[str]) -> bool:
    if after is None:
        return False
    for k, v in params.items():
        got = after.get(k)
        if isinstance(got, bool):
            got = int(got)
        if got != v:
            return False
    return all(after.get(k) in (None, False) for k in delete)


def _txt(params: dict, delete: list[str]) -> str:
    return ", ".join(f"{k}={'défini' if k == 'comment' else v}" for k, v in sorted(params.items())) + (f" ; retiré : {','.join(delete)}" if delete else "")


async def _jobs(c: Ctx) -> list[dict]:
    return shape_jobs(await c.px("get", "/cluster/replication"))


@router.post("")
async def create_job(body: JobCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "repl-create", f"{body.guest}->{body.target}")
    c.need_confirm(body)
    c.forbid_protected([f"vm:{body.guest}"])
    jobs = await _jobs(c)
    cluster = shape_status(await c.px("get", "/cluster/status"))
    guest = next((g for g in shape_guests(await c.px("get", "/cluster/resources", type="vm")) if g["vmid"] == body.guest), None)
    if guest is None:
        c.refuse("Machine introuvable", status.HTTP_404_NOT_FOUND)
    if guest["template"]:
        c.refuse("Un modèle ne se réplique pas", status.HTTP_422_UNPROCESSABLE_ENTITY)
    target = next((n for n in cluster["nodes"] if n["name"] == body.target), None)
    if target is None or not target["online"]:
        c.refuse("Nœud cible inconnu ou hors ligne", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.target == guest["node"]:
        c.refuse("La cible doit être un autre nœud que celui de la machine", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if any(j["guest"] == body.guest and j["target"] == body.target for j in jobs):
        c.refuse("Cette machine est déjà répliquée vers ce nœud", status.HTTP_409_CONFLICT)
    job_id = next_job_id(body.guest, jobs)
    if job_id is None:
        c.refuse("Trop de jobs pour cette machine", status.HTTP_409_CONFLICT)
    storages = {s["storage"]: s.get("type") for s in await c.px("get", "/storage") if isinstance(s, dict) and isinstance(s.get("storage"), str)}
    cfg = await c.px("get", f"/nodes/{guest['node']}/{guest['type']}/{body.guest}/config", current=1)
    disks = [d for k, v in (cfg if isinstance(cfg, dict) else {}).items() if isinstance(v, str)
             and ((k == "rootfs" or MP_KEY.fullmatch(k)) if guest["type"] == "lxc" else DISK_KEY.fullmatch(k))
             and (d := parse_disk(k, v))["kind"] == "disk" and d["storage"]]
    block = blockers(disks, storages)
    params, _ = build_job(body, [])
    preview = {"params": {"id": job_id, "type": "local", "target": body.target, **params}, "from": guest["node"], "blockers": block, "blocked": bool(block)}
    lk = {"cut": [], "live": [], "inert": True}
    if body.dry_run:
        return {"dry_run": True, **preview, "locks": lk, "phrase": None}
    if block:
        c.refuse("Réplication impossible : " + " ; ".join(block), status.HTTP_409_CONFLICT)
    await c.px("post", "/cluster/replication", id=job_id, type="local", target=body.target, **params)
    after = _job(await _jobs(c), job_id)
    if not _ok(after, {"target": body.target, **params}, []):
        c.refuse("Proxmox n'a pas appliqué la création", status.HTTP_502_BAD_GATEWAY)
    c.target = job_id
    c.log("started", f"{guest['node']} -> {body.target} ; {_txt(params, [])}")
    return {"created": job_id, "locks": lk}


@router.put("/{job}")
async def update_job(body: JobUpdate, conn_id: int, job: str = Path(pattern=JOB.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                     user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "repl-update", job)
    c.need_confirm(body)
    cur = _job(await _jobs(c), job)
    if cur is None:
        c.refuse("Job de réplication introuvable", status.HTTP_404_NOT_FOUND)
    if cur["remove_job"]:
        c.refuse("Ce job est marqué pour suppression : il ne peut plus être modifié", status.HTTP_409_CONFLICT)
    try:
        params, delete = build_job(body, list(body.clear))
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if not params and not delete:
        c.refuse("Aucune modification demandée", status.HTTP_422_UNPROCESSABLE_ENTITY)
    lk = {"cut": [], "live": ["ce job existe déjà : la modification vaut dès la prochaine synchronisation"], "inert": False}
    out = c.gate(body, lk, {"params": params, "remove": delete})
    if out:
        return out
    send = dict(params)
    if delete:
        send["delete"] = ",".join(delete)
    if isinstance(cur.get("digest"), str):
        send["digest"] = cur["digest"]
    await c.px("put", f"/cluster/replication/{job}", **send)
    if not _ok(_job(await _jobs(c), job), params, delete):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, delete))
    return {"changed": sorted(params), "removed": delete, "locks": lk}


@router.delete("/{job}")
async def delete_job(conn_id: int, job: str = Path(pattern=JOB.pattern), confirm: bool = Query(default=False), acknowledge_live: bool = Query(default=False),
                     keep: bool = Query(default=False, description="Garder les copies déjà répliquées sur le nœud cible"),
                     type_name: str | None = Query(default=None, max_length=40, description="Nom du job retapé (obligatoire sans `keep`)"), dry_run: bool = Query(default=False),
                     db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Marque le job pour suppression. Sans `keep`, les copies sur le nœud cible sont détruites : le nom du job doit être retapé."""
    body = Locks(confirm=confirm, acknowledge_live=acknowledge_live, dry_run=dry_run)
    c = Ctx(db, factory, conn_id, user, "repl-delete", job)
    c.need_confirm(body)
    cur = _job(await _jobs(c), job)
    if cur is None:
        c.refuse("Job de réplication introuvable", status.HTTP_404_NOT_FOUND)
    if cur["remove_job"]:
        c.refuse("Ce job est déjà marqué pour suppression", status.HTTP_409_CONFLICT)
    lk = {"cut": [], "live": ["le job sera retiré au prochain passage sur le nœud source" + ("" if keep else " ; les copies répliquées sur le nœud cible seront DÉTRUITES")], "inert": False}
    out = c.gate(body, lk, {"remove": [job], "keep": keep, "retype": None if keep else job})
    if out:
        return out
    if not keep and type_name != job:
        c.refuse(f"Les copies répliquées seront détruites : retape le nom du job ({job}) dans type_name, ou demande keep=true", status.HTTP_400_BAD_REQUEST)
    await c.px("delete", f"/cluster/replication/{job}", keep=1 if keep else 0)
    after = _job(await _jobs(c), job)
    if after is not None and not after["remove_job"]:
        c.refuse("Proxmox n'a pas retiré ni marqué le job pour suppression", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "marqué pour suppression" + (" (copies conservées)" if keep else " (copies détruites)"))
    return {"deleted": job, "pending_removal": after is not None, "keep": keep, "locks": lk}


@router.post("/{job}/now")
async def run_now(body: Locks, conn_id: int, job: str = Path(pattern=JOB.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                  user: AdminUser = Depends(current_user)):
    """Lance une synchronisation tout de suite (`schedule_now` sur le nœud source)."""
    c = Ctx(db, factory, conn_id, user, "repl-now", job)
    c.need_confirm(body)
    cur = _job(await _jobs(c), job)
    if cur is None:
        c.refuse("Job de réplication introuvable", status.HTTP_404_NOT_FOUND)
    c.forbid_protected([f"vm:{cur['guest']}"] if cur["guest"] else [])
    if cur["remove_job"] or cur["disable"]:
        c.refuse("Ce job est désactivé ou marqué pour suppression", status.HTTP_409_CONFLICT)
    node = cur["source"]
    if not node:
        c.refuse("Nœud source inconnu", status.HTTP_422_UNPROCESSABLE_ENTITY)
    lk = {"cut": [], "live": ["la synchronisation démarre tout de suite (charge disque et réseau sur les deux nœuds)"], "inert": False}
    out = c.gate(body, lk, {"node": node})
    if out:
        return out
    await c.px("post", f"/nodes/{node}/replication/{job}/schedule_now")
    c.log("started", f"synchronisation demandée sur {node}")
    return {"requested": job, "node": node, "locks": lk}
