"""Notes (champ `description`) d'une machine ou d'un nœud : validation et mise en forme.

Le texte est affiché **tel quel** par l'interface (jamais interprété comme du HTML). Il est borné, sans octet nul. Le `digest` lu juste avant
est exigé à l'écriture : une modification faite entre-temps (par Proxmox ou un autre poste) n'est jamais écrasée sans le savoir.
"""
import re

from pydantic import BaseModel, Field, field_validator

MAX_NOTES = 8192
DIGEST = r"^[0-9a-f]{40}$"
_DIGEST = re.compile(r"[0-9a-f]{40}")


class NotesBody(BaseModel):
    notes: str = Field(max_length=MAX_NOTES)
    digest: str | None = Field(default=None, pattern=DIGEST)       # absent seulement si la configuration est encore VIDE (nœud sans réglage)

    @field_validator("notes")
    @classmethod
    def _text(cls, v: str) -> str:
        if "\x00" in v:
            raise ValueError("caractère interdit")
        return v.replace("\r\n", "\n").replace("\r", "\n")


def shape_notes(cfg) -> dict:
    """`{notes, digest, empty}` d'une configuration lue chez Proxmox ; texte borné, digest `null` s'il est illisible. `empty` : configuration
    **vide** (c'est le cas d'un nœud sans aucun réglage : Proxmox ne renvoie alors pas de digest) ; seule une configuration vide s'écrit sans digest."""
    c = cfg if isinstance(cfg, dict) else {}
    d, digest = c.get("description"), c.get("digest")
    return {"notes": d[:MAX_NOTES] if isinstance(d, str) else "", "digest": digest if isinstance(digest, str) and _DIGEST.fullmatch(digest) else None,
            "empty": isinstance(cfg, dict) and not cfg}


def write_params(body: NotesBody) -> dict:
    """Notes vides : l'option est supprimée ; sinon elle est remplacée. Rien d'autre n'est jamais envoyé."""
    p = {"description": body.notes} if body.notes.strip() else {"delete": "description"}
    return {**p, "digest": body.digest} if body.digest else p
