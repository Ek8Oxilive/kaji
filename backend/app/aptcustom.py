"""Dépôt apt personnalisé : génère le fichier `.sources` (deb822) et les commandes à copier. **Kaji n'écrit rien chez Proxmox.**

L'API de Proxmox VE n'a aucune route pour un dépôt libre : `/nodes/{n}/apt/repositories` ne sait que lire, activer / désactiver un
dépôt existant et ajouter un dépôt *standard* par son nom (`apidoc.js`, Proxmox 9). Comme pour « installer les mises à jour », Kaji
valide donc chaque champ (liste blanche, aucune clé libre, aucun identifiant dans l'adresse) et fabrique ce qu'il faut coller dans la
console du nœud. Rien n'est envoyé : le contenu et les commandes sont recalculés à partir de champs validés, jamais d'un texte libre.
"""
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

NAME = r"^[a-z0-9][a-z0-9-]{0,59}$"
URI = r"^https?://[A-Za-z0-9][A-Za-z0-9.-]{0,252}(:[0-9]{1,5})?(/[A-Za-z0-9._~%+=/-]{0,200})?$"
SUITE = r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,99}(/[A-Za-z0-9][A-Za-z0-9._+-]{0,99})?$"
COMPONENT = r"^[a-z0-9][a-z0-9._+-]{0,39}$"
KEY = r"^/(usr/share/keyrings|etc/apt/keyrings)/[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.(gpg|asc)$"
ARCHS = ("amd64", "arm64", "armhf", "i386", "all")
PVE_HOSTS = frozenset({"download.proxmox.com", "enterprise.proxmox.com"})


def _unique(v: list[str]) -> list[str]:
    if len(set(v)) != len(v):
        raise ValueError("doublon")
    return v


class CustomRepo(BaseModel):
    name: str = Field(pattern=NAME, description="Nom du fichier : /etc/apt/sources.list.d/<name>.sources")
    types: list[Literal["deb", "deb-src"]] = Field(min_length=1, max_length=2)
    uris: list[str] = Field(min_length=1, max_length=3)
    suites: list[str] = Field(min_length=1, max_length=5)
    components: list[str] = Field(min_length=1, max_length=8)
    signed_by: str | None = Field(default=None, pattern=KEY)
    architectures: list[Literal["amd64", "arm64", "armhf", "i386", "all"]] = Field(default_factory=list, max_length=5)

    @field_validator("types", "uris", "suites", "components", "architectures")
    @classmethod
    def _no_dup(cls, v: list[str]) -> list[str]:
        return _unique(v)

    @field_validator("uris")
    @classmethod
    def _uris(cls, v: list[str]) -> list[str]:
        for u in v:
            if not re.fullmatch(URI, u) or ".." in u or "//" in u.split("://", 1)[1]:
                raise ValueError("adresse invalide (http ou https, sans identifiant, sans paramètre)")
            if (p := urlparse(u).port) is not None and not 1 <= p <= 65535:
                raise ValueError("port invalide")
        return v

    @field_validator("suites")
    @classmethod
    def _suites(cls, v: list[str]) -> list[str]:
        for s in v:
            if not re.fullmatch(SUITE, s):                       # le motif exclut déjà `..` (premier caractère alphanumérique)
                raise ValueError("suite invalide")
        return v

    @field_validator("components")
    @classmethod
    def _components(cls, v: list[str]) -> list[str]:
        for c in v:
            if not re.fullmatch(COMPONENT, c):
                raise ValueError("composant invalide")
        return v


def render(r: CustomRepo) -> str:
    """Contenu deb822 : une seule strophe, champs dans un ordre fixe, jamais de texte libre."""
    lines = [f"Types: {' '.join(r.types)}", f"URIs: {' '.join(r.uris)}", f"Suites: {' '.join(r.suites)}", f"Components: {' '.join(r.components)}"]
    if r.architectures:
        lines.append(f"Architectures: {' '.join(r.architectures)}")
    if r.signed_by:
        lines.append(f"Signed-By: {r.signed_by}")
    return "\n".join(lines) + "\n"


def file_path(r: CustomRepo) -> str:
    return f"/etc/apt/sources.list.d/{r.name}.sources"


def commands(r: CustomRepo) -> list[str]:
    """Commandes à coller dans la console du nœud (le délimiteur est entre guillemets : rien n'est interprété par le shell)."""
    return [f"cat > {file_path(r)} <<'KAJI_EOF'\n{render(r)}KAJI_EOF", "apt update"]


def warnings(r: CustomRepo) -> list[str]:
    out = []
    if any(u.startswith("http://") for u in r.uris):
        out.append("adresse http (non chiffrée) : seule la signature protège les paquets")
    if not r.signed_by:
        out.append("sans « Signed-By » : apt refusera ce dépôt tant que sa clé n'est pas installée (clé à poser toi-même, Kaji n'en télécharge aucune)")
    else:
        out.append("la clé indiquée doit déjà exister sur le nœud (Kaji ne la télécharge pas)")
    if any((urlparse(u).hostname or "").lower() in PVE_HOSTS for u in r.uris):
        out.append("dépôt de Proxmox : préfère « Ajouter un dépôt standard » (nom officiel, `digest` vérifié)")
    if any(c.endswith("test") or "test" in c.split("-") for c in r.components):
        out.append("composant de test : paquets peu validés, non destinés à la production")
    return out
