"""Ceph en LECTURE SEULE : mise en forme tolérante des réponses de Proxmox, et masquage des secrets.

Les formes décrites ici viennent de la connaissance de l'API Proxmox, pas d'un essai réel (le cluster de test n'a pas de
Ceph). Chaque fonction doit donc tout accepter : une valeur absente ou d'un type inattendu devient `None` ou `[]`, jamais
une exception qui ferait tomber toute la page.
"""
import math
import re

from .storagespec import _int, _str

HEALTH = ("HEALTH_OK", "HEALTH_WARN", "HEALTH_ERR")
MAX_DEPTH = 12                 # profondeur maximale de l'arbre des OSD (racine, rack, hôte, OSD…)
MAX_NODES = 5000               # garde-fou contre une réponse démesurée
MAX_CONF_BYTES = 200_000
MAX_LINE = 500

# Tout ce qui ressemble à un secret est masqué : clé, secret, mot de passe, jeton. Appliqué au `ceph.conf`, à la base de
# configuration et au journal, même si Ceph n'y met normalement pas de secret (les trousseaux sont des fichiers à part).
_SECRET_NAME = re.compile(r".*(?:key|secret|passw|token|credential).*", re.I | re.S)    # `fullmatch` : jamais `search` (garde-fou du dépôt)
_SECRET_PAIR = re.compile(r"(?i)\b(\w*(?:key|secret|passw\w*|token|credential)\w*)(\s*[=:]\s*)\S+")
MASK = "[masqué]"


def redact(text: str) -> str:
    return _SECRET_PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        n = float(v) if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip() != "") else None
    except ValueError:
        return None
    return n if n is not None and math.isfinite(n) else None


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _health(v) -> str:
    return v if v in HEALTH else "UNKNOWN"


def _bool(v) -> bool | None:
    """`1`, `true`, `"1"` -> vrai ; `0`, `false`, `"0"` -> faux ; le reste -> inconnu (None), jamais deviné."""
    if v in (1, True, "1", "true", "True"):
        return True
    if v in (0, False, "0", "false", "False"):
        return False
    return None


# ------------------------------------------------------------------ état et santé

def shape_status(data) -> dict:
    """`ceph -s` : santé et ses messages, OSD, moniteurs, gestionnaire, groupes de placement, usage, débit."""
    d = _dict(data)
    health = _dict(d.get("health"))
    checks = []
    for code, c in sorted(_dict(health.get("checks")).items()):
        c = _dict(c)
        summary = _dict(c.get("summary"))
        checks.append({
            "code": str(code)[:80], "severity": _health(c.get("severity")),
            "message": _str(summary.get("message")) or _str(c.get("message")) or "",
            "count": _int(summary.get("count")), "muted": bool(c.get("muted")),
            "details": [m[:MAX_LINE] for m in (_str(_dict(x).get("message")) for x in _list(c.get("detail"))[:50]) if m],
        })
    osdmap = _dict(d.get("osdmap"))
    osdmap = _dict(osdmap.get("osdmap")) or osdmap          # certaines versions imbriquent `osdmap` dans `osdmap`
    pg = _dict(d.get("pgmap"))
    states = [{"state": _str(_dict(s).get("state_name")) or "?", "count": _int(_dict(s).get("count")) or 0}
              for s in _list(pg.get("pgs_by_state"))[:100]]
    total, used, avail = _int(pg.get("bytes_total")), _int(pg.get("bytes_used")), _int(pg.get("bytes_avail"))
    mgr = _dict(d.get("mgrmap"))
    quorum = [q for q in _list(d.get("quorum_names")) if isinstance(q, str)]
    return {
        "health": {"status": _health(health.get("status")), "checks": checks},
        "osds": {"total": _int(osdmap.get("num_osds")), "up": _int(osdmap.get("num_up_osds")), "in": _int(osdmap.get("num_in_osds"))},
        "mons": {"total": _int(_dict(d.get("monmap")).get("num_mons")) if "monmap" in d else None, "quorum": quorum},
        "mgr": {"active": _str(mgr.get("active_name")), "standbys": len(_list(mgr.get("standbys"))), "available": _bool(mgr.get("available"))},
        "pgs": {"total": _int(pg.get("num_pgs")), "states": states,
                "all_clean": bool(states) and all(s["state"] == "active+clean" for s in states)},
        "usage": {"total": total, "used": used, "avail": avail,
                  "percent": round(used / total * 100, 1) if used is not None and total else None},
        "io": {"read_bytes_sec": _int(pg.get("read_bytes_sec")), "write_bytes_sec": _int(pg.get("write_bytes_sec")),
               "read_ops": _int(pg.get("read_op_per_sec")), "write_ops": _int(pg.get("write_op_per_sec"))},
    }


# ------------------------------------------------------------------ moniteurs et gestionnaires

def shape_mons(data) -> list[dict]:
    out = []
    for m in _list(data):
        m = _dict(m)
        name = _str(m.get("name"))
        if not name:
            continue
        out.append({"name": name, "host": _str(m.get("host")), "addr": _str(m.get("addr")) or _str(m.get("public_addr")),
                    "rank": _int(m.get("rank")), "in_quorum": _bool(m.get("quorum")),
                    "state": _str(m.get("state")), "version": _str(m.get("ceph_version_short")) or _str(m.get("ceph_version"))})
    return sorted(out, key=lambda x: (x["rank"] is None, x["rank"] or 0, x["name"]))


def shape_mgrs(data) -> list[dict]:
    out = []
    for m in _list(data):
        m = _dict(m)
        name = _str(m.get("name"))
        if not name:
            continue
        out.append({"name": name, "host": _str(m.get("host")), "addr": _str(m.get("addr")), "state": _str(m.get("state")),
                    "version": _str(m.get("ceph_version_short")) or _str(m.get("ceph_version"))})
    return sorted(out, key=lambda x: x["name"])


# ------------------------------------------------------------------ OSD

def shape_osds(data) -> dict:
    """L'arbre CRUSH que renvoie Proxmox (racine, hôtes, OSD) est aplati en une liste d'OSD avec leur hôte."""
    d = _dict(data)
    osds: list[dict] = []
    seen = 0
    stack = [(_dict(d.get("root")), None, 0)]
    while stack:
        node, host, depth = stack.pop()
        seen += 1
        if seen > MAX_NODES or depth > MAX_DEPTH:
            continue
        kind = _str(node.get("type"))
        if kind == "osd":
            oid = _int(node.get("id"))
            osds.append({
                "id": oid, "name": _str(node.get("name")) or (f"osd.{oid}" if oid is not None else "?"), "host": host,
                "up": (_str(node.get("status")) or "").lower() == "up" if node.get("status") is not None else None,
                "in": _bool(node.get("in")), "device_class": _str(node.get("device_class")),
                "crush_weight": _num(node.get("crush_weight")), "reweight": _num(node.get("reweight")),
                "percent_used": _num(node.get("percent_used")), "used": _int(node.get("bytes_used")),
                "total": _int(node.get("total_space")), "pgs": _int(node.get("pgs")), "version": _str(node.get("version")),
            })
            continue
        child_host = _str(node.get("name")) if kind == "host" else host
        for c in _list(node.get("children")):
            stack.append((_dict(c), child_host, depth + 1))
    osds.sort(key=lambda o: (o["id"] is None, o["id"] or 0))
    flags = [f.strip()[:40] for f in (_str(d.get("flags")) or "").split(",") if f.strip()]
    return {"osds": osds, "flags": flags, "summary": {
        "total": len(osds), "up": sum(1 for o in osds if o["up"] is True), "in": sum(1 for o in osds if o["in"] is True)}}


# ------------------------------------------------------------------ pools

def shape_pools(data) -> list[dict]:
    """Pools avec leurs réglages de redondance. Les avertissements ne font que SIGNALER (jamais d'écriture) un réglage
    dangereux : une seule copie, ou `min_size` à 1 qui laisse écrire sur une seule copie."""
    out = []
    for p in _list(data):
        p = _dict(p)
        name = _str(p.get("pool_name"))
        if not name:
            continue
        size, min_size = _int(p.get("size")), _int(p.get("min_size"))
        warnings = []
        if size is not None and size < 2:
            warnings.append("Une seule copie des données (size inférieur à 2) : la panne d'un disque fait perdre des données.")
        elif size is not None and min_size == 1:
            warnings.append("min_size à 1 : Ceph accepte d'écrire sur une seule copie.")
        if size is not None and min_size is not None and min_size > size:
            warnings.append("min_size supérieur à size : les écritures seront bloquées.")
        out.append({
            "name": name, "id": _int(p.get("pool")), "type": _str(p.get("type")), "size": size, "min_size": min_size,
            "pg_num": _int(p.get("pg_num")), "crush_rule": _str(p.get("crush_rule_name")),
            "autoscale": _str(p.get("pg_autoscale_mode")), "used": _int(p.get("bytes_used")),
            "percent_used": _num(p.get("percent_used")),
            "applications": sorted(str(a)[:40] for a in _dict(p.get("application_metadata")).keys()),
            "warnings": warnings,
        })
    return sorted(out, key=lambda x: x["name"])


# ------------------------------------------------------------------ CephFS et MDS

def shape_fs(fs, mds) -> dict:
    filesystems = []
    for f in _list(fs):
        f = _dict(f)
        name = _str(f.get("name"))
        if name:
            pools = [p for p in (_list(f.get("data_pools")) or [f.get("data_pool")]) if isinstance(p, str)]
            filesystems.append({"name": name, "metadata_pool": _str(f.get("metadata_pool")), "data_pools": pools})
    servers = []
    for m in _list(mds):
        m = _dict(m)
        name = _str(m.get("name"))
        if name:
            servers.append({"name": name, "host": _str(m.get("host")), "addr": _str(m.get("addr")),
                            "rank": _int(m.get("rank")), "state": _str(m.get("state"))})
    return {"filesystems": sorted(filesystems, key=lambda x: x["name"]), "mds": sorted(servers, key=lambda x: x["name"])}


# ------------------------------------------------------------------ configuration et journal

def shape_conf_raw(raw) -> dict:
    """`ceph.conf` en texte, secrets masqués ligne par ligne, taille bornée."""
    text = raw if isinstance(raw, str) else ""
    truncated = len(text.encode("utf-8", "ignore")) > MAX_CONF_BYTES
    if truncated:
        text = text.encode("utf-8", "ignore")[:MAX_CONF_BYTES].decode("utf-8", "ignore")
    return {"text": "\n".join(redact(line)[:MAX_LINE] for line in text.splitlines()), "truncated": truncated}


def shape_conf_db(data) -> list[dict]:
    out = []
    for e in _list(data)[:2000]:
        e = _dict(e)
        name = _str(e.get("name"))
        if not name:
            continue
        value = _str(e.get("value")) if not isinstance(e.get("value"), (dict, list)) else None
        out.append({"section": _str(e.get("section")) or "global", "name": name[:120], "level": _str(e.get("level")),
                    "value": MASK if value is not None and _SECRET_NAME.fullmatch(name) else (value or "")[:MAX_LINE] if value is not None else None,
                    "runtime": _bool(e.get("can_update_at_runtime"))})
    return sorted(out, key=lambda x: (x["section"], x["name"]))


def shape_log(data) -> list[dict]:
    out = []
    for e in _list(data)[:1000]:
        e = _dict(e)
        text = _str(e.get("t"))
        if text is None:
            continue
        out.append({"n": _int(e.get("n")), "text": redact(text)[:MAX_LINE]})
    return out


# ------------------------------------------------------------------ règles CRUSH

def shape_rules(data) -> list[dict]:
    """Règles de placement (`/nodes/{n}/ceph/rules`) : sert à proposer et à VALIDER `crush_rule` à la création d'un pool."""
    out: dict[str, dict] = {}
    for r in _list(data):
        r = _dict(r)
        name = _str(r.get("name")) or _str(r.get("rule_name"))
        if name:
            out[name] = {"name": name, "id": _int(r.get("rule_id") if r.get("rule_id") is not None else r.get("id"))}
    return sorted(out.values(), key=lambda x: x["name"])
