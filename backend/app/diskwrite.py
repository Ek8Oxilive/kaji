"""Écriture sur les disques d'un nœud : initialiser en GPT, effacer, créer LVM / LVM-thin / répertoire / ZFS. **Destructif.**

Principe : l'état est relu chez Proxmox **au moment de l'action** (jamais une valeur du navigateur) et l'action est refusée si cet
état est illisible. Un disque n'est touchable que s'il est vraiment libre :
- `free` : ni utilisation, ni partition ; seul état accepté pour créer un volume ou initialiser en GPT ;
- `leftover` : des partitions existent mais aucune n'est utilisée (restes d'une ancienne installation) ; acceptable pour **effacer** ;
- `busy` : tout le reste (système, LVM, ZFS, monté, OSD Ceph, partition de démarrage…) : **refus absolu**, aucune confirmation n'y change rien.
La suppression de volumes existants n'est volontairement pas dans ce lot.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .diskspec import DEVICE

DISK = r"^/dev/[A-Za-z0-9]{1,30}$"
NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$"
RESERVED = frozenset({"pve", "rpool", "root", "swap", "data", "vm", "local", "local-lvm"})
ZFS_BAD = re.compile(r"(?:c[0-9].*|mirror.*|raidz.*|draid.*|spare.*)")        # noms refusés par ZFS lui-même
RAID_MIN = {"single": 1, "mirror": 2, "raid10": 4, "raidz": 3, "raidz2": 4, "raidz3": 5}
MAX_DEVICES = 12


class Confirmed(BaseModel):
    confirm: bool = False
    type_name: str | None = Field(default=None, max_length=80, description="Texte retapé : le disque (GPT, effacer) ou le nom du volume créé")


class DiskOnly(Confirmed):
    disk: str = Field(pattern=DISK)


class LvmCreate(Confirmed):
    name: str = Field(pattern=NAME)
    device: str = Field(pattern=DISK)
    add_storage: bool = False


class DirectoryCreate(LvmCreate):
    filesystem: Literal["ext4", "xfs"] = "ext4"


class ZfsCreate(Confirmed):
    name: str = Field(pattern=NAME)
    devices: list[str] = Field(min_length=1, max_length=MAX_DEVICES)
    raidlevel: Literal["single", "mirror", "raid10", "raidz", "raidz2", "raidz3"]
    compression: Literal["on", "off", "lz4", "zstd"] = "on"
    ashift: int = Field(default=12, ge=9, le=16)
    add_storage: bool = False

    @model_validator(mode="after")
    def _devices_ok(self):
        if len(set(self.devices)) != len(self.devices) or any(not DEVICE.fullmatch(d) for d in self.devices):
            raise ValueError("périphériques invalides ou en double")
        return self


def disk_state(d: dict) -> str:
    """`free`, `leftover` ou `busy` d'après la sortie de `diskspec.shape_disks` (disque + partitions)."""
    parts = d.get("partitions") or []
    if d.get("osd"):
        return "busy"
    if not d.get("used") and not parts:
        return "free"
    if d.get("used") == "partitions" and parts and all(not p.get("used") for p in parts):
        return "leftover"
    return "busy"


def _find(disks: list[dict], device: str) -> dict | None:
    return next((d for d in disks if d.get("device") == device), None)


def _need(disks: list[dict], device: str, allowed: tuple[str, ...], what: str) -> tuple[int, str] | None:
    d = _find(disks, device)
    if d is None:
        return 404, f"Disque {device} introuvable sur ce nœud"
    st = disk_state(d)
    if st == "busy":
        return 422, f"{device} est utilisé (système, volume, partition ou OSD) : refus, quoi qu'il arrive"
    if st not in allowed:
        return 422, f"{device} contient d'anciennes partitions : efface-le d'abord ({what})"
    return None


def _confirm(confirm: bool, typed: str | None, expected: str, label: str) -> tuple[int, str] | None:
    if not confirm:
        return 400, "Confirmation requise"
    if typed != expected:
        return 400, f"Retape {label} exactement pour confirmer"
    return None


def verdict_gpt(b: DiskOnly, disks: list[dict]) -> tuple[int, str] | None:
    return _need(disks, b.disk, ("free",), "action « Effacer »") or _confirm(b.confirm, b.type_name, b.disk, "le disque")


def verdict_wipe(b: DiskOnly, disks: list[dict]) -> tuple[int, str] | None:
    return _need(disks, b.disk, ("free", "leftover"), "") or _confirm(b.confirm, b.type_name, b.disk, "le disque")


def _name(name: str, existing: set[str], extra_reserved: frozenset[str] = frozenset()) -> tuple[int, str] | None:
    if name.lower() in RESERVED or name.lower() in extra_reserved:
        return 422, f"Nom « {name} » réservé"
    if name in existing:
        return 409, f"« {name} » existe déjà sur ce nœud"
    return None


def verdict_lvm(b: LvmCreate, disks: list[dict], existing: set[str]) -> tuple[int, str] | None:
    return _name(b.name, existing) or _need(disks, b.device, ("free",), "action « Effacer »") or _confirm(b.confirm, b.type_name, b.name, "le nom")


def verdict_zfs(b: ZfsCreate, disks: list[dict], existing: set[str]) -> tuple[int, str] | None:
    if len(b.devices) < RAID_MIN[b.raidlevel]:
        return 422, f"{b.raidlevel} demande au moins {RAID_MIN[b.raidlevel]} disque(s)"
    if b.raidlevel == "raid10" and len(b.devices) % 2:
        return 422, "raid10 demande un nombre pair de disques"
    if b.raidlevel == "single" and len(b.devices) != 1:
        return 422, "single demande exactement 1 disque"
    if ZFS_BAD.fullmatch(b.name.lower()):
        return 422, "Nom refusé par ZFS"
    refused = _name(b.name, existing)
    if refused:
        return refused
    for dev in b.devices:
        refused = _need(disks, dev, ("free",), "action « Effacer »")
        if refused:
            return refused
    return _confirm(b.confirm, b.type_name, b.name, "le nom du pool")
