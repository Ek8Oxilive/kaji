"""Services d'un nœud : liste blanche et garde-fous des actions (démarrer, arrêter, redémarrer, recharger).

Seuls les services connus de Proxmox VE sont pilotables. Trois niveaux de risque :
- `normal` : sans effet sur l'accès ni sur le cluster ;
- `sensitive` : un redémarrage coupe un moment l'API, les consoles, le pare-feu ou la haute disponibilité ;
- `vital` : le cluster (`corosync`, `pve-cluster`) dépend d'eux : un redémarrage exige de retaper le nom du service.
Certains services ne s'arrêtent jamais depuis Kaji (`NO_STOP`) : on se couperait l'accès ou on casserait le cluster.
"""
ACTIONS = ("start", "stop", "restart", "reload")

VITAL = frozenset({"corosync", "pve-cluster"})
SENSITIVE = frozenset({"pveproxy", "pvedaemon", "pvestatd", "pvescheduler", "pve-firewall", "proxmox-firewall", "pve-ha-crm", "pve-ha-lrm",
                       "sshd", "lxcfs", "pve-lxc-syscalld", "qmeventd", "systemd-journald", "spiceproxy"})
NORMAL = frozenset({"chrony", "cron", "ksmtuned", "postfix", "pvefw-logger"})
KNOWN = VITAL | SENSITIVE | NORMAL
NO_STOP = frozenset({"corosync", "pve-cluster", "pveproxy", "pvedaemon", "sshd", "systemd-journald", "lxcfs"})


def risk(service: str) -> str:
    return "vital" if service in VITAL else "sensitive" if service in SENSITIVE else "normal"


def verdict(service: str, action: str, confirm: bool, typed: str | None) -> tuple[int, str] | None:
    """`None` si l'action est permise, sinon `(code HTTP, message)`. Vérifié côté serveur, avant tout appel à Proxmox."""
    if service not in KNOWN:
        return 404, "Service inconnu ou non pilotable depuis Kaji"
    if action not in ACTIONS:
        return 422, "Action inconnue"
    if action == "stop" and service in NO_STOP:
        return 422, "Arrêter ce service couperait l'accès ou casserait le cluster : à faire en ligne de commande sur le nœud"
    if action != "start" and not confirm:
        return 400, "Confirmation requise"
    if service in VITAL and action in ("restart", "reload") and typed != service:
        return 400, "Service vital du cluster : retape son nom exact pour confirmer"
    return None
