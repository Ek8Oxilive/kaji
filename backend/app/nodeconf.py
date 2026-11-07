"""Configuration réseau légère d'un nœud : DNS, fichier `hosts`, fuseau horaire. **Peut casser la résolution de noms du cluster.**

Garde-fous :
- DNS : au moins un serveur (adresse IP valide), domaine de recherche valide ; jamais de texte libre transmis.
- `hosts` : le **digest** lu juste avant est obligatoire (modification concurrente refusée) ; le fichier doit garder `localhost` et une ligne pour
  **le nœud lui-même** (sans elle `pve-cluster` ne démarre plus) ; chaque ligne est vérifiée (IP + noms) ; taille bornée ; pas d'octet nul.
- Fuseau horaire : forme `Zone/Ville` contrôlée ; Proxmox valide ensuite l'existence.
"""
import ipaddress
import re

from pydantic import BaseModel, Field, field_validator

DOMAIN = re.compile(r"(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*")
HOSTNAME = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
TIMEZONE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{0,40}(/[A-Za-z0-9_+-]{1,40}){0,2}")
DIGEST = re.compile(r"[0-9a-f]{40}")
MAX_HOSTS = 8192


def _ip(v: str) -> bool:
    try:
        ipaddress.ip_address(v)
        return True
    except ValueError:
        return False


class Confirmed(BaseModel):
    confirm: bool = False


class DnsBody(Confirmed):
    search: str = Field(max_length=253)
    servers: list[str] = Field(min_length=1, max_length=3)

    @field_validator("search")
    @classmethod
    def _search(cls, v: str) -> str:
        if not DOMAIN.fullmatch(v):
            raise ValueError("domaine invalide")
        return v

    @field_validator("servers")
    @classmethod
    def _servers(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v) or any(not _ip(s) for s in v):
            raise ValueError("adresses DNS invalides ou en double")
        return v


class HostsBody(Confirmed):
    content: str = Field(max_length=MAX_HOSTS)
    digest: str = Field(pattern=r"^[0-9a-f]{40}$")


class TimeBody(BaseModel):
    timezone: str = Field(max_length=100)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if not TIMEZONE.fullmatch(v):
            raise ValueError("fuseau horaire invalide")
        return v


def hosts_problem(content: str, node: str) -> str | None:
    """`None` si le fichier est acceptable, sinon la raison (sans jamais citer le contenu)."""
    if "\x00" in content or "\r" in content:
        return "Caractères interdits (octet nul ou retour chariot)"
    has_localhost = has_node = False
    for raw in content.split("\n"):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2 or not _ip(parts[0]):
            return "Chaque ligne doit être « adresse nom [alias…] »"
        names = parts[1:]
        if any(not HOSTNAME.fullmatch(n) for n in names):
            return "Nom d'hôte invalide"
        if "localhost" in names and parts[0] in ("127.0.0.1", "::1"):
            has_localhost = True
        if not ipaddress.ip_address(parts[0]).is_loopback and any(n == node or n.split(".")[0] == node for n in names):
            has_node = True
    if not has_localhost:
        return "La ligne localhost doit rester"
    if not has_node:
        return f"Une ligne avec une adresse non locale pour le nœud « {node} » est obligatoire (sinon le cluster ne démarre plus)"
    return None
