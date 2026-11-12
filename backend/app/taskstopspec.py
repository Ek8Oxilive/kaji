"""Arrêter une tâche en cours : règles (liste blanche de types, machines protégées). Aucun réseau ici (lot #310).

Un UPID Proxmox : `UPID:<nœud>:<pid>:<pstart>:<début>:<type>:<id>:<utilisateur>:`. On n'arrête QUE les tâches dont le type figure dans `STOPPABLE` : celles qu'on
interrompt sans risque (le travail est abandonné proprement par Proxmox). Jamais une console ou un terminal (`vncproxy`, `vncshell`, `termproxy`, `spiceproxy`…),
ni une tâche de stockage, de cluster, de HA, de Ceph ou de réseau. Jamais une tâche portant sur une machine de `KAJI_PROTECTED_VMIDS`.
(La mise en forme des listes de tâches est dans `taskspec.py`.)
"""
import re

# type de tâche -> libellé (l'interface et l'audit s'en servent pour dire ce qu'on arrête)
STOPPABLE = {
    "vzdump": "Sauvegarde", "qmigrate": "Migration d'une VM", "vzmigrate": "Migration d'un conteneur", "qmclone": "Clonage d'une VM", "qmmove": "Déplacement d'un disque",
    "qmrestore": "Restauration d'une VM", "vzrestore": "Restauration d'un conteneur", "download": "Téléchargement", "imgcopy": "Copie d'un volume",
    "aptupdate": "Actualisation des paquets", "qmshutdown": "Arrêt propre d'une VM", "vzshutdown": "Arrêt propre d'un conteneur", "qmreboot": "Redémarrage d'une VM",
    "vzreboot": "Redémarrage d'un conteneur", "qmstart": "Démarrage d'une VM", "vzstart": "Démarrage d'un conteneur",
}
VMID_LIST = re.compile(r"[0-9]+(,[0-9]+)*")


def parse_upid(upid: str) -> dict | None:
    """`{node, type, id, user}` d'un UPID bien formé, sinon None."""
    parts = upid.split(":") if isinstance(upid, str) else []
    if len(parts) != 9 or parts[0] != "UPID" or parts[8] != "" or not parts[1] or not parts[5]:
        return None
    return {"node": parts[1], "type": parts[5], "id": parts[6], "user": parts[7]}


def vmids_of(task: dict) -> set[int]:
    """Machines visées par une tâche `qm*` ou `vz*` : l'id de la tâche, entier ou liste d'entiers (`vzdump` de plusieurs machines)."""
    t, i = task["type"], task["id"]
    return {int(x) for x in i.split(",")} if t.startswith(("qm", "vz")) and VMID_LIST.fullmatch(i) else set()


def stop_refusal(task: dict | None, protected: set[int]) -> str | None:
    """Pourquoi cette tâche ne s'arrête pas depuis Kaji (message), ou None si elle peut s'arrêter."""
    if task is None:
        return "Identifiant de tâche (UPID) invalide"
    if task["type"] not in STOPPABLE:
        return "Ce type de tâche ne s'arrête pas depuis Kaji (seules les tâches longues sans risque : sauvegarde, migration, clonage, copie, téléchargement…)"
    if vmids_of(task) & protected:
        return "Cette tâche porte sur une machine protégée par Kaji (KAJI_PROTECTED_VMIDS) : elle ne s'arrête pas depuis Kaji"
    return None
