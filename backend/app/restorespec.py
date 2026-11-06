"""Restauration d'une sauvegarde vzdump vers une NOUVELLE machine : validation et paramètres Proxmox."""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .backupspec import BACKUP_FILE
from .vmspec import POOL, STORAGE

# `stockage:backup/vzdump-qemu-100-2026_11_02-02_00_01.vma.zst` — rien d'autre n'est accepté (pas de chemin, pas de
# sauvegarde d'un Proxmox Backup Server, pas de fichier hors du dossier `backup/`).
_STORAGE_ID = STORAGE.pattern.removeprefix("^").removesuffix("$")
VOLID = re.compile(rf"^({_STORAGE_ID}):backup/({BACKUP_FILE.pattern.removeprefix('^').removesuffix('$')})$")


class RestoreBody(BaseModel):
    """Seuls ces champs existent : tout autre champ envoyé (dont `force`) est ignoré, jamais transmis à Proxmox."""
    volid: str
    vmid: int | None = Field(default=None, ge=100, le=999999999,
                             description="Nouvel identifiant. Absent : le prochain identifiant libre.")
    storage: str = Field(description="Stockage de destination des disques")
    pool: str | None = None
    unique: bool = Field(default=True, description="Nouvelle adresse MAC (évite un doublon avec la machine d'origine)")

    @field_validator("volid")
    @classmethod
    def _volid(cls, v):
        if not VOLID.fullmatch(v):
            raise ValueError("Sauvegarde invalide : attendu « stockage:backup/vzdump-… »")
        return v

    @field_validator("storage")
    @classmethod
    def _storage(cls, v):
        if not STORAGE.fullmatch(v):
            raise ValueError("Nom de stockage invalide")
        return v

    @field_validator("pool")
    @classmethod
    def _pool(cls, v):
        if v is not None and not POOL.fullmatch(v):
            raise ValueError("Nom de pool invalide")
        return v


def parse_volid(volid: str) -> tuple[str, str, Literal["qemu", "lxc"]]:
    """`(stockage de sauvegarde, nom du fichier, type)` — le type est lu dans le nom, jamais choisi par l'appelant."""
    m = VOLID.fullmatch(volid)
    if not m:
        raise ValueError("Sauvegarde invalide")
    return m.group(1), m.group(2), m.group(3)


def restore_request(b: RestoreBody, vmid: int) -> tuple[str, dict]:
    """`(type, paramètres)` de la création. `force` n'est JAMAIS envoyé (il écraserait une machine existante), ni
    `start` : la machine restaurée reste arrêtée. `storage` est toujours envoyé (sinon Proxmox prend « local » pour un
    conteneur)."""
    _, _, gtype = parse_volid(b.volid)
    params: dict = {"vmid": vmid, "storage": b.storage}
    if gtype == "qemu":
        params["archive"] = b.volid
    else:
        params["ostemplate"] = b.volid
        params["restore"] = 1
    if b.pool:
        params["pool"] = b.pool
    if b.unique:
        params["unique"] = 1
    return gtype, params
