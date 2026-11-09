"""Haute disponibilité (HA) et réplication Proxmox : mise en forme tolérante, en liste blanche, textes bornés (LECTURE).

Rien n'est écrit ici. Particularités du cluster réel (2 nœuds) : le quorum est fragile, et activer la HA arme un chien de garde qui fait redémarrer un nœud qui perd le
quorum ; les groupes HA ont été remplacés par des règles (`/cluster/ha/groups` répond « migrated to rules »).
"""
import re

from .networkspec import NAME, _b, _choice, _int, _rows, _t

SID = re.compile(r"^(vm|ct):[1-9][0-9]{2,8}$")
NODE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,62})$")
RULE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
JOB = re.compile(r"^[1-9][0-9]{2,8}-[0-9]{1,9}$")
STATES = ("started", "stopped", "enabled", "disabled", "ignored")
STATUS_TYPES = ("quorum", "master", "lrm", "service", "fencing")
RULE_TYPES = ("node-affinity", "resource-affinity")


def _nodes(v) -> list[dict]:
    """Liste de nœuds d'une règle : `enzo:2,enzo2` -> [{node, priority}]."""
    out = []
    for part in v.split(",") if isinstance(v, str) else []:
        n, _, p = part.partition(":")
        if NODE.fullmatch(n) and (not p or p.isdigit()):
            out.append({"node": n, "priority": int(p) if p else None})
    return out[:32]


def _sids(v) -> list[str]:
    return [s for s in (v.split(",") if isinstance(v, str) else []) if SID.fullmatch(s)][:64]


def shape_ha_status(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        typ = _choice(r.get("type"), STATUS_TYPES)
        if typ is None:
            continue
        node = r.get("node")
        out.append({"type": typ, "id": _t(r.get("id"), 60), "node": node if isinstance(node, str) and NODE.fullmatch(node) else None, "status": _t(r.get("status"), 200),
                    "state": _choice(r.get("state"), STATES), "sid": r.get("sid") if isinstance(r.get("sid"), str) and SID.fullmatch(r["sid"]) else None,
                    "request_state": _choice(r.get("request_state"), STATES), "quorate": _b(r.get("quorate")), "armed_state": _t(r.get("armed-state"), 40),
                    "max_relocate": _int(r.get("max_relocate")), "max_restart": _int(r.get("max_restart")), "timestamp": _int(r.get("timestamp"))})
    return out


def shape_ha_resources(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        sid = r.get("sid")
        if not isinstance(sid, str) or not SID.fullmatch(sid):
            continue
        out.append({"sid": sid, "type": _choice(r.get("type"), ("vm", "ct")), "state": _choice(r.get("state"), STATES), "max_restart": _int(r.get("max_restart")),
                    "max_relocate": _int(r.get("max_relocate")), "failback": _b(r.get("failback")), "comment": _t(r.get("comment"), 500), "digest": _t(r.get("digest"), 64)})
    return sorted(out, key=lambda x: x["sid"])


def shape_ha_rules(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        rule = r.get("rule")
        typ = _choice(r.get("type"), RULE_TYPES)
        if not isinstance(rule, str) or not RULE.fullmatch(rule) or typ is None:
            continue
        out.append({"rule": rule, "type": typ, "resources": _sids(r.get("resources")), "nodes": _nodes(r.get("nodes")), "strict": _b(r.get("strict")),
                    "affinity": _choice(r.get("affinity"), ("positive", "negative")), "disable": _b(r.get("disable")), "comment": _t(r.get("comment"), 500),
                    "digest": _t(r.get("digest"), 64)})
    return sorted(out, key=lambda x: x["rule"])


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def shape_jobs(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        i = r.get("id")
        if not isinstance(i, str) or not JOB.fullmatch(i):
            continue
        out.append({"id": i, "guest": _int(r.get("guest")), "type": _choice(r.get("type"), ("local",)), "source": r.get("source") if isinstance(r.get("source"), str) and NODE.fullmatch(r["source"]) else None,
                    "target": r.get("target") if isinstance(r.get("target"), str) and NODE.fullmatch(r["target"]) else None, "schedule": _t(r.get("schedule"), 128),
                    "rate": _num(r.get("rate")), "disable": _b(r.get("disable")), "comment": _t(r.get("comment"), 500), "digest": _t(r.get("digest"), 64),
                    "remove_job": _choice(r.get("remove_job"), ("local", "full"))})
    return sorted(out, key=lambda x: x["id"])


def shape_job_status(raw) -> list[dict]:
    """État des jobs d'un nœud : dernière synchronisation, prochaine, durée, échecs, erreur."""
    out = []
    for r in _rows(raw):
        i = r.get("id")
        if not isinstance(i, str) or not JOB.fullmatch(i):
            continue
        out.append({"id": i, "guest": _int(r.get("guest")), "target": r.get("target") if isinstance(r.get("target"), str) and NODE.fullmatch(r["target"]) else None,
                    "last_sync": _int(r.get("last_sync")), "last_try": _int(r.get("last_try")), "next_sync": _int(r.get("next_sync")), "duration": _num(r.get("duration")),
                    "fail_count": _int(r.get("fail_count")), "error": _t(r.get("error"), 500), "disable": _b(r.get("disable")), "schedule": _t(r.get("schedule"), 128)})
    return sorted(out, key=lambda x: x["id"])


def shape_log(raw) -> list[str]:
    """Journal d'un job (liste de `{n, t}`) : seulement le texte, borné."""
    return [t for r in _rows(raw) if (t := _t(r.get("t"), 500)) is not None][:2000]


__all__ = ["NAME", "SID", "JOB", "NODE", "RULE"]
