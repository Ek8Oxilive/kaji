"""Redémarrer ou éteindre un nœud : évaluation des conséquences et garde-fous (jamais d'action sans confirmation forte).

Un nœud qu'on éteint coupe ses machines, peut couper l'accès à Kaji et, dans un cluster à nombre de nœuds trop faible, fait
**perdre le quorum** aux nœuds restants (plus de démarrage de machine, `/etc/pve` en lecture seule). L'évaluation vient de
Proxmox (état du cluster et machines en marche) ; si elle est illisible, l'action est refusée (fail closed).
"""
ACTIONS = ("reboot", "shutdown")


def assess(node: str, cluster: dict, guests: list[dict], protected: set[int]) -> dict:
    """`cluster` : sortie de `cluster.shape_status` ; `guests` : sortie de `shape_guests`. Ne dépend que de données déjà validées."""
    nodes = cluster.get("nodes") or []
    me = next((n for n in nodes if n.get("name") == node), None)
    online = sum(1 for n in nodes if n.get("online"))
    in_cluster = cluster.get("quorate") is not None
    after = online - (1 if me and me.get("online") else 0)
    running = [g for g in guests if g.get("node") == node and g.get("status") == "running" and not g.get("template") and isinstance(g.get("vmid"), int)]
    return {
        "node": node, "known": me is not None, "online": bool(me and me.get("online")),
        "running_guests": [{"vmid": g["vmid"], "name": g.get("name"), "type": g.get("type")} for g in sorted(running, key=lambda g: g["vmid"])],
        "protected_running": sorted(g["vmid"] for g in running if g["vmid"] in protected),
        "quorum_loss": bool(in_cluster and len(nodes) > 0 and after * 2 <= len(nodes)),
        "nodes_online_after": after if in_cluster else None,
    }


def verdict(action: str, node: str, confirm: bool, typed: str | None, accept_guests: bool, accept_quorum_loss: bool, a: dict) -> tuple[int, str] | None:
    """`None` si permis, sinon `(code HTTP, message)`. Vérifié côté serveur, avant tout appel d'écriture à Proxmox."""
    if action not in ACTIONS:
        return 422, "Action inconnue"
    if not a["known"]:
        return 404, "Nœud inconnu du cluster"
    if not a["online"]:
        return 409, "Le nœud est déjà hors ligne"
    if not confirm:
        return 400, "Confirmation requise"
    if typed != node:
        return 400, "Retape le nom exact du nœud pour confirmer"
    if a["protected_running"]:
        ids = ", ".join(str(v) for v in a["protected_running"])
        return 422, f"Machine protégée en marche sur ce nœud ({ids}) : arrête-la ou migre-la d'abord"
    if a["running_guests"] and not accept_guests:
        return 409, f"{len(a['running_guests'])} machine(s) en marche seront arrêtées : confirme explicitement (accept_guests)"
    if a["quorum_loss"] and not accept_quorum_loss:
        return 409, "Les nœuds restants perdraient le quorum du cluster : confirme explicitement (accept_quorum_loss)"
    return None
