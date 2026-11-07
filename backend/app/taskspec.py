"""Journal des tâches Proxmox (lecture seule) : mise en forme tolérante des listes de tâches.

Une tâche en cours n'a ni `status` ni `endtime`. Le texte d'état d'une tâche échouée est un message libre de Proxmox : il est
borné et n'est jamais interprété.
"""
import re

from .routers.actions import UPID
from .storagespec import _int, _iso, _str

TYPE_FILTER = re.compile(r"[a-z0-9_]{1,40}")        # `typefilter` : nom de type de tâche (`qmstart`, `vzdump`…)
MAX_STATUS_TEXT = 200


def task_state(status: str | None, ended: bool) -> str:
    """`running` (ni fin ni état, ou état `RUNNING` : c'est ce que Proxmox renvoie pour une tâche active), `ok`, `warning`
    (« WARNINGS: n », tâche réussie avec avertissements) ou `error`. Une tâche qui a une fin ne peut pas être « en cours »."""
    if status is not None and status.upper() == "RUNNING":
        return "running" if not ended else "error"
    if status is None:
        return "running" if not ended else "error"      # fin sans état lisible : jamais « ok » par défaut
    if status == "OK":
        return "ok"
    if status.startswith("WARNINGS"):
        return "warning"
    return "error"


def shape_task(row, node_hint: str, conn_user: str | None, conn_token: str | None) -> dict | None:
    """Une tâche, ou `None` si l'entrée est inexploitable (UPID absent ou de forme inattendue)."""
    if not isinstance(row, dict):
        return None
    upid = _str(row.get("upid"))
    if not upid or not UPID.fullmatch(upid):
        return None
    status = _str(row.get("status"))
    start, end = _int(row.get("starttime")), _int(row.get("endtime"))
    state = task_state(status, end is not None and end > 0)
    user, token = _str(row.get("user")), _str(row.get("tokenid"))
    text = None if state in ("ok", "running") else (status[:MAX_STATUS_TEXT] if status else None)
    return {
        "upid": upid, "node": _str(row.get("node")) or node_hint, "type": _str(row.get("type")), "id": _str(row.get("id")) or (
            str(_int(row.get("id"))) if _int(row.get("id")) is not None else None),
        "user": user, "token": token,
        "start": _iso(start), "end": _iso(end) if end else None,
        "duration": (end - start) if (start and end and end >= start) else None,
        "state": state, "status_text": text,
        # Lancée par Kaji : même utilisateur ET même jeton que la connexion (le nom du jeton seul ne suffit pas)
        "by_kaji": bool(user and token and user == conn_user and token == conn_token),
        "_sort": start or 0,
    }


def merge_tasks(per_node: list[list[dict]], limit: int) -> list[dict]:
    """Fusionne les listes des nœuds : plus récentes d'abord, au plus `limit`, sans doublon d'UPID."""
    seen: set[str] = set()
    out = []
    for t in sorted((t for rows in per_node for t in rows), key=lambda t: (t["_sort"], t["upid"]), reverse=True):
        if t["upid"] in seen:
            continue
        seen.add(t["upid"])
        out.append({k: v for k, v in t.items() if k != "_sort"})
        if len(out) >= limit:
            break
    return out
