"""Alertes (lot #413) : validation des règles et lecture des mesures. Fonctions pures, testables sans Proxmox ni horloge.

Types de règle : `cpu` et `mem` (% d'un nœud en ligne, pendant `minutes`), `storage` (% utilisé d'un stockage actif, pendant `minutes`), `node_offline` (nœud qui n'est pas
« online », pendant `minutes`), `task_failed` (chaque tâche terminée en échec, une alerte par tâche).
Tout ce qui vient de Proxmox est traité comme non fiable : types vérifiés, valeurs bornées, noms assainis.
"""
import re

from pydantic import BaseModel, Field, StrictBool, StrictInt

KINDS = ("cpu", "mem", "storage", "node_offline", "task_failed")
THRESHOLD_KINDS = ("cpu", "mem", "storage")
MAX_RULES_PER_CONNECTION = 50
NAME = re.compile(r"^[^\x00-\x1f\x7f]{3,80}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class RuleBody(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    kind: str = Field(pattern=r"^(cpu|mem|storage|node_offline|task_failed)$")
    threshold: StrictInt = Field(default=0, ge=0, le=100)
    minutes: StrictInt = Field(default=5, ge=1, le=120)
    enabled: StrictBool = True
    webhook_url: str | None = Field(default=None, max_length=500)          # écriture seule : jamais renvoyée
    clear_webhook: StrictBool = False


def check_rule(b: RuleBody) -> str | None:
    """Message d'erreur, ou None. Un seuil est obligatoire (1 à 100) pour cpu, mem, storage ; sans objet pour les autres."""
    if not NAME.fullmatch(b.name):
        return "Nom invalide (3 à 80 caractères, sans caractère de contrôle)"
    if b.kind in THRESHOLD_KINDS and not 1 <= b.threshold <= 100:
        return "Seuil obligatoire : 1 à 100 (%)"
    if b.kind not in THRESHOLD_KINDS and b.threshold != 0:
        return "Ce type de règle n'a pas de seuil"
    if b.webhook_url is not None and b.clear_webhook:
        return "Adresse du webhook et retrait demandés en même temps"
    return None


def clean(v, limit: int) -> str:
    return _CONTROL.sub(" ", v)[:limit] if isinstance(v, str) else ""


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def pct(used, total) -> int | None:
    u, t = _num(used), _num(total)
    return None if u is None or t is None or t <= 0 else min(100, round(u * 100 / t))


def read_measures(resources) -> dict:
    """`{nodes: {nom: {online, cpu, mem}}, storages: {« stockage@nœud »: pct}}` d'après `/cluster/resources` (entrées illisibles ignorées)."""
    nodes: dict[str, dict] = {}
    storages: dict[str, int] = {}
    for r in (resources if isinstance(resources, list) else [])[:5000]:
        if not isinstance(r, dict):
            continue
        if r.get("type") == "node" and isinstance(r.get("node"), str) and r["node"]:
            name = clean(r["node"], 63)
            cpu = _num(r.get("cpu"))
            nodes[name] = {"online": r.get("status") == "online", "cpu": None if cpu is None else min(100, round(cpu * 100)), "mem": pct(r.get("mem"), r.get("maxmem"))}
        elif r.get("type") == "storage" and isinstance(r.get("storage"), str) and r.get("status") == "available":
            p = pct(r.get("disk"), r.get("maxdisk"))
            if p is not None:
                storages[f"{clean(r['storage'], 40)}@{clean(r.get('node'), 30)}"] = p
    return {"nodes": nodes, "storages": storages}


def breaches(kind: str, threshold: int, m: dict) -> dict[str, int]:
    """`{sujet: valeur}` des sujets qui dépassent le seuil (ou, pour `node_offline`, qui sont hors ligne : valeur 0)."""
    if kind == "cpu":
        return {n: v["cpu"] for n, v in m["nodes"].items() if v["online"] and v["cpu"] is not None and v["cpu"] >= threshold}
    if kind == "mem":
        return {n: v["mem"] for n, v in m["nodes"].items() if v["online"] and v["mem"] is not None and v["mem"] >= threshold}
    if kind == "storage":
        return {s: v for s, v in m["storages"].items() if v >= threshold}
    if kind == "node_offline":
        return {n: 0 for n, v in m["nodes"].items() if not v["online"]}
    return {}


def failed_tasks(tasks, cursor: int) -> list[dict]:
    """Tâches terminées en échec après `cursor` (epoch), plus anciennes d'abord. `OK` et `WARNINGS…` ne sont pas des échecs ; une tâche en cours n'a pas de `status`."""
    out = []
    for t in (tasks if isinstance(tasks, list) else [])[:2000]:
        if not isinstance(t, dict):
            continue
        end, st = t.get("endtime"), t.get("status")
        if isinstance(end, int) and not isinstance(end, bool) and end > cursor and isinstance(st, str) and st != "OK" and not st.startswith("WARNINGS"):
            out.append({"end": end, "type": clean(t.get("type"), 30) or "?", "node": clean(t.get("node"), 40), "id": clean(t.get("id"), 30), "status": clean(st, 80)})
    return sorted(out, key=lambda x: x["end"])
