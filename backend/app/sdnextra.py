"""SDN, suite : contrôleurs (BGP, EVPN, IS-IS), IPAM (pve, NetBox, phpIPAM), DNS (PowerDNS), fabrics (OpenFabric, OSPF) et leurs nœuds.

Mêmes règles que `sdnspec.py` : contrôleurs et fabrics s'écrivent EN ATTENTE (appliquer : verrou actif, et phrase `COUPURE POSSIBLE` car ce sont des protocoles de routage) ;
IPAM et DNS n'ont pas d'état « en attente » chez Proxmox : l'écriture est immédiate, avec `acknowledge_live` si une zone s'en sert. Les secrets (jeton IPAM, clé DNS) sont des
`SecretStr` : jamais relus, journalisés ni renvoyés (l'audit dit seulement « défini »).
"""
import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, StrictBool, StrictInt, field_validator

from .sdnspec import IFACE, NODE, STATES, Locks, _b, _eff, _i, _list, _rows, _s, wire

CTRL_ID = re.compile(r"^[a-z][a-z0-9_\-]{0,7}$")
OBJ_ID = re.compile(r"^[a-z][a-z0-9_\-]{0,30}$")
FABRIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,7}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,30}$")
ISIS_NET = re.compile(r"^[0-9A-Fa-f]{2}(\.[0-9A-Fa-f]{4}){3,9}\.[0-9A-Fa-f]{2}$")
URL = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]{1,253}(:[0-9]{1,5})?(/[A-Za-z0-9._~%/\-]{0,200})?$")
FINGERPRINT = re.compile(r"^([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$")
AREA = re.compile(r"^([0-9]{1,10}|[0-9]{1,3}(\.[0-9]{1,3}){3})$")
SECRET = re.compile(r"^[\x21-\x7e]{1,200}$")
CTRL_FIELDS = ("asn", "peers", "ebgp", "ebgp_multihop", "bgp_multipath_as_path_relax", "node", "loopback", "isis_domain", "isis_ifaces", "isis_net", "fabric")
CTRL_TYPES = {"evpn": ("asn", "peers"), "bgp": ("asn", "peers", "ebgp", "ebgp_multihop", "bgp_multipath_as_path_relax", "node", "loopback", "fabric"),
              "isis": ("node", "loopback", "isis_domain", "isis_ifaces", "isis_net", "fabric")}
CTRL_REQUIRED = {"evpn": ("asn", "peers"), "bgp": ("asn", "node"), "isis": ("node", "isis_domain", "isis_net", "isis_ifaces")}
IPAM_FIELDS = ("url", "section", "fingerprint")
IPAM_TYPES = {"pve": (), "netbox": ("url",), "phpipam": ("url", "section")}
IPAM_REQUIRED = {"pve": (), "netbox": ("url",), "phpipam": ("url", "section")}
DNS_FIELDS = ("url", "ttl", "reversemaskv6", "fingerprint")
FABRIC_FIELDS = ("ip_prefix", "ip6_prefix", "area", "hello_interval", "csnp_interval")
FABRIC_TYPES = {"ospf": ("ip_prefix", "ip6_prefix", "area"), "openfabric": ("ip_prefix", "ip6_prefix", "hello_interval", "csnp_interval")}
LISTS = ("peers", "isis_ifaces")


def _ip_list(v):
    if v is not None:
        for p in v:
            ipaddress.ip_address(p)
        if len(set(v)) != len(v):
            raise ValueError("Adresse en double")
    return v


# ------------------------------------------------------------------ contrôleurs
class CtrlFields(Locks):
    asn: StrictInt | None = Field(default=None, ge=0, le=4294967295)
    peers: list[str] | None = Field(default=None, max_length=32)
    ebgp: StrictBool | None = None
    ebgp_multihop: StrictInt | None = Field(default=None, ge=1, le=255)
    bgp_multipath_as_path_relax: StrictBool | None = None
    node: str | None = Field(default=None, max_length=63)
    loopback: str | None = Field(default=None, max_length=20)
    isis_domain: str | None = Field(default=None, max_length=31)
    isis_ifaces: list[str] | None = Field(default=None, max_length=16)
    isis_net: str | None = Field(default=None, max_length=60)
    fabric: str | None = Field(default=None, max_length=8)

    _p = field_validator("peers")(lambda cls, v: _ip_list(v))

    @field_validator("node")
    @classmethod
    def _node(cls, v):
        if v is not None and not NODE.fullmatch(v):
            raise ValueError("Nom de nœud invalide")
        return v

    @field_validator("loopback")
    @classmethod
    def _lo(cls, v):
        if v is not None and not IFACE.fullmatch(v):
            raise ValueError("Nom d'interface invalide")
        return v

    @field_validator("isis_domain")
    @classmethod
    def _dom(cls, v):
        if v is not None and not NAME.fullmatch(v):
            raise ValueError("Domaine invalide")
        return v

    @field_validator("isis_ifaces")
    @classmethod
    def _ifs(cls, v):
        if v is not None and (any(not IFACE.fullmatch(x) for x in v) or len(set(v)) != len(v)):
            raise ValueError("Interface invalide ou en double")
        return v

    @field_validator("isis_net")
    @classmethod
    def _net(cls, v):
        if v is not None and not ISIS_NET.fullmatch(v):
            raise ValueError("NET IS-IS invalide")
        return v

    @field_validator("fabric")
    @classmethod
    def _fab(cls, v):
        if v is not None and not FABRIC_ID.fullmatch(v):
            raise ValueError("Identifiant de fabric invalide")
        return v


class CtrlCreate(CtrlFields):
    controller: str = Field(max_length=8)
    type: Literal["bgp", "evpn", "isis"]

    @field_validator("controller")
    @classmethod
    def _id(cls, v):
        if not CTRL_ID.fullmatch(v):
            raise ValueError("Identifiant : 8 caractères au plus (minuscules, chiffres, - et _), commence par une lettre")
        return v


class CtrlUpdate(CtrlFields):
    clear: list[str] = Field(default=[], max_length=11)


def check_controller(type_: str, cfg: dict) -> None:
    allowed = CTRL_TYPES[type_]
    for k in CTRL_FIELDS:
        if cfg.get(k) not in (None, [], "") and k not in allowed:
            raise ValueError(f"« {k} » ne s'applique pas à un contrôleur {type_}")
    for k in CTRL_REQUIRED[type_]:
        if cfg.get(k) in (None, [], ""):
            raise ValueError(f"Un contrôleur {type_} exige « {k} »")


# ------------------------------------------------------------------ IPAM et DNS
class UrlFields(Locks):
    url: str | None = Field(default=None, max_length=300)
    fingerprint: str | None = Field(default=None, max_length=95)

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        if v is not None and not URL.fullmatch(v):
            raise ValueError("URL http(s) invalide (sans identifiants)")
        return v

    @field_validator("fingerprint")
    @classmethod
    def _fp(cls, v):
        if v is not None and not FINGERPRINT.fullmatch(v):
            raise ValueError("Empreinte SHA-256 invalide (32 octets séparés par :)")
        return v


def _secret(v: SecretStr | None):
    if v is not None and not SECRET.fullmatch(v.get_secret_value()):
        raise ValueError("Secret invalide")
    return v


class IpamFields(UrlFields):
    section: StrictInt | None = Field(default=None, ge=0, le=100000)
    token: SecretStr | None = None
    _t = field_validator("token")(lambda cls, v: _secret(v))


class IpamCreate(IpamFields):
    ipam: str = Field(max_length=31)
    type: Literal["pve", "netbox", "phpipam"]

    @field_validator("ipam")
    @classmethod
    def _id(cls, v):
        if not OBJ_ID.fullmatch(v):
            raise ValueError("Identifiant invalide (minuscules, chiffres, - et _)")
        return v


class IpamUpdate(IpamFields):
    clear: list[str] = Field(default=[], max_length=3)


class DnsFields(UrlFields):
    key: SecretStr | None = None
    ttl: StrictInt | None = Field(default=None, ge=1, le=2147483647)
    reversemaskv6: StrictInt | None = Field(default=None, ge=1, le=128)
    _k = field_validator("key")(lambda cls, v: _secret(v))


class DnsCreate(DnsFields):
    dns: str = Field(max_length=31)
    type: Literal["powerdns"]
    url: str = Field(max_length=300)
    key: SecretStr

    @field_validator("dns")
    @classmethod
    def _id(cls, v):
        if not OBJ_ID.fullmatch(v):
            raise ValueError("Identifiant invalide (minuscules, chiffres, - et _)")
        return v


class DnsUpdate(DnsFields):
    clear: list[str] = Field(default=[], max_length=4)


def check_ipam(type_: str, cfg: dict) -> None:
    for k in IPAM_FIELDS + ("token",):
        if cfg.get(k) not in (None, "") and k not in IPAM_TYPES[type_] + ("token", "fingerprint"):
            raise ValueError(f"« {k} » ne s'applique pas à un IPAM {type_}")
    if type_ == "pve" and (cfg.get("token") or cfg.get("fingerprint")):
        raise ValueError("L'IPAM « pve » n'a aucun réglage")
    for k in IPAM_REQUIRED[type_]:
        if cfg.get(k) in (None, ""):
            raise ValueError(f"Un IPAM {type_} exige « {k} »")


# ------------------------------------------------------------------ fabrics
class FabricFields(Locks):
    ip_prefix: str | None = Field(default=None, max_length=18)
    ip6_prefix: str | None = Field(default=None, max_length=43)
    area: str | None = Field(default=None, max_length=15)
    hello_interval: StrictInt | None = Field(default=None, ge=1, le=600)
    csnp_interval: StrictInt | None = Field(default=None, ge=1, le=600)

    @field_validator("ip_prefix")
    @classmethod
    def _p4(cls, v):
        if v is not None and (ipaddress.ip_network(v, strict=True).version != 4 or "/" not in v):
            raise ValueError("Préfixe IPv4 attendu (10.0.0.0/24)")
        return v

    @field_validator("ip6_prefix")
    @classmethod
    def _p6(cls, v):
        if v is not None and (ipaddress.ip_network(v, strict=True).version != 6 or "/" not in v):
            raise ValueError("Préfixe IPv6 attendu")
        return v

    @field_validator("area")
    @classmethod
    def _area(cls, v):
        if v is not None and not AREA.fullmatch(v):
            raise ValueError("Zone OSPF invalide (entier ou a.b.c.d)")
        return v


class FabricCreate(FabricFields):
    id: str = Field(max_length=8)
    protocol: Literal["openfabric", "ospf"]

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not FABRIC_ID.fullmatch(v):
            raise ValueError("Identifiant : 8 caractères au plus, lettres, chiffres, - et _")
        return v


class FabricUpdate(FabricFields):
    clear: list[str] = Field(default=[], max_length=5)


class Iface(BaseModel):
    name: str = Field(max_length=20)

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        if not IFACE.fullmatch(v):
            raise ValueError("Nom d'interface invalide")
        return v


class FabricNode(Locks):
    ip: str | None = Field(default=None, max_length=15)
    ip6: str | None = Field(default=None, max_length=39)
    interfaces: list[Iface] | None = Field(default=None, max_length=16)

    @field_validator("ip")
    @classmethod
    def _ip(cls, v):
        if v is not None and (not re.fullmatch(r"[0-9.]{7,15}", v) or ipaddress.ip_address(v).version != 4):
            raise ValueError("IPv4 invalide")
        return v

    @field_validator("ip6")
    @classmethod
    def _ip6(cls, v):
        if v is not None and (not re.fullmatch(r"[0-9A-Fa-f:.]{2,39}", v) or ipaddress.ip_address(v).version != 6):
            raise ValueError("IPv6 invalide")
        return v

    @field_validator("interfaces")
    @classmethod
    def _ifs(cls, v):
        if v is not None and len({i.name for i in v}) != len(v):
            raise ValueError("Interface en double")
        return v


def check_fabric(protocol: str, cfg: dict) -> None:
    for k in FABRIC_FIELDS:
        if cfg.get(k) not in (None, "") and k not in FABRIC_TYPES[protocol]:
            raise ValueError(f"« {k} » ne s'applique pas à un fabric {protocol}")
    if not (cfg.get("ip_prefix") or cfg.get("ip6_prefix")):
        raise ValueError("Un fabric exige ip_prefix ou ip6_prefix")


# ------------------------------------------------------------------ lecture
def shape_controllers(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        e = _eff(r)
        c = r.get("controller")
        if not isinstance(c, str) or not CTRL_ID.fullmatch(c):
            continue
        d = {"controller": c, "type": r.get("type") if r.get("type") in CTRL_TYPES else None, "state": r.get("state") if r.get("state") in STATES else None, "digest": _s(r.get("digest"), 64)}
        for k in CTRL_FIELDS:
            v = e.get(wire(k))
            d[k] = _list(v) if k in LISTS else _b(v) if k in ("ebgp", "bgp_multipath_as_path_relax") else _i(v) if k in ("asn", "ebgp_multihop") else _s(v)
        out.append(d)
    return sorted(out, key=lambda x: x["controller"])


def shape_ipams(raw) -> list[dict]:
    out = [{"ipam": r["ipam"], "type": r.get("type") if r.get("type") in IPAM_TYPES else None, "url": _s(r.get("url"), 300), "section": _i(r.get("section")),
            "fingerprint": _s(r.get("fingerprint"), 95), "token_set": bool(r.get("token")), "digest": _s(r.get("digest"), 64)}
           for r in _rows(raw) if isinstance(r.get("ipam"), str) and OBJ_ID.fullmatch(r["ipam"])]
    return sorted(out, key=lambda x: x["ipam"])


def shape_dns(raw) -> list[dict]:
    out = [{"dns": r["dns"], "type": "powerdns" if r.get("type") == "powerdns" else None, "url": _s(r.get("url"), 300), "ttl": _i(r.get("ttl")), "reversemaskv6": _i(r.get("reversemaskv6")),
            "fingerprint": _s(r.get("fingerprint"), 95), "key_set": bool(r.get("key")), "digest": _s(r.get("digest"), 64)}
           for r in _rows(raw) if isinstance(r.get("dns"), str) and OBJ_ID.fullmatch(r["dns"])]
    return sorted(out, key=lambda x: x["dns"])


def shape_fabrics(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        e = _eff(r)
        i = r.get("id")
        if not isinstance(i, str) or not FABRIC_ID.fullmatch(i):
            continue
        out.append({"id": i, "protocol": r.get("protocol") if r.get("protocol") in FABRIC_TYPES else None, "state": r.get("state") if r.get("state") in STATES else None,
                    "ip_prefix": _s(e.get("ip_prefix"), 18), "ip6_prefix": _s(e.get("ip6_prefix"), 43), "area": _s(e.get("area"), 15), "hello_interval": _i(e.get("hello_interval")),
                    "csnp_interval": _i(e.get("csnp_interval")), "digest": _s(r.get("digest"), 64)})
    return sorted(out, key=lambda x: x["id"])


def shape_fabric_nodes(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        e = _eff(r)
        n = r.get("node_id")
        if not isinstance(n, str) or not NODE.fullmatch(n):
            continue
        ifs = []
        for x in e.get("interfaces") or []:
            name = x.get("name") if isinstance(x, dict) else dict(p.split("=", 1) for p in x.split(",") if "=" in p).get("name") if isinstance(x, str) else None
            if isinstance(name, str) and IFACE.fullmatch(name):
                ifs.append(name)
        out.append({"node": n, "ip": _s(e.get("ip"), 15), "ip6": _s(e.get("ip6"), 39), "interfaces": ifs[:16], "state": r.get("state") if r.get("state") in STATES else None, "digest": _s(r.get("digest"), 64)})
    return sorted(out, key=lambda x: x["node"])
