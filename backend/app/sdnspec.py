"""SDN (zones, VNets, sous-réseaux) : validation, lecture en liste blanche et verrous.

Chez Proxmox, toute écriture SDN est **en attente** (comme le réseau d'un nœud) : rien n'agit sur les nœuds tant qu'on n'**applique** pas (`PUT /cluster/sdn`), et on peut
tout annuler (`POST /cluster/sdn/rollback`). Verrous (décidés par le SERVEUR sur l'état relu) :
- **préparer** : `confirm` suffit (inerte) ; refus de supprimer une zone qui a des VNets ou un VNet qui a des sous-réseaux ;
- **appliquer** : `acknowledge_live` toujours ; phrase `COUPURE POSSIBLE` en plus si l'application touche le réseau des nœuds (zone autre que `simple` créée ou modifiée) ou
  supprime une zone, un VNet ou un sous-réseau (les machines branchées perdent leur réseau).
`dry_run` montre les verrous et les paramètres sans rien écrire. Les contrôleurs, IPAM, DNS et fabrics ne sont pas gérés ici.
"""
import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

ZONE_ID = re.compile(r"^[a-z][a-z0-9]{0,7}$")
VNET_ID = re.compile(r"^[a-z][a-z0-9]{0,7}$")
SUBNET_ID = re.compile(r"^[a-z][a-z0-9]{0,7}-[0-9A-Fa-f:.]{2,45}-[0-9]{1,3}$")
NODE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,62})$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,30}$")
IFACE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,19}$")
DNSNAME = re.compile(r"^([A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?$")
RT = re.compile(r"^[0-9]{1,10}:[0-9]{1,10}$")
STATES = ("new", "changed", "deleted")
ZONE_TYPES = ("simple", "vlan", "qinq", "vxlan", "evpn")
COMMON = ("nodes", "mtu", "ipam", "dns", "reversedns", "dnszone", "dhcp")
PER_TYPE = {"simple": (), "vlan": ("bridge",), "qinq": ("bridge", "tag", "vlan_protocol"), "vxlan": ("peers", "vxlan_port"),
            "evpn": ("controller", "vrf_vxlan", "exitnodes", "exitnodes_primary", "exitnodes_local_routing", "advertise_subnets", "disable_arp_nd_suppression", "rt_import")}
REQUIRED = {"simple": (), "vlan": ("bridge",), "qinq": ("bridge", "tag"), "vxlan": ("peers",), "evpn": ("controller", "vrf_vxlan")}
ZONE_FIELDS = COMMON + ("bridge", "tag", "vlan_protocol", "peers", "vxlan_port", "controller", "vrf_vxlan", "exitnodes", "exitnodes_primary", "exitnodes_local_routing",
                        "advertise_subnets", "disable_arp_nd_suppression", "rt_import")
LISTS = ("nodes", "peers", "exitnodes", "rt_import")
VNET_FIELDS = ("alias", "tag", "vlanaware", "isolate_ports")
SUBNET_FIELDS = ("gateway", "snat", "dhcp_dns_server", "dnszoneprefix", "dhcp_range")


def wire(k: str) -> str:
    return k.replace("_", "-")


class Locks(BaseModel):
    confirm: StrictBool = False
    acknowledge_live: StrictBool = False
    acknowledge_cut_access: StrictBool = False
    type_name: str | None = Field(default=None, max_length=40)
    dry_run: StrictBool = False


def _nodes(v):
    if v is not None and (any(not NODE.fullmatch(x) for x in v) or len(set(v)) != len(v)):
        raise ValueError("Nom de nœud invalide ou en double")
    return v


class ZoneFields(Locks):
    nodes: list[str] | None = Field(default=None, max_length=32)
    mtu: StrictInt | None = Field(default=None, ge=576, le=65520)
    ipam: str | None = Field(default=None, max_length=31)
    dns: str | None = Field(default=None, max_length=31)
    reversedns: str | None = Field(default=None, max_length=31)
    dnszone: str | None = Field(default=None, max_length=253)
    dhcp: Literal["dnsmasq"] | None = None
    bridge: str | None = Field(default=None, max_length=20)
    tag: StrictInt | None = Field(default=None, ge=1, le=4094)
    vlan_protocol: Literal["802.1q", "802.1ad"] | None = None
    peers: list[str] | None = Field(default=None, max_length=32)
    vxlan_port: StrictInt | None = Field(default=None, ge=1, le=65535)
    controller: str | None = Field(default=None, max_length=31)
    vrf_vxlan: StrictInt | None = Field(default=None, ge=1, le=16777215)
    exitnodes: list[str] | None = Field(default=None, max_length=32)
    exitnodes_primary: str | None = Field(default=None, max_length=63)
    exitnodes_local_routing: StrictBool | None = None
    advertise_subnets: StrictBool | None = None
    disable_arp_nd_suppression: StrictBool | None = None
    rt_import: list[str] | None = Field(default=None, max_length=16)

    _n = field_validator("nodes", "exitnodes")(lambda cls, v: _nodes(v))

    @field_validator("ipam", "dns", "reversedns", "controller")
    @classmethod
    def _name(cls, v):
        if v is not None and not NAME.fullmatch(v):
            raise ValueError("Nom invalide")
        return v

    @field_validator("dnszone")
    @classmethod
    def _dnszone(cls, v):
        if v is not None and not DNSNAME.fullmatch(v):
            raise ValueError("Nom DNS invalide")
        return v

    @field_validator("bridge")
    @classmethod
    def _bridge(cls, v):
        if v is not None and not IFACE.fullmatch(v):
            raise ValueError("Nom de bridge invalide")
        return v

    @field_validator("exitnodes_primary")
    @classmethod
    def _prim(cls, v):
        if v is not None and not NODE.fullmatch(v):
            raise ValueError("Nom de nœud invalide")
        return v

    @field_validator("peers")
    @classmethod
    def _peers(cls, v):
        if v is not None:
            for p in v:
                ipaddress.ip_address(p)
            if len(set(v)) != len(v):
                raise ValueError("Pair en double")
        return v

    @field_validator("rt_import")
    @classmethod
    def _rt(cls, v):
        if v is not None and any(not RT.fullmatch(x) for x in v):
            raise ValueError("Route target invalide (ASN:ID)")
        return v


class ZoneCreate(ZoneFields):
    zone: str = Field(max_length=8)
    type: Literal["simple", "vlan", "qinq", "vxlan", "evpn"]

    @field_validator("zone")
    @classmethod
    def _z(cls, v):
        if not ZONE_ID.fullmatch(v):
            raise ValueError("Identifiant de zone : 8 caractères au plus, minuscules et chiffres, commence par une lettre")
        return v


class ZoneUpdate(ZoneFields):
    clear: list[str] = Field(default=[], max_length=16)


class VnetFields(Locks):
    alias: str | None = Field(default=None, max_length=256)
    tag: StrictInt | None = Field(default=None, ge=1, le=16777215)
    vlanaware: StrictBool | None = None
    isolate_ports: StrictBool | None = None

    @field_validator("alias")
    @classmethod
    def _alias(cls, v):
        if v is not None and any(ord(c) < 32 for c in v):
            raise ValueError("Alias invalide")
        return v


class VnetCreate(VnetFields):
    vnet: str = Field(max_length=8)
    zone: str = Field(max_length=8)

    @field_validator("vnet", "zone")
    @classmethod
    def _id(cls, v):
        if not VNET_ID.fullmatch(v):
            raise ValueError("Identifiant : 8 caractères au plus, minuscules et chiffres, commence par une lettre")
        return v


class VnetUpdate(VnetFields):
    clear: list[str] = Field(default=[], max_length=4)


class DhcpRange(BaseModel):
    start: str = Field(max_length=45)
    end: str = Field(max_length=45)

    @field_validator("start", "end")
    @classmethod
    def _ip(cls, v):
        ipaddress.ip_address(v)
        return v


class SubnetFields(Locks):
    gateway: str | None = Field(default=None, max_length=45)
    snat: StrictBool | None = None
    dhcp_dns_server: str | None = Field(default=None, max_length=45)
    dnszoneprefix: str | None = Field(default=None, max_length=100)
    dhcp_range: list[DhcpRange] | None = Field(default=None, max_length=8)

    @field_validator("gateway", "dhcp_dns_server")
    @classmethod
    def _ip(cls, v):
        if v is not None:
            ipaddress.ip_address(v)
        return v

    @field_validator("dnszoneprefix")
    @classmethod
    def _pre(cls, v):
        if v is not None and not DNSNAME.fullmatch(v):
            raise ValueError("Préfixe DNS invalide")
        return v


class SubnetCreate(SubnetFields):
    subnet: str = Field(max_length=50, description="CIDR, ex. 10.99.0.0/24")

    @field_validator("subnet")
    @classmethod
    def _cidr(cls, v):
        if "/" not in v:
            raise ValueError("CIDR attendu (10.0.0.0/24)")
        n = ipaddress.ip_network(v, strict=True)
        if n.prefixlen == n.max_prefixlen:
            raise ValueError("Sous-réseau trop petit")
        return v


class SubnetUpdate(SubnetFields):
    clear: list[str] = Field(default=[], max_length=6)


# ------------------------------------------------------------------ cohérence
def check_zone(type_: str, cfg: dict) -> None:
    allowed = set(COMMON) | set(PER_TYPE[type_])
    for k in ZONE_FIELDS:
        if cfg.get(k) not in (None, [], "") and k not in allowed:
            raise ValueError(f"« {k} » ne s'applique pas à une zone de type {type_}")
    for k in REQUIRED[type_]:
        if cfg.get(k) in (None, [], ""):
            raise ValueError(f"Une zone {type_} exige « {k} »")
    if cfg.get("exitnodes_primary") and cfg["exitnodes_primary"] not in (cfg.get("exitnodes") or []):
        raise ValueError("exitnodes_primary doit être un des exitnodes")


def check_subnet(cidr: str, cfg: dict) -> None:
    net = ipaddress.ip_network(cidr, strict=True)
    for k in ("gateway", "dhcp_dns_server"):
        if cfg.get(k) and ipaddress.ip_address(cfg[k]).version != net.version:
            raise ValueError(f"{k} : version d'IP différente du sous-réseau")
    if cfg.get("gateway") and ipaddress.ip_address(cfg["gateway"]) not in net:
        raise ValueError("La passerelle n'est pas dans le sous-réseau")
    for r in cfg.get("dhcp_range") or []:
        a, b = ipaddress.ip_address(r["start"]), ipaddress.ip_address(r["end"])
        if a not in net or b not in net or a.version != b.version or a > b:
            raise ValueError("Plage DHCP invalide ou hors du sous-réseau")
    if cfg.get("dhcp_range") and not cfg.get("gateway"):
        raise ValueError("Une plage DHCP exige une passerelle")


def subnet_id(zone: str, cidr: str) -> str:
    """Identifiant Proxmox d'un sous-réseau : `zone-adresse-préfixe`."""
    net = ipaddress.ip_network(cidr, strict=True)
    return f"{zone}-{net.network_address}-{net.prefixlen}"


# ------------------------------------------------------------------ lecture
def _s(v, n=100):
    return v if isinstance(v, str) and len(v) <= n and not any(ord(c) < 32 for c in v) else None


def _i(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else (int(v) if isinstance(v, str) and v.lstrip("-").isdigit() else None)


def _b(v):
    return bool(v) if v in (0, 1, True, False, "0", "1") else None


def _list(v):
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)][:64]
    return [x for x in v.split(",") if x][:64] if isinstance(v, str) else []


def _eff(r: dict) -> dict:
    """Valeurs en attente par-dessus les valeurs courantes (`pending=1`)."""
    p = r.get("pending")
    return {**r, **p} if isinstance(p, dict) else r


def _rows(raw):
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def shape_zones(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        e = _eff(r)
        z = r.get("zone")
        if not isinstance(z, str) or not ZONE_ID.fullmatch(z):
            continue
        d = {"zone": z, "type": r.get("type") if r.get("type") in ZONE_TYPES else None, "state": r.get("state") if r.get("state") in STATES else None,
             "digest": _s(r.get("digest"), 64)}
        for k in ZONE_FIELDS:
            wk = wire(k)
            v = e.get(wk)
            d[k] = _list(v) if k in LISTS else _b(v) if k in ("exitnodes_local_routing", "advertise_subnets", "disable_arp_nd_suppression") else _i(v) if k in ("mtu", "tag", "vxlan_port", "vrf_vxlan") else _s(v)
        out.append(d)
    return sorted(out, key=lambda x: x["zone"])


def shape_vnets(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        e = _eff(r)
        v = r.get("vnet")
        if not isinstance(v, str) or not VNET_ID.fullmatch(v):
            continue
        out.append({"vnet": v, "zone": _s(e.get("zone"), 8), "alias": _s(e.get("alias"), 256), "tag": _i(e.get("tag")), "vlanaware": _b(e.get("vlanaware")),
                    "isolate_ports": _b(e.get("isolate-ports")), "state": r.get("state") if r.get("state") in STATES else None, "digest": _s(r.get("digest"), 64)})
    return sorted(out, key=lambda x: x["vnet"])


def shape_subnets(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        e = _eff(r)
        cidr = _s(e.get("cidr") or e.get("network"), 50)
        sid = _s(r.get("subnet"), 60) or _s(r.get("id"), 60)
        if not sid or not SUBNET_ID.fullmatch(sid):
            continue
        rng = []
        for x in (e.get("dhcp-range") or []):
            if isinstance(x, dict):
                a, b = x.get("start-address"), x.get("end-address")
            elif isinstance(x, str):
                kv = dict(p.split("=", 1) for p in x.split(",") if "=" in p)
                a, b = kv.get("start-address"), kv.get("end-address")
            else:
                continue
            if isinstance(a, str) and isinstance(b, str):
                rng.append({"start": a[:45], "end": b[:45]})
        out.append({"subnet": sid, "cidr": cidr, "gateway": _s(e.get("gateway"), 45), "snat": _b(e.get("snat")), "dhcp_dns_server": _s(e.get("dhcp-dns-server"), 45),
                    "dnszoneprefix": _s(e.get("dnszoneprefix")), "dhcp_range": rng[:8], "state": r.get("state") if r.get("state") in STATES else None, "digest": _s(r.get("digest"), 64)})
    return sorted(out, key=lambda x: x["subnet"])


# ------------------------------------------------------------------ paramètres et verrous
def params_of(fields: dict, lists_as: str = ",") -> dict:
    p = {}
    for k, v in fields.items():
        if k == "dhcp_range":
            p["dhcp-range"] = [f"start-address={r['start']},end-address={r['end']}" for r in v]
        elif isinstance(v, list):
            p[wire(k)] = lists_as.join(v)
        elif isinstance(v, bool):
            p[wire(k)] = 1 if v else 0
        else:
            p[wire(k)] = v
    return p


def apply_locks(zones: list[dict], vnets: list[dict], routing: list[str] | None = None) -> dict:
    cut: list[str] = []
    if routing:
        cut.append(f"{', '.join(routing)} : contrôleurs ou fabrics de routage (BGP, EVPN, IS-IS, OSPF, OpenFabric) : une erreur peut isoler des nœuds")
    host = sorted(z["zone"] for z in zones if z["type"] not in (None, "simple") and z["state"] in ("new", "changed"))
    if host:
        cut.append(f"les zones {', '.join(host)} agissent sur le réseau des nœuds (VLAN, VXLAN, EVPN) : une erreur peut le couper")
    gone = sorted([z["zone"] for z in zones if z["state"] == "deleted"] + [v["vnet"] for v in vnets if v["state"] == "deleted"])
    if gone:
        cut.append(f"la suppression de {', '.join(gone)} retire les bridges correspondants : les machines branchées perdent leur réseau")
    return {"cut": cut, "live": ["appliquer pousse la configuration SDN sur tous les nœuds du cluster"], "inert": False}
