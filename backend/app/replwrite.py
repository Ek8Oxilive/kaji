"""Réplication Proxmox en ÉCRITURE : validation en liste blanche, paramètres, verrous (jobs de réplication de stockage, ZFS seulement).

Aucun accès au cluster réel n'a de stockage ZFS : l'écriture n'y est validée que par `dry_run`, qui annonce les **bloqueurs** (pas de stockage ZFS, disque hors ZFS).
Verrous (état relu chez Proxmox) :
- **bloqueur (409)** : aucun stockage ZFS, ou un disque de la machine n'est pas sur un stockage ZFS : Proxmox refuserait, Kaji le dit avant ;
- **machine protégée** (`KAJI_PROTECTED_VMIDS`, dont Kaji) : pas de nouveau job ni de lancement immédiat (403) ; modifier ou supprimer un job existant reste permis ;
- **en direct** (`acknowledge_live=true`) : modifier, supprimer un job existant, ou le lancer maintenant ;
- **données répliquées** : supprimer un job SANS `keep` détruit les copies sur le nœud cible ⇒ le **nom du job** (`1xx-n`) doit être retapé (`type_name`).
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, field_validator

from .hawrite import Locks

NODE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,62})$")
JOB = re.compile(r"^[1-9][0-9]{2,8}-[0-9]{1,9}$")
CALENDAR = re.compile(r"[A-Za-z0-9*/,:\-. ]{1,128}")
CLEAN = re.compile(r"[^\x00-\x1f\x7f]*")
MAX_JOBS_PER_GUEST = 16


def _comment(v):
    if v is not None and not CLEAN.fullmatch(v):
        raise ValueError("Caractère de contrôle interdit")
    return v


class JobFields(Locks):
    schedule: str | None = Field(default=None, max_length=128, description="Calendrier systemd, ex. `*/15`, `mon..fri 02:00` (défaut Proxmox : `*/15`)")
    rate: StrictInt | StrictFloat | None = Field(default=None, ge=1, le=1_000_000, description="Débit max. en Mo/s")
    comment: str | None = Field(default=None, max_length=500)
    disable: StrictBool | None = None

    _c = field_validator("comment")(lambda cls, v: _comment(v))

    @field_validator("schedule")
    @classmethod
    def _schedule(cls, v):
        if v is not None and (not CALENDAR.fullmatch(v) or not v.strip()):
            raise ValueError("Calendrier invalide")
        return v


class JobCreate(JobFields):
    guest: StrictInt = Field(ge=100, le=999999999)
    target: str = Field(pattern=NODE.pattern)


class JobUpdate(JobFields):
    clear: list[Literal["schedule", "rate", "comment", "disable"]] = Field(default=[], max_length=4)


def build_job(body: JobFields, clear: list[str]) -> tuple[dict, list[str]]:
    p: dict = {}
    if body.schedule is not None:
        p["schedule"] = body.schedule.strip()
    if body.rate is not None:
        p["rate"] = body.rate
    if body.comment is not None:
        p["comment"] = body.comment
    if body.disable is not None:
        p["disable"] = 1 if body.disable else 0
    delete = list(dict.fromkeys(clear))
    if set(delete) & set(p):
        raise ValueError("Réglage à la fois modifié et retiré")
    return p, delete


def next_job_id(vmid: int, jobs: list[dict]) -> str | None:
    used = {j["id"] for j in jobs}
    for n in range(MAX_JOBS_PER_GUEST):
        if f"{vmid}-{n}" not in used:
            return f"{vmid}-{n}"
    return None


def blockers(disks: list[dict], storage_types: dict[str, str]) -> list[str]:
    """Raisons pour lesquelles Proxmox refuserait de répliquer cette machine (ZFS obligatoire pour tous ses disques)."""
    out: list[str] = []
    if "zfspool" not in storage_types.values():
        out.append("aucun stockage ZFS n'est configuré sur ce cluster : la réplication de stockage de Proxmox exige du ZFS sur la source et la cible")
    for d in disks:
        t = storage_types.get(d["storage"])
        if t is not None and t != "zfspool":
            out.append(f"le disque {d['key']} est sur le stockage « {d['storage']} » ({t}) : seul ZFS est répliquable")
        elif t is None:
            out.append(f"le disque {d['key']} est sur un stockage inconnu « {d['storage']} »")
    return out
