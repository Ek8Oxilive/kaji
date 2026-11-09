"""Réseau d'un nœud en écriture : bridges, bonds, VLAN et cartes (Linux uniquement), **en attente** puis appliqués ou annulés.

Chez Proxmox, créer/modifier/supprimer une interface n'écrit que `/etc/network/interfaces.new` : rien ne change tant qu'on n'**applique** pas (`PUT /nodes/{node}/network`),
ce qui recharge le réseau du nœud (et peut le couper). Il n'y a aucun retour arrière automatique. Verrous décidés par le SERVEUR sur l'état relu :
- **préparer** une modification est inerte (`confirm`), SAUF si elle touche l'interface d'administration (celle qui porte la passerelle, ses ports, ses esclaves) ou pose une
  nouvelle passerelle : alors `acknowledge_cut_access` + phrase `COUPURE POSSIBLE` ;
- **appliquer** exige `acknowledge_live` (le réseau du nœud est rechargé), et la phrase si le diff en attente touche l'interface d'administration. Rien à appliquer : refusé.
`dry_run` montre le diff, les verrous et les paramètres sans rien écrire. Open vSwitch, fabrics, VNet et alias ne sont pas gérés ici.
"""
import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

from .fwoptions import PHRASE

KINDS = ("bridge", "bond", "vlan", "eth")
CREATABLE = ("bridge", "bond", "vlan")
NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,19}$")
BR_NAME = re.compile(r"^vmbr[0-9]{1,4}$")
BOND_NAME = re.compile(r"^bond[0-9]{1,4}$")
VLAN_DOT = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_\-]{0,14})\.([0-9]{1,4})$")
VLAN_NAME = re.compile(r"^vlan[0-9]{1,4}$")
VIDS = re.compile(r"^[0-9]{1,4}(-[0-9]{1,4})?( [0-9]{1,4}(-[0-9]{1,4})?)*$")
BOND_MODES = Literal["balance-rr", "active-backup", "balance-xor", "broadcast", "802.3ad", "balance-tlb", "balance-alb", "balance-slb", "lacp-balance-slb", "lacp-balance-tcp"]
HASH = Literal["layer2", "layer2+3", "layer3+4"]
WIRE = {"bond_primary": "bond-primary", "vlan_id": "vlan-id", "vlan_raw_device": "vlan-raw-device"}
CLEARABLE = ("cidr", "cidr6", "gateway", "gateway6", "mtu", "comments", "bridge_ports", "bridge_vlan_aware", "bridge_vids", "slaves", "bond_mode", "bond_xmit_hash_policy",
             "bond_primary", "autostart")
FIELDS = ("cidr", "cidr6", "gateway", "gateway6", "mtu", "comments", "bridge_ports", "bridge_vlan_aware", "bridge_vids", "slaves", "bond_mode", "bond_xmit_hash_policy",
          "bond_primary", "autostart", "vlan_id", "vlan_raw_device")
LISTS = ("bridge_ports", "slaves")


class Locks(BaseModel):
    confirm: StrictBool = False
    acknowledge_live: StrictBool = False
    acknowledge_cut_access: StrictBool = False
    type_name: str | None = Field(default=None, max_length=40)
    dry_run: StrictBool = False


class Fields(Locks):
    cidr: str | None = Field(default=None, max_length=18)
    cidr6: str | None = Field(default=None, max_length=43)
    gateway: str | None = Field(default=None, max_length=15)
    gateway6: str | None = Field(default=None, max_length=39)
    mtu: StrictInt | None = Field(default=None, ge=1280, le=65520)
    comments: str | None = Field(default=None, max_length=200)
    bridge_ports: list[str] | None = Field(default=None, max_length=16)
    bridge_vlan_aware: StrictBool | None = None
    bridge_vids: str | None = Field(default=None, max_length=100)
    slaves: list[str] | None = Field(default=None, max_length=8)
    bond_mode: BOND_MODES | None = None
    bond_xmit_hash_policy: HASH | None = None
    bond_primary: str | None = Field(default=None, max_length=20)
    autostart: StrictBool | None = None
    vlan_id: StrictInt | None = Field(default=None, ge=1, le=4094)
    vlan_raw_device: str | None = Field(default=None, max_length=20)

    @field_validator("cidr")
    @classmethod
    def _cidr(cls, v):
        if v is not None:
            n = ipaddress.ip_interface(v)                       # lève ValueError
            if n.version != 4 or "/" not in v:
                raise ValueError("Adresse IPv4 avec masque (10.0.0.2/24) attendue")
        return v

    @field_validator("cidr6")
    @classmethod
    def _cidr6(cls, v):
        if v is not None and (ipaddress.ip_interface(v).version != 6 or "/" not in v):
            raise ValueError("Adresse IPv6 avec préfixe attendue")
        return v

    @field_validator("gateway")
    @classmethod
    def _gw(cls, v):
        if v is not None and (not re.fullmatch(r"[0-9.]{7,15}", v) or ipaddress.ip_address(v).version != 4):
            raise ValueError("Passerelle IPv4 invalide")
        return v

    @field_validator("gateway6")
    @classmethod
    def _gw6(cls, v):
        if v is not None and (not re.fullmatch(r"[0-9A-Fa-f:.]{2,39}", v) or ipaddress.ip_address(v).version != 6):
            raise ValueError("Passerelle IPv6 invalide")
        return v

    @field_validator("comments")
    @classmethod
    def _comments(cls, v):
        if v is not None and any(ord(c) < 32 for c in v):
            raise ValueError("Commentaire invalide")
        return v

    @field_validator("bridge_ports", "slaves")
    @classmethod
    def _names(cls, v):
        if v is not None and (any(not NAME.fullmatch(x) for x in v) or len(set(v)) != len(v)):
            raise ValueError("Nom d'interface invalide ou en double")
        return v

    @field_validator("bridge_vids")
    @classmethod
    def _vids(cls, v):
        if v is not None:
            if not VIDS.fullmatch(v):
                raise ValueError("Liste de VLAN invalide")
            for part in re.split(r"[ -]", v):
                if not 1 <= int(part) <= 4094:
                    raise ValueError("VLAN hors limites")
        return v

    @field_validator("bond_primary", "vlan_raw_device")
    @classmethod
    def _one(cls, v):
        if v is not None and not NAME.fullmatch(v):
            raise ValueError("Nom d'interface invalide")
        return v


class NetCreate(Fields):
    type: Literal["bridge", "bond", "vlan"]
    iface: str = Field(max_length=20)


class NetUpdate(Fields):
    clear: list[str] = Field(default=[], max_length=16)


def check_name(kind: str, name: str, raw: str | None) -> None:
    ok = {"bridge": bool(BR_NAME.fullmatch(name)), "bond": bool(BOND_NAME.fullmatch(name)),
          "vlan": bool(VLAN_NAME.fullmatch(name)) or bool(VLAN_DOT.fullmatch(name))}[kind]
    if not ok:
        raise ValueError({"bridge": "Nom de bridge : vmbr0 à vmbr9999", "bond": "Nom de bond : bond0 à bond9999", "vlan": "Nom de VLAN : carte.ID (nic0.100) ou vlanID"}[kind])


def check_consistency(kind: str, name: str, new: dict, others: dict[str, dict]) -> None:
    """Cohérence de l'interface telle qu'elle sera : champs propres à son type, ports/esclaves existants et libres, passerelle dans le réseau."""
    own = {"bridge": ("bridge_ports", "bridge_vlan_aware", "bridge_vids"), "bond": ("slaves", "bond_mode", "bond_xmit_hash_policy", "bond_primary"), "vlan": ("vlan_id", "vlan_raw_device"), "eth": ()}[kind]
    for k in ("bridge_ports", "bridge_vlan_aware", "bridge_vids", "slaves", "bond_mode", "bond_xmit_hash_policy", "bond_primary", "vlan_id", "vlan_raw_device"):
        if new.get(k) not in (None, [], "") and k not in own:
            raise ValueError(f"« {k} » ne s'applique pas à une interface de type {kind}")
    if kind == "bridge" and new.get("bridge_vids") and not new.get("bridge_vlan_aware"):
        raise ValueError("bridge_vids exige bridge_vlan_aware")
    if kind == "vlan":
        m = VLAN_DOT.fullmatch(name)
        if m:
            if new.get("vlan_id") not in (None, int(m.group(2))) or new.get("vlan_raw_device") not in (None, m.group(1)):
                raise ValueError("Le nom carte.ID fixe déjà la carte et l'ID du VLAN")
        elif not (new.get("vlan_id") and new.get("vlan_raw_device")):
            raise ValueError("Un VLAN « vlanID » exige vlan_id et vlan_raw_device")
        raw = m.group(1) if m else new.get("vlan_raw_device")
        if raw not in others:
            raise ValueError("Carte du VLAN inconnue")
    for key, wanted in (("bridge_ports", ("eth", "bond", "vlan")), ("slaves", ("eth",))):
        for p in new.get(key) or []:
            if p == name or p not in others or others[p].get("type") not in wanted:
                raise ValueError(f"« {p} » n'est pas un port valide pour {key}")
            for o, cfg in others.items():
                if o != name and (p in (cfg.get("bridge_ports") or []) or p in (cfg.get("slaves") or [])):
                    raise ValueError(f"« {p} » est déjà utilisé par {o}")
    if new.get("bond_primary") and new["bond_primary"] not in (new.get("slaves") or []):
        raise ValueError("bond_primary doit être un des esclaves")
    for gw, cidr in (("gateway", "cidr"), ("gateway6", "cidr6")):
        if new.get(gw):
            if not new.get(cidr):
                raise ValueError(f"{gw} exige {cidr}")
            if ipaddress.ip_address(new[gw]) not in ipaddress.ip_interface(new[cidr]).network:
                raise ValueError(f"{gw} n'est pas dans le réseau de {cidr}")


def management_ifaces(ifaces: list[dict]) -> set[str]:
    """Interfaces dont dépend l'accès au nœud : celles qui portent la passerelle par défaut, leurs ports, esclaves et carte de VLAN (récursivement)."""
    by = {i["iface"]: i for i in ifaces}
    out = {n for n, i in by.items() if i.get("gateway") or i.get("gateway6")}
    todo = list(out)
    while todo:
        i = by.get(todo.pop(), {})
        for sub in list(i.get("bridge_ports") or []) + list(i.get("slaves") or []) + ([i["vlan_raw_device"]] if i.get("vlan_raw_device") else []):
            if sub not in out:
                out.add(sub)
                todo.append(sub)
    return out


def stage_locks(name: str, op: str, change: dict, mgmt: set[str], other_gateway: bool) -> dict:
    cut: list[str] = []
    if name in mgmt:
        cut.append(f"« {name} » est l'interface d'administration du nœud (ou en dépend) : après application, une erreur coupe l'accès à Proxmox et à Kaji")
    if (change.get("gateway") or change.get("gateway6")) and name not in mgmt and other_gateway:
        cut.append("cela déplace la passerelle par défaut du nœud sur une autre interface")
    return {"cut": cut, "live": [], "inert": not cut}


def apply_locks(diff: str | None, mgmt: set[str]) -> dict:
    live = ["appliquer recharge le réseau du nœud : un mauvais réglage le coupe, sans retour arrière automatique"]
    cut: list[str] = []
    hit = sorted(n for n in mgmt if diff and re.findall(r"(?<![A-Za-z0-9_.\-])" + re.escape(n) + r"(?![A-Za-z0-9_\-])", diff))
    if hit:
        cut.append(f"les modifications en attente touchent l'interface d'administration ({', '.join(hit)})")
    if diff and re.findall(r"^-[ \t]*(gateway6?|bridge[-_]ports|bond[-_]slaves|slaves|iface vmbr[0-9]+|iface bond[0-9]+)\b", diff, re.M):
        cut.append("les modifications en attente retirent une passerelle, un port, un esclave ou une interface : l'ancien accès peut disparaître")
    return {"cut": cut, "live": live, "inert": False}


def params_of(fields: dict) -> dict:
    p = {}
    for k, v in fields.items():
        v = " ".join(v) if k == "bridge_ports" or k == "slaves" else v
        p[WIRE.get(k, k)] = (1 if v else 0) if isinstance(v, bool) else v
    return p


__all__ = ["PHRASE"]
