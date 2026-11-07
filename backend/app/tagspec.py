"""Étiquettes (tags) des machines : lecture tolérante et validation stricte à l'écriture.

Proxmox stocke les étiquettes dans une chaîne séparée par `;` (ou `,`/espace à la lecture) et les met en minuscules. Une étiquette valide
suit le motif de Proxmox. L'écriture remplace l'ensemble ; aucune autre option de la machine n'est touchée.
"""
import re

from pydantic import BaseModel, Field, field_validator

TAG = re.compile(r"[a-z0-9_][a-z0-9_\-+.]{0,31}")
MAX_TAGS = 20


def parse_tags(raw) -> list[str]:
    """`"web;Prod, db"` -> `["db", "prod", "web"]` : minuscules, sans doublon, valides seulement, bornées."""
    if not isinstance(raw, str):
        return []
    parts = (p.strip().lower() for p in re.split(r"[;, ]+", raw))
    return sorted({p for p in parts if TAG.fullmatch(p)})[:MAX_TAGS * 2]


class TagsBody(BaseModel):
    tags: list[str] = Field(max_length=MAX_TAGS)

    @field_validator("tags")
    @classmethod
    def _valid(cls, v: list[str]) -> list[str]:
        out = []
        for t in v:
            t = t.strip().lower()
            if not TAG.fullmatch(t):
                raise ValueError("étiquette invalide")
            if t not in out:
                out.append(t)
        return sorted(out)
