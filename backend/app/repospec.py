"""Dépôts apt d'un nœud : activer / désactiver un dépôt, ajouter un dépôt standard. **Une erreur peut couper toutes les mises à jour.**

L'état est relu chez Proxmox à chaque action (illisible : refus). Le `digest` du navigateur doit être celui du moment (sinon la
configuration a changé entre-temps). Trois cas demandent en plus `accept_risk` : dépôt *enterprise* sans abonnement actif (apt répond 401
et échoue), dépôt de test (paquets non validés), et désactivation du dernier dépôt Proxmox ou Debian actif.
"""
import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

PATH = r"^/etc/apt/[A-Za-z0-9._/-]{1,200}$"
HANDLE = r"^[a-z0-9][a-z0-9-]{0,59}$"
DIGEST = r"^[0-9a-f]{64}$"
PVE_HOSTS = frozenset({"download.proxmox.com", "enterprise.proxmox.com"})
DEBIAN_HOSTS = frozenset({"deb.debian.org", "security.debian.org", "ftp.debian.org"})


class _Base(BaseModel):
    digest: str = Field(pattern=DIGEST)
    confirm: bool = False
    accept_risk: bool = False


class RepoToggle(_Base):
    path: str = Field(pattern=PATH)
    index: int = Field(ge=0, le=200)
    enabled: bool

    @field_validator("path")
    @classmethod
    def _no_traversal(cls, v: str) -> str:
        if ".." in v or "//" in v or v.endswith("/"):
            raise ValueError("chemin invalide")
        return v


class RepoAdd(_Base):
    handle: str = Field(pattern=HANDLE)


def _hosts(repo: dict) -> set[str]:
    out = set()
    for u in repo.get("uris") or []:
        try:
            h = urlparse(u).hostname
        except ValueError:
            h = None
        if h:
            out.add(h.lower())
    return out


def _enabled_hosts(files: list[dict], skip: tuple[str, int] | None = None) -> set[str]:
    out: set[str] = set()
    for f in files:
        for r in f["repositories"]:
            if r["enabled"] and (f["path"], r["index"]) != skip:
                out |= _hosts(r)
    return out


def find_repo(files: list[dict], path: str, index: int) -> dict | None:
    return next((r for f in files if f["path"] == path for r in f["repositories"] if r["index"] == index), None)


def risks_toggle(files: list[dict], path: str, index: int, enabled: bool, subscription_active: bool) -> list[str]:
    repo = find_repo(files, path, index)
    hosts = _hosts(repo or {})
    out = []
    if enabled:
        if "enterprise.proxmox.com" in hosts and not subscription_active:
            out.append("dépôt « enterprise » sans abonnement actif : apt répondra 401 et les mises à jour échoueront")
    else:
        rest = _enabled_hosts(files, (path, index))
        if hosts & PVE_HOSTS and not rest & PVE_HOSTS:
            out.append("c'est le dernier dépôt Proxmox actif : plus aucune mise à jour de Proxmox")
        if hosts & DEBIAN_HOSTS and not rest & DEBIAN_HOSTS:
            out.append("c'est le dernier dépôt Debian actif : plus aucune mise à jour de sécurité du système")
    return out


def risks_add(handle: str, subscription_active: bool) -> list[str]:
    out = []
    if "test" in handle.split("-"):
        out.append("dépôt de TEST : paquets peu validés, non destinés à la production")
    if "enterprise" in handle.split("-") and not subscription_active:
        out.append("dépôt « enterprise » sans abonnement actif : apt répondra 401 et les mises à jour échoueront")
    return out


def verdict(body_digest: str, fresh: dict, confirm: bool, accept_risk: bool, risks: list[str]) -> tuple[int, str] | None:
    if fresh.get("digest") is None:
        return 502, "Dépôts illisibles : action refusée par précaution"
    if body_digest != fresh["digest"]:
        return 409, "La configuration des dépôts a changé entre-temps : recharge et recommence"
    if not confirm:
        return 400, "Confirmation requise"
    if risks and not accept_risk:
        return 409, "Risque à accepter explicitement (accept_risk) : " + " ; ".join(risks)
    return None
