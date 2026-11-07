"""ACME (certificats automatiques) : lecture et garde-fous d'écriture (comptes, domaines d'un nœud, commande de certificat).

Une opération ACME **contacte une autorité extérieure** (Let's Encrypt) : l'adresse de contact est transmise, les conditions d'utilisation
doivent être acceptées explicitement, et une commande trop répétée est limitée par l'autorité. Les plugins DNS portent des secrets d'API :
ils ne sont qu'en lecture (sans leurs données) dans ce lot.
"""
import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .storagespec import _str

ACCOUNT = r"^[a-z][a-z0-9_-]{0,31}$"
PLUGIN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63}){1,5}")
LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
FQDN = re.compile(rf"(\*\.)?({LABEL}\.)+[A-Za-z]{{2,24}}")
MAX_DOMAINS = 5
DIGEST = r"^[0-9a-f]{40}$"
STAGING_HINT = "staging"


class _Confirm(BaseModel):
    confirm: bool = False


class AccountCreate(_Confirm):
    name: str = Field(pattern=ACCOUNT)
    contact: str = Field(max_length=254)
    directory: str = Field(max_length=300)
    accept_tos: bool = False


class AccountDelete(_Confirm):
    type_name: str | None = Field(default=None, max_length=40)


class Domain(BaseModel):
    domain: str = Field(max_length=253)
    plugin: str | None = Field(default=None, pattern=PLUGIN)


class AcmeConfig(_Confirm):
    account: str = Field(pattern=ACCOUNT)
    domains: list[Domain] = Field(min_length=1, max_length=MAX_DOMAINS)
    digest: str | None = Field(default=None, pattern=DIGEST)


class Order(_Confirm):
    replace_existing: bool = False


# ------------------------------------------------------------------ lecture

def shape_accounts(names, details: dict) -> list[dict]:
    out = []
    for r in names if isinstance(names, list) else []:
        n = _str(r.get("name")) if isinstance(r, dict) else None
        if not n or not re.fullmatch(ACCOUNT[1:-1], n):
            continue
        d = details.get(n) if isinstance(details.get(n), dict) else {}
        acc = d.get("account") if isinstance(d.get("account"), dict) else {}
        contact = [c[7:] if isinstance(c, str) and c.startswith("mailto:") else None for c in (acc.get("contact") or [])]
        out.append({"name": n, "directory": _str(d.get("directory")), "contact": [c for c in contact if c][:3], "status": _str(acc.get("status"))})
    return sorted(out, key=lambda a: a["name"])


def shape_directories(raw) -> list[dict]:
    return [{"name": _str(r.get("name")), "url": _str(r.get("url"))} for r in (raw if isinstance(raw, list) else [])
            if isinstance(r, dict) and _str(r.get("url")) and urlparse(r["url"]).scheme == "https" and _str(r.get("name"))][:10]


def shape_plugins(raw) -> list[dict]:
    """Sans la moindre donnée de configuration : un plugin DNS peut porter un jeton d'API."""
    return [{"id": _str(r.get("plugin")), "type": _str(r.get("type"))} for r in (raw if isinstance(raw, list) else [])
            if isinstance(r, dict) and _str(r.get("plugin")) and re.fullmatch(PLUGIN[1:-1], r["plugin"])]


def _props(v) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (v.split(",") if isinstance(v, str) else []):
        k, _, val = part.partition("=")
        if k and val:
            out[k.strip()] = val.strip()
    return out


def shape_node_acme(cfg) -> dict:
    c = cfg if isinstance(cfg, dict) else {}
    domains = []
    for i in range(MAX_DOMAINS):
        p = _props(c.get(f"acmedomain{i}"))
        if p.get("domain"):
            domains.append({"slot": i, "domain": p["domain"][:253], "plugin": p.get("plugin")})
    digest = c.get("digest")
    return {"account": _props(c.get("acme")).get("account"), "domains": domains,
            "digest": digest if isinstance(digest, str) and re.fullmatch(DIGEST[1:-1], digest) else None}


# ------------------------------------------------------------------ garde-fous

def domain_problem(d: Domain, plugins: dict[str, str]) -> str | None:
    if not FQDN.fullmatch(d.domain):
        return "Nom de domaine invalide (un nom complet comme pve.exemple.org)"
    wildcard = d.domain.startswith("*.")
    if d.plugin is None or d.plugin == "standalone":
        if wildcard:
            return "Un domaine générique (*.) exige un plugin DNS"
        return None if d.plugin is None or plugins.get("standalone") == "standalone" else "Plugin standalone absent"
    if d.plugin not in plugins:
        return f"Plugin « {d.plugin} » inconnu"
    return None


def verdict_account(b: AccountCreate, directories: list[dict], tos: str | None, existing: set[str]) -> tuple[int, str] | None:
    if not b.accept_tos:
        return 400, "Tu dois accepter les conditions d'utilisation de l'autorité (accept_tos)"
    if not b.confirm:
        return 400, "Confirmation requise"
    if not EMAIL.fullmatch(b.contact):
        return 422, "Adresse de contact invalide"
    if b.directory not in {d["url"] for d in directories}:
        return 422, "Annuaire ACME inconnu : choisis-en un proposé par Proxmox"
    if tos is None:
        return 502, "Conditions d'utilisation illisibles : création refusée par précaution"
    if b.name in existing:
        return 409, "Ce compte existe déjà"
    return None


def verdict_delete(b: AccountDelete, name: str, existing: set[str], used_by: list[str] | None) -> tuple[int, str] | None:
    if name not in existing:
        return 404, "Compte introuvable"
    if used_by is None:
        return 502, "Configuration des nœuds illisible : suppression refusée par précaution"
    if used_by:
        return 422, "Ce compte est utilisé par le nœud : " + ", ".join(used_by) + " (retire d'abord sa configuration ACME)"
    if not b.confirm:
        return 400, "Confirmation requise"
    if b.type_name != name:
        return 400, "Retape le nom exact du compte pour confirmer"
    return None


def verdict_config(b: AcmeConfig, accounts: set[str], plugins: dict[str, str], current: dict) -> tuple[int, str] | None:
    if not b.confirm:
        return 400, "Confirmation requise"
    if b.account not in accounts:
        return 404, "Compte ACME introuvable"
    names = [d.domain.lower() for d in b.domains]
    if len(set(names)) != len(names):
        return 422, "Domaines en double"
    for d in b.domains:
        problem = domain_problem(d, plugins)
        if problem:
            return 422, problem
    if current.get("digest") is not None and b.digest is not None and b.digest != current["digest"]:
        return 409, "La configuration du nœud a changé entre-temps : recharge et recommence"
    return None


def verdict_order(b: Order, current: dict, directory: str | None, has_custom: bool, verify_ssl: bool) -> tuple[int, str] | None:
    if not current.get("account") or not current.get("domains"):
        return 409, "Configure d'abord un compte ACME et au moins un domaine sur ce nœud"
    if directory is None:
        return 502, "Annuaire du compte illisible : commande refusée par précaution"
    if verify_ssl and STAGING_HINT in directory:
        return 422, "Annuaire de TEST (staging) : son certificat n'est pas approuvé et Kaji, qui vérifie le TLS, perdrait l'accès au nœud"
    if not b.confirm:
        return 400, "Confirmation requise"
    if has_custom and not b.replace_existing:
        return 409, "Un certificat personnalisé est déjà installé : confirme son remplacement (replace_existing)"
    return None
