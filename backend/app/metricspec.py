"""Historique des mesures (RRD) d'un nœud ou d'une machine : mise en forme tolérante, lecture seule.

Seuls les champs de la liste blanche sont repris. Une valeur absente (machine arrêtée, trou), non numérique, infinie, `NaN` ou
négative devient `null` : elle ne fausse jamais une courbe et ne la traverse pas. Les séries sont réduites à `MAX_POINTS` points
au plus (moyenne par tranche) pour que la page reste fluide.
"""
import math

MAX_POINTS = 400

# champ renvoyé par Kaji -> champ du RRD de Proxmox
NODE_FIELDS = {"cpu": "cpu", "iowait": "iowait", "load": "loadavg", "mem_used": "memused", "mem_total": "memtotal",
               "swap_used": "swapused", "swap_total": "swaptotal", "net_in": "netin", "net_out": "netout"}
GUEST_FIELDS = {"cpu": "cpu", "cpus": "maxcpu", "mem_used": "mem", "mem_total": "maxmem", "net_in": "netin", "net_out": "netout",
                "disk_read": "diskread", "disk_write": "diskwrite"}


def _num(v) -> float | None:
    """Nombre fini et positif ou nul ; sinon `None` (booléens, textes, `NaN`, infinis et négatifs exclus)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if not math.isfinite(v) or v < 0:
        return None
    return float(v)


def _time(v) -> int | None:
    n = _num(v)
    return int(n) if n is not None and n < 4_102_444_800 else None      # avant 2100 : on écarte les horodatages absurdes


def shape_points(rows, fields: dict[str, str], max_points: int = MAX_POINTS) -> list[dict]:
    """Points `{t, <champ>: valeur|None…}` triés par date, sans doublon de date, réduits à `max_points` au plus."""
    seen: dict[int, dict] = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        t = _time(r.get("time"))
        if t is None:
            continue
        seen[t] = {"t": t, **{out: _num(r.get(src)) for out, src in fields.items()}}
    points = [seen[t] for t in sorted(seen)]
    return _downsample(points, fields, max_points)


def _downsample(points: list[dict], fields: dict[str, str], max_points: int) -> list[dict]:
    """Moyenne par tranche (les valeurs absentes sont ignorées ; une tranche entièrement vide reste vide : le trou est conservé)."""
    n = len(points)
    if max_points < 1 or n <= max_points:
        return points
    out = []
    for i in range(max_points):
        chunk = points[i * n // max_points:(i + 1) * n // max_points]
        if not chunk:
            continue
        row: dict = {"t": chunk[len(chunk) // 2]["t"]}
        for f in fields:
            vals = [p[f] for p in chunk if p[f] is not None]
            row[f] = sum(vals) / len(vals) if vals else None
        out.append(row)
    return out


def step_seconds(points: list[dict]) -> int | None:
    """Écart typique entre deux points (la médiane), `None` s'il y en a moins de deux."""
    gaps = sorted(b["t"] - a["t"] for a, b in zip(points, points[1:]) if b["t"] > a["t"])
    return gaps[len(gaps) // 2] if gaps else None
