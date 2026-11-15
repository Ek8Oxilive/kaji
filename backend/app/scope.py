"""Périmètre d'un compte de Kaji (lot #447, jalon J2) : restreindre un compte (opérateur ou lecture seule) à un GROUPE DE MACHINES, décidé par le SERVEUR à chaque requête.

Principe : **tout est refusé par défaut** pour un compte restreint. N'est permis que ce que ce module liste explicitement :
- le libre-service (`/api/auth/…`, `/api/me/…`) ;
- la liste des connexions (filtrée aux connexions de son périmètre), la liste des machines et le flux temps réel (filtrés aux machines de son périmètre) ;
- les routes d'UNE machine (`…/guests/{node}/{type}/{vmid}/…`, `…/firewall/guests/…`) quand la machine est dans son périmètre, et le journal d'une tâche de CETTE machine ;
- tout le reste (stockage, réseau, droits, tâches de tout le cluster, HA, audit, administration…) : refusé. Une route ajoutée plus tard l'est donc aussi, tant qu'on ne la déclare pas ici
  (test de garde : `tests/test_scope.py` passe TOUTES les routes de l'application à la politique).

Le rôle (`app/roles.py`) s'applique EN PLUS : un opérateur restreint ne fait que démarrer / arrêter / redémarrer / créer un snapshot, et seulement sur ses machines.
Un administrateur n'a jamais de périmètre. Une machine est désignée par son `vmid` (unique dans un cluster) ; le périmètre est par connexion. Un « pool » n'est PAS résolu à la volée (cela exigerait
un appel à Proxmox à chaque requête) : l'interface propose seulement d'ajouter d'un coup les machines d'un pool, au moment de l'attribution.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import UserScope

# `…/guests/{node}/{qemu|lxc}/{vmid}[/…]` et `…/firewall/guests/…` : les deux seules familles de routes qui portent un identifiant de machine.
GUEST = re.compile(r"/api/connections/(?P<conn>[0-9]{1,9})/(?:firewall/)?guests/(?P<node>[A-Za-z0-9][A-Za-z0-9.\-]{0,62})/(?P<gtype>qemu|lxc)/(?P<vmid>[0-9]{1,9})(?:/[^/]+)*")
CONN_LISTS = re.compile(r"/api/connections/(?P<conn>[0-9]{1,9})/(?P<what>guests|events)")
TASK = re.compile(r"/api/connections/(?P<conn>[0-9]{1,9})/tasks/(?P<node>[A-Za-z0-9\-]+)/(?P<upid>UPID:[^/]+)(?:/log)?")
SELF_SERVICE = ("/api/auth/", "/api/me/")
# Types de tâches Proxmox qui concernent UNE machine (l'identifiant de tâche est alors son vmid) : `qmstart`, `vzstop`, `qmsnapshot`, `vncproxy`…
GUEST_TASK = re.compile(r"(?:qm|vz)[a-z]+|vncproxy|vncshell|spiceproxy|termproxy|qmrestore|vzdump")
Scope = dict[int, frozenset[int]]


def scope_of(db: Session, user_id: int) -> Scope | None:
    """`{connexion: machines}` du compte, ou `None` s'il n'est pas restreint."""
    rows = db.execute(select(UserScope.conn_id, UserScope.vmid).where(UserScope.user_id == user_id)).all()
    if not rows:
        return None
    out: dict[int, set[int]] = {}
    for conn, vmid in rows:
        out.setdefault(conn, set()).add(vmid)
    return {c: frozenset(v) for c, v in out.items()}


def clean(path: str) -> bool:
    """Chemin sans tour de passe-passe : ni `..`, ni `//`, ni octet de contrôle ni caractère hors ASCII (refusé pour un compte restreint)."""
    return path.isascii() and path.isprintable() and ".." not in path and "//" not in path


def _task_vmid(upid: str) -> int | None:
    """Le vmid d'une tâche de machine (`UPID:nœud:pid:pstart:début:type:id:utilisateur:`), sinon `None` (tâche du cluster, d'un nœud, du stockage…)."""
    parts = upid.split(":")
    if len(parts) < 8 or parts[0] != "UPID" or not GUEST_TASK.fullmatch(parts[5]) or not parts[6].isdigit():
        return None
    return int(parts[6])


def allowed(scope: Scope, method: str, path: str) -> bool:
    """La politique pour un compte restreint. `scope` : `{connexion: machines}`."""
    if not clean(path):
        return False
    if path.startswith(SELF_SERVICE):
        return True                                                    # la politique des rôles décide déjà du libre-service
    if path == "/api/connections":
        return method.upper() == "GET"                                 # la liste est filtrée par le gestionnaire (connexions du périmètre)
    if m := GUEST.fullmatch(path):
        return int(m["conn"]) in scope and int(m["vmid"]) in scope[int(m["conn"])]
    if m := CONN_LISTS.fullmatch(path):
        return method.upper() == "GET" and int(m["conn"]) in scope     # filtrées par les gestionnaires (machines du périmètre)
    if m := TASK.fullmatch(path):
        vmid = _task_vmid(m["upid"])
        return method.upper() == "GET" and int(m["conn"]) in scope and vmid is not None and vmid in scope[int(m["conn"])]
    return False


def machines(scope: Scope | None, conn_id: int) -> frozenset[int] | None:
    """Les machines permises sur une connexion (`None` : pas de restriction ; ensemble vide : aucune)."""
    return None if scope is None else scope.get(conn_id, frozenset())


def filter_guests(scope: Scope | None, conn_id: int, guests: list[dict]) -> list[dict]:
    """La liste des machines réduite au périmètre ; sans restriction, inchangée."""
    allowed_ids = machines(scope, conn_id)
    return guests if allowed_ids is None else [g for g in guests if g.get("vmid") in allowed_ids]


def filter_connections(scope: Scope | None, connections: list) -> list:
    return connections if scope is None else [c for c in connections if c.id in scope]


def filter_snapshot(scope: Scope | None, conn_id: int, snapshot: dict) -> dict:
    """Un instantané du flux temps réel réduit au périmètre : les machines permises seulement, les nœuds qui les portent, et RIEN de l'état du cluster
    (quorum, adresses des nœuds, noms)."""
    allowed_ids = machines(scope, conn_id)
    if allowed_ids is None:
        return snapshot
    guests = [g for g in snapshot.get("guests", []) if g.get("vmid") in allowed_ids]
    hosting = {g.get("node") for g in guests}
    nodes = [{k: n.get(k) for k in ("node", "status")} for n in snapshot.get("nodes", []) if n.get("node") in hosting]
    return {"status": {"name": None, "quorate": None, "nodes": []}, "nodes": nodes, "guests": guests}
