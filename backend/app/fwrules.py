"""Règles du pare-feu Proxmox (datacenter, nœud, machine, groupe de sécurité) : écriture avec verrous à déverrouillage explicite.

Une règle n'a d'effet que si elle est **activée**, que son niveau est **activé** ET que le pare-feu du datacenter (interrupteur général) l'est : sinon l'écriture est inerte
et `confirm` suffit. Une règle est **créée désactivée** sauf demande contraire. Verrous (décidés par le SERVEUR sur l'état relu chez Proxmox) :
- **actif** : la règle (avant ou après) agit sur un pare-feu actif ⇒ `acknowledge_live` ;
- **coupure possible** : la règle bloque (`DROP`/`REJECT`, entrante) un port d'administration (22, 3128, 8006, 5900-5999) ou tout le trafic, ou on retire/désactive/déplace
  une règle `ACCEPT` qui les autorise alors que la politique entrante est restrictive, ou on touche aux règles de la machine de Kaji ⇒ `acknowledge_cut_access` ET `type_name == "COUPURE POSSIBLE"`.
Les champs sont validés un à un ; rien n'est transmis tel quel. `dry_run` montre les verrous sans écrire.
"""
import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

from .fwobjects import GROUP, REF, check_note
from .fwoptions import PHRASE, RESTRICTIVE

LOG = Literal["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug", "nolog"]
ADMIN_PORTS = ((22, 22), (3128, 3128), (8006, 8006), (5900, 5999))
ADMIN_MACROS = frozenset({"SSH", "VNC", "SPICEproxy"})
SERVICES = {"ssh": 22}                                       # noms de service dont le numéro est certain
PROTO = re.compile(r"^([A-Za-z][A-Za-z0-9\-]{0,19}|[0-9]{1,3})$")
PORT_TOKEN = re.compile(r"^([0-9]{1,5}|[A-Za-z][A-Za-z0-9\-]{0,31})(:([0-9]{1,5}|[A-Za-z][A-Za-z0-9\-]{0,31}))?$")
IFACE = re.compile(r"^[A-Za-z0-9_.:\-]{1,20}$")
MACRO = re.compile(r"^[A-Za-z0-9\-_]{1,64}$")
ICMP = re.compile(r"^[A-Za-z0-9\-/]{1,40}$")
RANGE = re.compile(r"^([0-9A-Fa-f:.]+)-([0-9A-Fa-f:.]+)$")
Level = Literal["cluster", "node", "guest", "group"]
FIELDS = ("type", "action", "enable", "source", "dest", "proto", "sport", "dport", "iface", "macro", "log", "icmp_type", "comment")
WIRE = {"icmp_type": "icmp-type"}
CLEARABLE = ("source", "dest", "proto", "sport", "dport", "iface", "macro", "log", "icmp_type", "comment")


def _addr_token(t: str) -> str:
    t = t.strip()
    if not t or len(t) > 100:
        raise ValueError("Adresse invalide")
    name = t[1:] if t.startswith("+") else t
    try:
        ipaddress.ip_network(name, strict=False) if "/" in name else ipaddress.ip_address(name)
        if t.startswith("+"):
            raise ValueError
        return t
    except ValueError:
        pass
    m = RANGE.fullmatch(t)
    if m:
        try:
            a, b = ipaddress.ip_address(m.group(1)), ipaddress.ip_address(m.group(2))
            if a.version == b.version and a <= b:
                return t
        except ValueError:
            pass
        raise ValueError("Plage d'adresses invalide")
    if REF.fullmatch(name):
        return t                                             # alias (`name`, `dc/name`) ou IPSet (`+name`)
    raise ValueError("Adresse invalide")


def check_addr_spec(v: str | None) -> str | None:
    if v is None:
        return None
    if len(v) > 512:
        raise ValueError("Liste d'adresses trop longue")
    return ",".join(_addr_token(t) for t in v.split(","))


def check_port_spec(v: str | None) -> str | None:
    if v is None:
        return None
    if len(v) > 100:
        raise ValueError("Liste de ports trop longue")
    toks = v.split(",")
    for t in toks:
        m = PORT_TOKEN.fullmatch(t)
        if not m:
            raise ValueError("Port invalide")
        for part in (m.group(1), m.group(3)):
            if part and part.isdigit() and not (1 <= int(part) <= 65535):
                raise ValueError("Port hors limites")
    return v


def port_ranges(spec: str | None) -> list[tuple[int, int]] | None:
    """Plages numériques d'une liste de ports, ou None si elle contient un nom de service dont on ne connaît pas le numéro (alors on ne conclut pas)."""
    if not spec:
        return []
    out = []
    for t in spec.split(","):
        a, _, b = t.partition(":")
        vals = []
        for p in (a, b or a):
            if p.isdigit():
                vals.append(int(p))
            elif p.lower() in SERVICES:
                vals.append(SERVICES[p.lower()])
            else:
                return None
        out.append((min(vals), max(vals)))
    return out


def touches_admin(rule: dict) -> bool:
    """La règle concerne-t-elle un port d'administration (ou tout le trafic) ?"""
    if (rule.get("proto") or "tcp").lower() not in ("tcp", "6"):
        return False
    if rule.get("macro"):                                   # une macro porte ses propres ports : seules SSH/VNC/SPICE touchent l'administration
        return rule["macro"] in ADMIN_MACROS
    ranges = port_ranges(rule.get("dport"))
    if ranges is None:
        return False
    return not ranges or any(lo <= ahi and alo <= hi for lo, hi in ranges for alo, ahi in ADMIN_PORTS)


class RuleLocks(BaseModel):
    confirm: StrictBool = False
    acknowledge_live: StrictBool = False
    acknowledge_cut_access: StrictBool = False
    type_name: str | None = Field(default=None, max_length=40)
    dry_run: StrictBool = False


class RuleFields(RuleLocks):
    type: Literal["in", "out", "forward", "group"] | None = None
    action: str | None = Field(default=None, max_length=20)
    enable: StrictBool | None = None
    source: str | None = Field(default=None, max_length=512)
    dest: str | None = Field(default=None, max_length=512)
    proto: str | None = Field(default=None, max_length=20)
    sport: str | None = Field(default=None, max_length=100)
    dport: str | None = Field(default=None, max_length=100)
    iface: str | None = Field(default=None, max_length=20)
    macro: str | None = Field(default=None, max_length=64)
    log: LOG | None = None
    icmp_type: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=100)

    _s = field_validator("source", "dest")(lambda cls, v: check_addr_spec(v))
    _p = field_validator("sport", "dport")(lambda cls, v: check_port_spec(v))
    _c = field_validator("comment")(lambda cls, v: check_note(v))

    @field_validator("proto")
    @classmethod
    def _proto(cls, v):
        if v is not None and (not PROTO.fullmatch(v) or (v.isdigit() and int(v) > 255)):
            raise ValueError("Protocole invalide")
        return v

    @field_validator("iface")
    @classmethod
    def _iface(cls, v):
        if v is not None and not IFACE.fullmatch(v):
            raise ValueError("Interface invalide")
        return v

    @field_validator("macro")
    @classmethod
    def _macro(cls, v):
        if v is not None and not MACRO.fullmatch(v):
            raise ValueError("Macro invalide")
        return v

    @field_validator("icmp_type")
    @classmethod
    def _icmp(cls, v):
        if v is not None and not ICMP.fullmatch(v):
            raise ValueError("Type ICMP invalide")
        return v


class RuleCreate(RuleFields):
    type: Literal["in", "out", "forward", "group"]
    action: str = Field(max_length=20)
    pos: StrictInt | None = Field(default=None, ge=0, le=10000)


class RuleUpdate(RuleFields):
    clear: list[str] = Field(default=[], max_length=10)


class RuleMove(RuleLocks):
    moveto: StrictInt = Field(ge=0, le=10000)


def check_action(type_: str | None, action: str | None, groups: set[str]) -> None:
    if type_ == "group":
        if not action or not GROUP.fullmatch(action) or action not in groups:
            raise ValueError("Groupe de sécurité inconnu")
    elif action is not None and action not in ("ACCEPT", "DROP", "REJECT"):
        raise ValueError("Action invalide (ACCEPT, DROP ou REJECT)")


def params_of(fields: dict) -> dict:
    p = {}
    for k, v in fields.items():
        p[WIRE.get(k, k)] = (1 if v else 0) if isinstance(v, bool) else v
    return p


def effective(cur: dict | None, change: dict, clear: list[str]) -> dict:
    """La règle telle qu'elle sera après une modification (état courant relu + champs changés − champs retirés)."""
    out = dict(cur or {})
    for k in clear:
        out.pop(k, None)
    out.update({k: v for k, v in change.items() if k in FIELDS})
    return out


def _acts(rule: dict | None) -> bool:
    return bool(rule) and bool(rule.get("enable")) and rule.get("type") in ("in", "out", "forward", "group")


def blocks_admin(rule: dict | None) -> bool:
    return _acts(rule) and rule.get("type") in ("in", "forward") and rule.get("action") in RESTRICTIVE and touches_admin(rule)


def allows_admin(rule: dict | None) -> bool:
    return _acts(rule) and rule.get("type") == "in" and rule.get("action") == "ACCEPT" and touches_admin(rule)


def locks(level: str, active: bool, restrictive_in: bool, before: dict | None, after: dict | None, protected_guest: bool) -> dict:
    """Verrous applicables, d'après l'état courant relu. `before`/`after` : la règle avant et après (None = absente)."""
    cut: list[str] = []
    live: list[str] = []
    effect = _acts(before) or _acts(after)
    if active and effect:
        live.append("cette règle agit sur un pare-feu ACTIF : la modification s'applique tout de suite")
        if level in ("cluster", "node", "group") and blocks_admin(after) and not blocks_admin(before):
            cut.append("elle bloque un port d'administration (22, 3128, 8006, 5900-5999) ou tout le trafic entrant")
        if level in ("cluster", "node", "group") and restrictive_in and allows_admin(before) and not allows_admin(after):
            cut.append("elle autorisait l'administration (22, 3128, 8006, 5900-5999) et la politique entrante est restrictive : la retirer, la désactiver ou la déplacer peut tout bloquer")
        if protected_guest:
            cut.append("c'est une règle de la machine de Kaji : une erreur coupe Kaji lui-même")
    return {"cut": cut, "live": live, "inert": not (cut or live)}


__all__ = ["PHRASE", "RuleCreate", "RuleUpdate", "RuleMove", "locks", "effective", "params_of", "check_action", "CLEARABLE", "FIELDS", "Level"]
