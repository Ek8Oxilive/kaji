"""Supprimer un volume de disque d'un nœud : groupe LVM, pool LVM-thin, répertoire, pool ZFS. **Détruit les données.**

Principe : l'état (disques, volumes, configuration des stockages, contenu) est relu chez Proxmox à chaque action et la suppression est
refusée dès qu'il est illisible. Refus absolus, quelles que soient les confirmations :
- un nom réservé (`pve`, `rpool`…) ou un volume posé sur un disque système (partition de démarrage ou montée) ;
- un volume qui contient encore quelque chose : volumes logiques LVM, données d'un pool LVM-thin, volumes d'un stockage Proxmox qui
  l'utilise (disques de machines, sauvegardes, ISO), données dans un pool ZFS ;
- un groupe LVM qui contient un pool LVM-thin.
Seul un volume **vide** peut être supprimé : on supprime d'abord son contenu dans Proxmox.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field

from .diskwrite import RESERVED

NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$"
KINDS = ("lvm", "lvmthin", "directory", "zfs")
SYSTEM_PARTITIONS = frozenset({"BIOS boot", "EFI", "mounted"})
ZFS_EMPTY_MAX = 64 * 2**20          # un pool ZFS vide occupe quelques centaines de Ko de métadonnées ; au-delà : des données


class DeleteBody(BaseModel):
    confirm: bool = False
    type_name: str | None = Field(default=None, max_length=80, description="Le nom du volume, retapé")
    vg: str | None = Field(default=None, pattern=NAME, description="Groupe LVM du pool LVM-thin (obligatoire pour lvmthin)")
    cleanup_config: bool = True       # retirer les stockages Proxmox qui pointaient dessus
    cleanup_disks: bool = False       # effacer les disques ensuite (signatures et partitions)


Kind = Literal["lvm", "lvmthin", "directory", "zfs"]


def matching_storages(kind: str, name: str, vg: str | None, storages: list[dict]) -> list[dict]:
    """Stockages de Proxmox qui reposent sur ce volume (`storages` : sortie de `/storage`, déjà filtrée sur les champs utiles)."""
    out = []
    for s in storages:
        t = s.get("type")
        if kind == "lvm" and t == "lvm" and s.get("vgname") == name:
            out.append(s)
        elif kind == "lvm" and t == "lvmthin" and s.get("vgname") == name:
            out.append(s)                                   # un pool LVM-thin vit dans ce groupe
        elif kind == "lvmthin" and t == "lvmthin" and s.get("vgname") == vg and s.get("thinpool") == name:
            out.append(s)
        elif kind == "directory" and t == "dir" and s.get("path") == f"/mnt/pve/{name}":
            out.append(s)
        elif kind == "zfs" and t == "zfspool" and isinstance(s.get("pool"), str) and (s["pool"] == name or s["pool"].startswith(name + "/")):
            out.append(s)
    return out


def _parent_disk(disks: list[dict], device: str | None) -> dict | None:
    if not device:
        return None
    return next((d for d in disks if d["device"] == device or any(p["device"] == device for p in d["partitions"])), None)


def on_system_disk(disks: list[dict], devices: list[str]) -> bool:
    for dev in devices:
        d = _parent_disk(disks, dev)
        if d and (d.get("used") == "mounted" or any(p.get("used") in SYSTEM_PARTITIONS for p in d["partitions"])):
            return True
    return False


def verdict(kind: str, name: str, body: DeleteBody, st: dict) -> tuple[int, str] | None:
    """`st` : `lvm`, `lvmthin`, `directory`, `zfs` (listes de `diskspec`), `disks` (`shape_disks`), `storages` (liste ou `None` si illisible),
    `contents` (`{id du stockage: nombre de volumes ou None si illisible}`)."""
    if kind not in KINDS:
        return 404, "Type de volume inconnu"
    if st.get("storages") is None:
        return 502, "Configuration des stockages illisible : suppression refusée par précaution"
    if kind == "lvmthin" and not body.vg:
        return 400, "Le groupe LVM du pool est obligatoire (vg)"
    # 1. le volume doit exister (chez Proxmox, pas dans la saisie)
    target = None
    devices: list[str] = []
    if kind == "lvm":
        target = next((v for v in st["lvm"] if v["name"] == name), None)
        devices = (target or {}).get("devices", [])
    elif kind == "lvmthin":
        target = next((p for p in st["lvmthin"] if p["name"] == name and p["vg"] == body.vg), None)
        devices = next((v["devices"] for v in st["lvm"] if v["name"] == body.vg), [])
    elif kind == "directory":
        target = next((d for d in st["directory"] if d["path"].rstrip("/").rsplit("/", 1)[-1] == name), None)
        devices = [target["device"]] if target and target.get("device") else []
    else:
        target = next((z for z in st["zfs"] if z["name"] == name), None)
    if target is None:
        return 404, "Volume introuvable sur ce nœud"
    # 2. noms et disques qu'on ne touche jamais
    if name.lower() in RESERVED or (kind == "lvmthin" and (body.vg or "").lower() in RESERVED):
        return 422, f"« {name} » est réservé (système) : refus, quoi qu'il arrive"
    if on_system_disk(st["disks"], devices):
        return 422, "Ce volume est posé sur un disque système (démarrage ou partition montée) : refus, quoi qu'il arrive"
    # 3. il doit être vide
    if kind == "lvm":
        if target.get("volumes") is None or target["volumes"] > 0:
            return 422, "Ce groupe LVM contient encore des volumes logiques : supprime-les d'abord dans Proxmox"
        if any(p["vg"] == name for p in st["lvmthin"]):
            return 422, "Ce groupe LVM contient un pool LVM-thin : supprime-le d'abord"
    elif kind == "lvmthin":
        if target.get("used") is None or target["used"] > 0:
            return 422, "Ce pool LVM-thin contient encore des données : supprime-les d'abord dans Proxmox"
    elif kind == "zfs":
        if target.get("alloc") is None or target["alloc"] > ZFS_EMPTY_MAX:
            return 422, "Ce pool ZFS contient encore des données : supprime-les d'abord dans Proxmox"
    for s in matching_storages(kind, name, body.vg, st["storages"]):
        nodes = s.get("nodes")
        if nodes and st.get("node") not in nodes:
            continue
        count = st["contents"].get(s["storage"])
        if count is None:
            return 502, f"Contenu du stockage « {s['storage']} » illisible : suppression refusée par précaution"
        if count > 0:
            return 422, f"Le stockage « {s['storage']} » contient encore {count} élément(s) : supprime-les ou migre-les d'abord"
    # 4. confirmation
    if not body.confirm:
        return 400, "Confirmation requise"
    if body.type_name != name:
        return 400, "Retape le nom exact du volume pour confirmer"
    return None


def delete_params(kind: str, body: DeleteBody) -> dict:
    p = {"cleanup-config": int(body.cleanup_config), "cleanup-disks": int(body.cleanup_disks)}
    if kind == "lvmthin":
        p["volume-group"] = body.vg
    return p
