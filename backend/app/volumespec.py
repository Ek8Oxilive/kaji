"""Volumes d'un stockage : protéger une sauvegarde, supprimer un fichier (ISO, modèle, snippet, image) et élaguer les sauvegardes.

L'élagage est destructif et se fait en deux temps : un **aperçu** (Proxmox calcule ce qui serait supprimé, sans rien supprimer), puis
l'**exécution**, qui exige le nombre exact de sauvegardes à supprimer vu dans l'aperçu : si le stockage a changé entre-temps, c'est refusé.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field

from .backupspec import _int, _iso, _protected
from .storageconf import Prune

FileKind = Literal["iso", "vztmpl", "snippets", "import"]
# Fichiers supprimables ici. Les disques de machines (images, rootdir) et les sauvegardes ont leurs propres routes et garde-fous.
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+()\-]{0,200}$")          # ancré : `Path(pattern=…)` cherche, il ne vérifie pas tout le texte
MARKS = ("keep", "remove", "protected", "renamed")
MAX_ROWS = 5000


class Protect(BaseModel):
    protected: bool


class PrunePreview(BaseModel):
    """Règles de conservation à la place de celles du stockage (absentes : Proxmox applique celles du stockage)."""
    retention: Prune | None = None
    vmid: int | None = Field(default=None, ge=100, le=999999999)
    guest_type: Literal["qemu", "lxc"] | None = None


class PruneRun(PrunePreview):
    confirm: bool = False
    type_name: str | None = Field(default=None, max_length=60, description="Nom exact du stockage, retapé")
    expected_remove: int = Field(ge=0, le=MAX_ROWS, description="Nombre de sauvegardes à supprimer, tel que vu dans l'aperçu")


def prune_params(b: PrunePreview) -> dict[str, str | int]:
    """Paramètres de `prunebackups` (GET et DELETE), construits à l'identique pour que l'exécution suive exactement l'aperçu."""
    p: dict[str, str | int] = {}
    if b.retention is not None:
        p["prune-backups"] = b.retention.wire()                 # ValueError si vide ou contradictoire
    if b.vmid is not None:
        p["vmid"] = b.vmid
    if b.guest_type is not None:
        p["type"] = b.guest_type
    return p


def shape_prune(raw) -> dict:
    rows = []
    for r in (raw if isinstance(raw, list) else [])[:MAX_ROWS]:
        if not isinstance(r, dict) or not isinstance(r.get("volid"), str) or not r["volid"]:
            continue
        mark = r.get("mark") if r.get("mark") in MARKS else None
        ctime = _int(r.get("ctime"))
        rows.append({"volid": r["volid"][:300], "vmid": _int(r.get("vmid")), "type": r.get("type") if r.get("type") in ("qemu", "lxc", "openvz") else None,
                     "ctime": ctime, "date": _iso(ctime), "mark": mark})
    rows.sort(key=lambda x: (x["vmid"] or 0, -(x["ctime"] or 0), x["volid"]))
    counts = {m: sum(1 for x in rows if x["mark"] == m) for m in MARKS}
    # Une marque inconnue ne compte jamais comme « à supprimer » : seul « remove » explicite est supprimé.
    return {"items": rows, "counts": counts, "remove": counts["remove"]}


__all__ = ["FILE_NAME", "FileKind", "Protect", "PrunePreview", "PruneRun", "prune_params", "shape_prune", "_protected"]
