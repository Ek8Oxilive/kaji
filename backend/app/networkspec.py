"""Réseau d'un nœud et pare-feu Proxmox (lecture seule) : mise en forme tolérante, en liste blanche, textes bornés.

Rien n'est écrit ici. Les écritures réseau et pare-feu sont à risque élevé (une erreur peut couper l'accès à tout le cluster) et ne se valident
que sur un banc d'essai imbriqué : voir `docs/m7-reseau-firewall.md`.
"""
import re

from .storagespec import _int, _str

IFACE = re.compile(r"^[A-Za-z0-9._:\-]{1,40}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
TOKEN = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
TYPES = ("bridge", "bond", "eth", "alias", "vlan", "fabric", "OVSBridge", "OVSBond", "OVSPort", "OVSIntPort", "vnet", "unknown")
METHODS = ("loopback", "dhcp", "manual", "static", "auto")
LOG_LEVELS = ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug", "nolog")
POLICIES = ("ACCEPT", "REJECT", "DROP")
MAX_ROWS = 1000
MAX_TEXT = 200
MAX_CHANGES = 20000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _t(v, n: int = MAX_TEXT) -> str | None:
    """Texte borné, sans caractère de contrôle ; autre chose qu'un texte -> None."""
    return _CONTROL.sub("", v)[:n] if isinstance(v, str) else None


def _b(v) -> bool | None:
    if isinstance(v, bool):
        return v
    return {1: True, "1": True, 0: False, "0": False}.get(v)


def _rows(raw) -> list[dict]:
    return [r for r in raw if isinstance(r, dict)][:MAX_ROWS] if isinstance(raw, list) else []


def _words(v) -> list[str]:
    return [w for w in v.split() if IFACE.fullmatch(w)][:64] if isinstance(v, str) else []


def _choice(v, allowed):
    return v if v in allowed else None


# ------------------------------------------------------------------ réseau
def shape_interfaces(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        name = _str(r.get("iface"))
        if not name or not IFACE.fullmatch(name):
            continue
        mtu = _int(r.get("mtu"))
        out.append({
            "iface": name, "type": r.get("type") if r.get("type") in TYPES else "unknown", "active": _b(r.get("active")), "autostart": _b(r.get("autostart")),
            "method": _choice(r.get("method"), METHODS), "method6": _choice(r.get("method6"), METHODS),
            "address": _t(r.get("address"), 45), "netmask": _t(r.get("netmask"), 45), "cidr": _t(r.get("cidr"), 60), "gateway": _t(r.get("gateway"), 45),
            "address6": _t(r.get("address6"), 60), "cidr6": _t(r.get("cidr6"), 70), "gateway6": _t(r.get("gateway6"), 60),
            "mtu": mtu if mtu is not None and 68 <= mtu <= 65535 else None,
            "bridge_ports": _words(r.get("bridge_ports")), "bridge_vlan_aware": _b(r.get("bridge_vlan_aware")), "bridge_vids": _t(r.get("bridge_vids"), 100),
            "slaves": _words(r.get("slaves")), "bond_mode": _t(r.get("bond_mode"), 30),
            "vlan_id": _int(r.get("vlan-id")), "vlan_raw_device": _t(r.get("vlan-raw-device"), 40),
            "comments": _t(r.get("comments")),
            # Une interface qui porte la passerelle par défaut est vraisemblablement celle de l'administration : y toucher peut couper l'accès.
            "has_gateway": bool(_t(r.get("gateway"), 45) or _t(r.get("gateway6"), 60)),
        })
    order = {t: i for i, t in enumerate(TYPES)}
    return sorted(out, key=lambda i: (order.get(i["type"], 99), i["iface"]))


def shape_network(envelope) -> dict:
    env = envelope if isinstance(envelope, dict) else {}
    changes = env.get("changes")
    text = changes[:MAX_CHANGES] if isinstance(changes, str) else None
    return {"interfaces": shape_interfaces(env.get("data")), "changes": text, "pending": bool(text and text.strip())}


# ------------------------------------------------------------------ pare-feu
OPTION_KINDS: dict[str, dict[str, object]] = {
    "cluster": {"enable": "bool", "ebtables": "bool", "log_ratelimit": "text", "policy_forward": POLICIES[::2], "policy_in": POLICIES, "policy_out": POLICIES},
    "node": {"enable": "bool", "log_level_forward": LOG_LEVELS, "log_level_in": LOG_LEVELS, "log_level_out": LOG_LEVELS, "log_nf_conntrack": "bool", "ndp": "bool",
             "nf_conntrack_allow_invalid": "bool", "nf_conntrack_helpers": "text", "nf_conntrack_max": "int", "nf_conntrack_tcp_timeout_established": "int",
             "nf_conntrack_tcp_timeout_syn_recv": "int", "nftables": "bool", "nosmurfs": "bool", "protection_synflood": "bool", "protection_synflood_burst": "int",
             "protection_synflood_rate": "int", "smurf_log_level": LOG_LEVELS, "tcp_flags_log_level": LOG_LEVELS, "tcpflags": "bool"},
    "guest": {"dhcp": "bool", "enable": "bool", "ipfilter": "bool", "log_level_in": LOG_LEVELS, "log_level_out": LOG_LEVELS, "macfilter": "bool", "ndp": "bool",
              "policy_in": POLICIES, "policy_out": POLICIES, "radv": "bool"},
}


def shape_options(level: str, raw) -> dict:
    """Options du pare-feu d'un niveau (`cluster`, `node`, `guest`), en liste blanche ; le `digest` sert plus tard aux écritures."""
    r = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for key, kind in OPTION_KINDS[level].items():
        if key not in r:
            continue
        v = r[key]
        out[key] = _b(v) if kind == "bool" else _int(v) if kind == "int" else _t(v, 100) if kind == "text" else _choice(v, kind)
    d = r.get("digest")
    out["digest"] = d if isinstance(d, str) and re.fullmatch(r"[0-9a-f]{40}", d) else None
    return out


def shape_rules(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        pos = _int(r.get("pos"))
        if pos is None or pos < 0:
            continue
        act = r.get("action")                                   # validé AVANT toute troncature : une valeur trop longue est écartée, jamais raccourcie
        out.append({
            "pos": pos, "type": _choice(r.get("type"), ("in", "out", "group", "forward")), "action": act if isinstance(act, str) and TOKEN.fullmatch(act) else None,
            "enable": _b(r.get("enable")), "source": _t(r.get("source")), "dest": _t(r.get("dest")), "proto": _t(r.get("proto"), 30), "sport": _t(r.get("sport"), 60),
            "dport": _t(r.get("dport"), 60), "iface": _t(r.get("iface"), 40), "macro": _t(r.get("macro"), 40), "log": _choice(r.get("log"), LOG_LEVELS),
            "icmp_type": _t(r.get("icmp-type"), 40), "ipversion": _choice(_int(r.get("ipversion")), (4, 6)), "comment": _t(r.get("comment")),
        })
    return sorted(out, key=lambda x: x["pos"])


def shape_aliases(raw) -> list[dict]:
    out = [{"name": n, "cidr": _t(r.get("cidr"), 60), "comment": _t(r.get("comment"))} for r in _rows(raw) if (n := _str(r.get("name"))) and NAME.fullmatch(n)]
    return sorted(out, key=lambda a: a["name"])


def shape_named(raw, key: str) -> list[dict]:
    """IPSets (`name`) ou groupes de sécurité (`group`) : nom et commentaire."""
    out = [{"name": n, "comment": _t(r.get("comment"))} for r in _rows(raw) if (n := _str(r.get(key))) and NAME.fullmatch(n)]
    return sorted(out, key=lambda a: a["name"])


def shape_ipset_entries(raw) -> list[dict]:
    out = [{"cidr": c, "comment": _t(r.get("comment")), "nomatch": bool(_b(r.get("nomatch")))} for r in _rows(raw) if (c := _t(r.get("cidr"), 60))]
    return sorted(out, key=lambda e: e["cidr"])
