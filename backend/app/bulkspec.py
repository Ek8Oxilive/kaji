"""Actions groupées d'un nœud (tout démarrer, tout arrêter, tout migrer) et Wake-on-LAN : plan, garde-fous, paramètres envoyés à Proxmox.

Kaji n'envoie JAMAIS « toutes les machines » : la liste `vms` est toujours explicite, relue contre `/cluster/resources`, et chaque machine
est contrôlée (présente sur ce nœud, pas un modèle, jamais une machine protégée pour un arrêt ou une migration). Le plan (`plan`) ne dépend
que de données déjà validées ; `verdict` dit si l'action réelle est permise. Tout est vérifié côté serveur, avant le moindre appel d'écriture.
"""
import re

ACTIONS = ("startall", "stopall", "migrateall")
MAX_VMS = 50
NODE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9-]{0,62})")


def plan(action: str, node: str, vmids: list[int], guests: list[dict], protected: set[int], cluster: dict, target: str | None) -> dict:
    """`guests` : sortie de `shape_guests` ; `cluster` : sortie de `shape_status`. Ne renvoie jamais de valeur saisie telle quelle."""
    nodes = cluster.get("nodes") or []
    me = next((n for n in nodes if n.get("name") == node), None)
    here = {g["vmid"]: g for g in guests if g.get("node") == node and not g.get("template") and isinstance(g.get("vmid"), int)}
    unknown = sorted(v for v in vmids if v not in here)
    chosen = [here[v] for v in vmids if v in here]
    row = lambda g: {"vmid": g["vmid"], "name": g.get("name"), "type": g.get("type"), "status": g.get("status")}   # noqa: E731
    apply, skipped = [], []
    for g in chosen:
        running = g.get("status") == "running"
        if action == "startall" and running:
            skipped.append({**row(g), "reason": "déjà en marche"})
        elif action == "stopall" and not running:
            skipped.append({**row(g), "reason": "déjà arrêtée"})
        else:
            apply.append(row(g))
    t = next((n for n in nodes if n.get("name") == target), None) if target else None
    return {
        "action": action, "node": node, "known": me is not None, "online": bool(me and me.get("online")),
        "apply": apply, "skipped": skipped, "unknown": unknown,
        "protected": sorted(g["vmid"] for g in apply if g["vmid"] in protected) if action != "startall" else [],
        "running": [g["vmid"] for g in apply if g.get("status") == "running"],
        "target": target, "target_ok": (bool(t and t.get("online")) and target != node) if action == "migrateall" else None,
    }


def verdict(p: dict, confirm: bool, typed: str | None, accept_running: bool) -> tuple[int, str] | None:
    """`None` si l'action réelle est permise, sinon `(code HTTP, message)`."""
    if not p["known"]:
        return 404, "Nœud inconnu du cluster"
    if not p["online"]:
        return 409, "Le nœud est hors ligne"
    if p["unknown"]:
        return 422, "Machine absente de ce nœud (ou modèle) : " + ", ".join(str(v) for v in p["unknown"])
    if p["action"] == "migrateall" and not p["target_ok"]:
        return 422, "Nœud cible invalide : il doit être en ligne et différent du nœud source"
    if p["protected"]:
        return 422, "Machine protégée : " + ", ".join(str(v) for v in p["protected"]) + " (arrête-la ou migre-la à la main, jamais en groupe)"
    if not p["apply"]:
        return 409, "Rien à faire : toutes les machines choisies sont déjà dans l'état demandé"
    if not confirm:
        return 400, "Confirmation requise"
    if p["action"] != "startall" and typed != p["node"]:
        return 400, "Retape le nom exact du nœud pour confirmer"
    if p["action"] == "migrateall" and p["running"] and not accept_running:
        return 409, f"{len(p['running'])} machine(s) en marche seront migrées à chaud (les conteneurs sont redémarrés) : confirme explicitement (accept_running)"
    return None


def proxmox_params(p: dict, force_stop: bool, timeout: int, with_local_disks: bool, max_workers: int) -> dict:
    """Paramètres exacts envoyés à `POST /nodes/{node}/{action}`. Rien d'autre ne part vers Proxmox."""
    vms = ",".join(str(g["vmid"]) for g in p["apply"])
    if p["action"] == "startall":
        return {"vms": vms, "force": 1}                       # `force` : démarre même si `onboot` est désactivé (la liste est explicite)
    if p["action"] == "stopall":
        return {"vms": vms, "force-stop": 1 if force_stop else 0, "timeout": timeout}
    return {"vms": vms, "target": p["target"], "maxworkers": max_workers, "with-local-disks": 1 if with_local_disks else 0}


def wake_verdict(known: bool, online: bool, confirm: bool, typed: str | None, node: str) -> tuple[int, str] | None:
    """Wake-on-LAN : seulement pour un nœud connu du cluster et HORS ligne ; confirmation avec le nom retapé."""
    if not known:
        return 404, "Nœud inconnu du cluster"
    if online:
        return 409, "Le nœud est déjà en ligne"
    if not confirm:
        return 400, "Confirmation requise"
    if typed != node:
        return 400, "Retape le nom exact du nœud pour confirmer"
    return None
