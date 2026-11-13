"""Rôles des utilisateurs de Kaji (lot #409) : qui a le droit de faire quoi, décidé par le SERVEUR sur chaque requête (jamais par l'interface).

- `admin` : tout, y compris gérer les utilisateurs de Kaji.
- `operator` : lire, démarrer / arrêter / redémarrer / suspendre / reprendre / réinitialiser une machine, créer un snapshot. Rien d'autre (ni console, ni
  migration, ni suppression, ni réglage, ni restauration d'un snapshot, ni droits).
- `viewer` : lecture seule.

Tout ce qui n'est pas explicitement permis à un rôle est refusé : une route ajoutée plus tard est réservée aux administrateurs tant qu'on ne la déclare pas ici.
Un rôle inconnu (base abîmée) est traité comme `viewer`. Le compte de Kaji auprès de Proxmox (le jeton) est le même pour tous : les rôles protègent l'accès à Kaji.
"""
import re

ROLES = ("admin", "operator", "viewer")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_G = r"/api/connections/\d+/guests/[A-Za-z0-9\-]+"
OPERATOR_POST = (
    re.compile(rf"^{_G}/(qemu|lxc)/\d+/(start|stop|shutdown|reboot)$"),
    re.compile(rf"^{_G}/qemu/\d+/(reset|suspend|resume|hibernate)$"),
    re.compile(rf"^{_G}/(qemu|lxc)/\d+/snapshots$"),
)
ADMIN_ONLY_PREFIX = "/api/kaji-users"
SELF_SERVICE_PREFIX = "/api/auth/"                       # déconnexion, changement de son propre mot de passe : tout rôle


def normalize(role) -> str:
    return role if role in ROLES else "viewer"


def allowed(role, method: str, path: str, *, websocket: bool = False) -> bool:
    role = normalize(role)
    if path == ADMIN_ONLY_PREFIX or path.startswith(ADMIN_ONLY_PREFIX + "/"):
        return role == "admin"
    if path.startswith(SELF_SERVICE_PREFIX):
        return True
    if role == "admin":
        return True
    if websocket:                                         # consoles : accès complet à la machine
        return False
    if method.upper() in SAFE_METHODS:
        return True
    return role == "operator" and method.upper() == "POST" and any(rx.fullmatch(path) for rx in OPERATOR_POST)
