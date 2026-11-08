"""Objets du pare-feu Proxmox : alias, IPSets (et leurs entrées), groupes de sécurité. Écriture, un objet à la fois, au niveau datacenter ou machine.

Politique de verrous (décision d'Enzo : le but est de remplacer toute l'interface de Proxmox, donc on rend les opérations SÛRES plutôt que de les interdire) :
- un objet **inerte** (non référencé, ou pare-feu du niveau désactivé) se modifie avec `confirm=true` ;
- un objet **utilisé par des règles d'un pare-feu actif** ne se modifie qu'avec `acknowledge_live=true` en plus (verrou décidé par le SERVEUR sur l'état relu
  chez Proxmox, jamais par le navigateur) ; la réponse de refus liste les règles concernées ;
- `management` et `blacklist` (ensembles intégrés que Proxmox utilise sans qu'une règle les nomme) sont toujours considérés comme actifs ;
- suppression : le nom est retapé ; un IPSet non vide ne se supprime qu'avec `delete_members=true`.
"""
import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, field_validator

NAME = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{1,63}$")
GROUP = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{1,17}$")                       # 18 caractères au plus chez Proxmox
REF = re.compile(r"^(dc/|guest/)?[A-Za-z][A-Za-z0-9\-_]{1,63}$")
NOTE = re.compile(r"^[^\x00-\x1f\x7f\\]{0,100}$")
BUILTIN_IPSETS = frozenset({"management", "blacklist"})
Kind = Literal["alias", "ipset", "group"]


def check_name(v: str) -> str:
    if not isinstance(v, str) or not NAME.fullmatch(v):
        raise ValueError("Nom invalide (lettre puis lettres, chiffres, - ou _)")
    return v


def check_group(v: str) -> str:
    if not isinstance(v, str) or not GROUP.fullmatch(v):
        raise ValueError("Nom de groupe invalide (18 caractères au plus)")
    return v


def check_note(v: str | None) -> str | None:
    if v is not None and not NOTE.fullmatch(v):
        raise ValueError("Commentaire invalide : une ligne de 100 caractères, sans antislash")
    return v


def check_ip_or_cidr(v: str) -> str:
    """Adresse IP ou réseau CIDR (IPv4 ou IPv6) : `ipaddress` fait foi, pas une regex."""
    if not isinstance(v, str) or len(v) > 50:
        raise ValueError("Adresse invalide")
    try:
        ipaddress.ip_network(v, strict=False) if "/" in v else ipaddress.ip_address(v)
    except ValueError:
        raise ValueError("Adresse ou réseau invalide") from None
    return v


def check_entry(v: str) -> str:
    """Entrée d'IPSet : adresse, réseau, ou référence à un alias."""
    try:
        return check_ip_or_cidr(v)
    except ValueError:
        if isinstance(v, str) and REF.fullmatch(v):
            return v
        raise ValueError("Entrée invalide (adresse, réseau ou alias)") from None


class Confirmed(BaseModel):
    confirm: StrictBool = False
    type_name: str | None = Field(default=None, max_length=70, description="Nom retapé (modification d'un objet existant)")
    acknowledge_live: StrictBool = False


class AliasCreate(Confirmed):
    name: str = Field(max_length=64)
    cidr: str
    comment: str | None = Field(default=None, max_length=100)

    _n = field_validator("name")(lambda cls, v: check_name(v))
    _c = field_validator("cidr")(lambda cls, v: check_ip_or_cidr(v))
    _m = field_validator("comment")(lambda cls, v: check_note(v))


class AliasUpdate(Confirmed):
    cidr: str
    comment: str | None = Field(default=None, max_length=100)

    _c = field_validator("cidr")(lambda cls, v: check_ip_or_cidr(v))
    _m = field_validator("comment")(lambda cls, v: check_note(v))


class NamedCreate(Confirmed):
    """IPSet (`name`) ou groupe de sécurité (`name`, 18 caractères au plus selon la route)."""
    name: str = Field(max_length=64)
    comment: str | None = Field(default=None, max_length=100)

    _m = field_validator("comment")(lambda cls, v: check_note(v))


class IpsetCreate(NamedCreate):
    _n = field_validator("name")(lambda cls, v: check_name(v))


class GroupCreate(NamedCreate):
    _n = field_validator("name")(lambda cls, v: check_group(v))


class EntryBody(Confirmed):
    cidr: str
    comment: str | None = Field(default=None, max_length=100)
    nomatch: StrictBool = False

    _c = field_validator("cidr")(lambda cls, v: check_entry(v))
    _m = field_validator("comment")(lambda cls, v: check_note(v))


def _tokens(v) -> list[str]:
    return [t.strip() for t in str(v or "").split(",") if t.strip()]


def references(rules: list[dict], kind: Kind, name: str) -> list[int]:
    """Positions des règles qui nomment cet objet : alias (`name`, `dc/name`, `guest/name`), IPSet (`+name`, `+dc/name`), groupe (règle de type `group`)."""
    hits = []
    for r in rules:
        if kind == "group":
            used = r.get("type") == "group" and r.get("action") == name
        else:
            toks = _tokens(r.get("source")) + _tokens(r.get("dest"))
            if kind == "ipset":
                used = any(t.lstrip("+").removeprefix("dc/").removeprefix("guest/") == name for t in toks if t.startswith("+"))
            else:
                used = any(t.removeprefix("dc/").removeprefix("guest/") == name for t in toks if not t.startswith("+"))
        if used and isinstance(r.get("pos"), int):
            hits.append(r["pos"])
    return sorted(hits)


def is_live(kind: Kind, name: str, hits: list[int], scope_enabled: bool) -> bool:
    """Un objet est « actif » s'il est référencé par une règle ET que le pare-feu de son niveau est activé, ou s'il s'agit d'un IPSet intégré."""
    return (kind == "ipset" and name in BUILTIN_IPSETS) or (bool(hits) and scope_enabled)
