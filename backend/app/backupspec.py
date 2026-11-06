"""Sauvegardes vzdump : validation de la demande, construction des paramètres Proxmox, mise en forme de la liste."""
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .vmspec import STORAGE

_DIGITS = re.compile(r"-?[0-9]+")


# TODO : `_int`, `_str` et `_iso` existent aussi dans `storagespec.py` (PR #46). Les dédupliquer une fois #46 mergée.
def _int(v) -> int | None:
    """Entier ou None : une valeur absente ou illisible ne doit jamais faire échouer la liste."""
    if isinstance(v, bool):
        return None
    try:
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and _DIGITS.fullmatch(v.strip()):
            return int(v)
    except (ValueError, OverflowError):
        pass
    return None


def _str(v) -> str | None:
    return v if isinstance(v, str) else None


def _iso(ts: int | None) -> str | None:
    if not ts or ts < 0:
        return None
    try:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None

# Fichier de sauvegarde vzdump sur un stockage de fichiers. Les sauvegardes d'un Proxmox Backup Server ont une autre
# forme (`backup/ct/100/2026-…`) : elles sont refusées ici, pas devinées.
BACKUP_FILE = re.compile(
    r"^vzdump-(qemu|lxc)-([0-9]{3,9})-[0-9]{4}_[0-9]{2}_[0-9]{2}-[0-9]{2}_[0-9]{2}_[0-9]{2}"
    r"\.(vma|tar)(\.(zst|gz|lzo))?$")

# Une seule ligne, sans caractère de contrôle ni antislash (Proxmox demande de les échapper : on les refuse).
NOTES = re.compile(r"^[^\x00-\x1f\x7f\\]*$")


class BackupBody(BaseModel):
    """Seuls ces champs existent : tout autre champ envoyé est ignoré, jamais transmis à Proxmox."""
    vmid: int = Field(ge=100, le=999999999)
    storage: str
    mode: Literal["snapshot", "suspend", "stop"] = "snapshot"
    compress: Literal["zstd", "gzip", "lzo", "none"] = "zstd"
    notes: str | None = Field(default=None, max_length=200)

    @field_validator("storage")
    @classmethod
    def _storage(cls, v):
        if not STORAGE.match(v):
            raise ValueError("Nom de stockage invalide")
        return v

    @field_validator("notes")
    @classmethod
    def _notes(cls, v):
        if v is not None and not NOTES.match(v):
            raise ValueError("Notes invalides : une seule ligne, sans antislash")
        return v


def vzdump_params(b: BackupBody) -> dict:
    """Paramètres de `POST /nodes/{node}/vzdump`. `remove=0` est TOUJOURS envoyé : sans lui, Proxmox élague les
    anciennes sauvegardes selon la rétention du stockage, et une sauvegarde manuelle en supprimerait d'autres."""
    params: dict = {"vmid": b.vmid, "storage": b.storage, "mode": b.mode,
                    "compress": "0" if b.compress == "none" else b.compress, "remove": 0}
    if b.notes:
        params["notes-template"] = b.notes
    return params


def shape_backups(data, vmid: int | None = None) -> list[dict]:
    """Sauvegardes d'un stockage, de la plus récente à la plus ancienne. Une entrée illisible est ignorée."""
    out = []
    for v in data if isinstance(data, list) else []:
        if not isinstance(v, dict) or not isinstance(v.get("volid"), str) or not v["volid"]:
            continue
        name = v["volid"].split(":", 1)[-1].rsplit("/", 1)[-1]
        m = BACKUP_FILE.match(name)
        guest = _int(v.get("vmid")) if _int(v.get("vmid")) is not None else (int(m.group(2)) if m else None)
        if vmid is not None and guest != vmid:
            continue
        ctime = _int(v.get("ctime"))
        out.append({
            "volid": v["volid"], "name": name, "vmid": guest,
            "type": m.group(1) if m else None,                       # qemu | lxc, lu dans le nom du fichier
            "format": _str(v.get("format")), "size": _int(v.get("size")),
            "ctime": ctime, "date": _iso(ctime),
            "notes": _str(v.get("notes")), "protected": bool(v.get("protected")),
            "deletable": bool(m) and not v.get("protected"),
        })
    return sorted(out, key=lambda b: (-(b["ctime"] or 0), b["volid"]))
