"""Cluster Proxmox (corosync) en LECTURE : mise en forme tolérante, en liste blanche, textes bornés.

Sources : `/cluster/status` (nœuds, quorum), `/cluster/config/nodes` (nœuds corosync), `/cluster/config/totem`, `/cluster/config/qdevice`. Le schéma officiel de ces trois dernières
réponses est vide : on n'en garde que des champs connus (valeurs validées) et jamais une valeur inattendue. Rien d'autre que ces champs ne sort ; aucun secret n'existe dans ces réponses,
et le jeton d'authentification de corosync (`authkey`) n'est jamais lu.
Créer, joindre ou retirer un nœud : NON implémenté (voir `docs/m10-cluster.md`).
"""
import re

from .networkspec import _b, _int, _rows

NODE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,62})$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,62}$")
ADDR = re.compile(r"^[A-Za-z0-9._:\-]{1,255}$")
FP = re.compile(r"^([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$")
RING = re.compile(r"^ring([0-7])_addr$")
KEY = re.compile(r"^[A-Za-z0-9_.\- ]{1,60}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _str(v, pattern):
    return v if isinstance(v, str) and pattern.fullmatch(v) else None


def _short(v, n: int) -> str | None:
    """Texte court : AUCUN caractère de contrôle (saut de ligne compris), borné ; autre chose qu'un texte -> None."""
    return CONTROL.sub("", v)[:n] if isinstance(v, str) else None


def _num(v):
    """Entier, ou chaîne de chiffres (corosync renvoie `"2"`)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    return int(v) if isinstance(v, str) and v.isdigit() and len(v) < 10 else None


def shape_status(raw) -> dict:
    """`/cluster/status` : le cluster (nom, quorum, version de la configuration) et ses nœuds (id corosync, en ligne, adresse, nœud interrogé)."""
    rows = _rows(raw)
    cluster = next((r for r in rows if r.get("type") == "cluster"), None)
    nodes = [{"name": _str(r.get("name"), NODE), "nodeid": _int(r.get("nodeid")), "online": _b(r.get("online")), "ip": _str(r.get("ip"), ADDR), "local": bool(_b(r.get("local")))}
             for r in rows if r.get("type") == "node" and _str(r.get("name"), NODE)]
    return {"name": _str(cluster.get("name"), NAME) if cluster else None, "quorate": _b(cluster.get("quorate")) if cluster else None,
            "version": _int(cluster.get("version")) if cluster else None, "nodes_total": _int(cluster.get("nodes")) if cluster else None,
            "clustered": cluster is not None, "nodes": sorted(nodes, key=lambda n: (n["nodeid"] is None, n["nodeid"] or 0, n["name"]))}


def shape_corosync_nodes(raw) -> list[dict]:
    out = []
    for r in _rows(raw):
        name = _str(r.get("name"), NODE) or _str(r.get("node"), NODE)
        if not name:
            continue
        links = sorted(({"link": int(m.group(1)), "addr": a} for k, v in r.items() if (m := RING.fullmatch(k)) and (a := _str(v, ADDR))), key=lambda x: x["link"])
        out.append({"name": name, "nodeid": _num(r.get("nodeid")), "votes": _num(r.get("quorum_votes")), "links": links, "pve_addr": _str(r.get("pve_addr"), ADDR),
                    "fingerprint": _str(r.get("pve_fp"), FP)})
    return sorted(out, key=lambda n: (n["nodeid"] is None, n["nodeid"] or 0, n["name"]))


def shape_totem(raw) -> dict | None:
    if not isinstance(raw, dict) or not raw:
        return None
    iface = raw.get("interface")
    links = sorted(int(k) for k in iface if isinstance(k, str) and k.isdigit() and len(k) < 3) if isinstance(iface, dict) else []
    return {"cluster_name": _str(raw.get("cluster_name"), NAME), "config_version": _num(raw.get("config_version")), "ip_version": _short(raw.get("ip_version"), 20),
            "link_mode": _short(raw.get("link_mode"), 20), "secauth": _short(raw.get("secauth"), 10), "transport": _short(raw.get("transport"), 20), "links": links}


def shape_qdevice(raw) -> dict:
    """État du QDevice : objet libre côté Proxmox ; on n'expose que des couples clé / court texte (20 au plus)."""
    info: dict[str, str | None] = {}
    if isinstance(raw, dict):
        for k, v in list(raw.items())[:20]:
            if isinstance(k, str) and KEY.fullmatch(k) and isinstance(v, (str, int, float)) and not isinstance(v, bool):
                info[k] = _short(str(v), 200)
    return {"configured": bool(info), "info": info}


def shape_join(raw) -> dict | None:
    """Informations pour joindre un nœud (équivalent du bouton « Join Information » de Proxmox) : nœud à contacter, son adresse et son empreinte. Rien de secret."""
    if not isinstance(raw, dict) or not raw:
        return None
    nodes = shape_corosync_nodes(raw.get("nodelist"))
    pref = _str(raw.get("preferred_node"), NODE)
    node = next((n for n in nodes if n["name"] == pref), None)
    addr = (node["pve_addr"] or (node["links"][0]["addr"] if node["links"] else None)) if node else None
    return {"preferred_node": pref, "address": addr, "fingerprint": node["fingerprint"] if node else None, "nodes": len(nodes)}


def merge_nodes(status_nodes: list[dict], corosync: list[dict], join_nodes: list[dict] | None = None) -> list[dict]:
    """Un nœud par ligne : état (en ligne, adresse) du statut + votes et liens de corosync ; l'empreinte vient de corosync, sinon de la liste de jonction (constaté en réel : `/cluster/config/nodes` ne la donne pas)."""
    by_name = {n["name"]: n for n in corosync}
    fp_join = {n["name"]: n["fingerprint"] for n in join_nodes or []}
    out = []
    for s in status_nodes:
        c = by_name.pop(s["name"], None)
        out.append({"name": s["name"], "nodeid": s["nodeid"] if s["nodeid"] is not None else (c or {}).get("nodeid"), "online": s["online"], "ip": s["ip"], "local": s["local"],
                    "votes": (c or {}).get("votes"), "links": (c or {}).get("links", []), "fingerprint": (c or {}).get("fingerprint") or fp_join.get(s["name"])})
    for c in by_name.values():                                     # dans corosync mais absent du statut
        out.append({"name": c["name"], "nodeid": c["nodeid"], "online": None, "ip": c["pve_addr"], "local": False, "votes": c["votes"], "links": c["links"], "fingerprint": c["fingerprint"] or fp_join.get(c["name"])})
    return out
