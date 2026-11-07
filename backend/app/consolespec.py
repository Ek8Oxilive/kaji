"""Console web : validation et sessions à usage unique. Logique pure, testable sans réseau.

Principe : le navigateur demande une console (requête HTTP authentifiée et auditée) et reçoit un identifiant **à usage unique**, valable
quelques secondes et **lié à sa session Kaji**. Il ouvre ensuite le WebSocket de Kaji avec cet identifiant. Le ticket Proxmox ne
quitte jamais le serveur, sauf pour noVNC (le mot de passe VNC *est* le ticket, comme dans l'interface de Proxmox).
"""
import secrets
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

Kind = Literal["vnc", "term"]

SESSION_TTL = 30.0          # secondes pour ouvrir le WebSocket après la demande (le ticket Proxmox vit ~40 s)
MAX_PENDING = 8             # demandes non utilisées par session Kaji
MAX_ACTIVE = 4              # consoles ouvertes en même temps par session Kaji
IDLE_TIMEOUT = 1800.0       # secondes sans aucun octet dans un sens ou dans l'autre
MAX_DURATION = 8 * 3600.0   # durée maximale d'une console
MAX_MESSAGE = 1024 * 1024   # octets par message


@dataclass(frozen=True)
class Target:
    """Ce que le WebSocket doit atteindre. Construit par le serveur, jamais par le client."""
    conn_id: int
    node: str
    gtype: Literal["qemu", "lxc"]
    vmid: int
    kind: Kind
    port: int
    ticket: str
    pve_user: str


@dataclass
class _Pending:
    target: Target
    owner: str            # identifiant de la session Kaji (jti)
    expires: float


class ConsoleSessions:
    """Identifiants à usage unique, liés à une session Kaji, et compteur de consoles actives."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._pending: dict[str, _Pending] = {}
        self._active: dict[str, int] = {}

    def _purge(self) -> None:
        now = self._clock()
        for k in [k for k, p in self._pending.items() if p.expires <= now]:
            del self._pending[k]

    def create(self, owner: str, target: Target) -> str | None:
        """Identifiant, ou `None` si cette session Kaji a déjà trop de demandes en attente."""
        self._purge()
        if sum(1 for p in self._pending.values() if p.owner == owner) >= MAX_PENDING:
            return None
        sid = secrets.token_urlsafe(32)
        self._pending[sid] = _Pending(target, owner, self._clock() + SESSION_TTL)
        return sid

    def take(self, sid: str, owner: str) -> Target | None:
        """Consomme l'identifiant (usage unique). `None` s'il est inconnu, expiré, déjà utilisé ou lié à une autre session.
        Un identifiant présenté par une autre session n'est **pas** consommé : il ne peut pas être détruit par un tiers."""
        self._purge()
        p = self._pending.get(sid)
        if p is None or not secrets.compare_digest(p.owner, owner):
            return None
        del self._pending[sid]
        return p.target

    def acquire(self, owner: str) -> bool:
        if self._active.get(owner, 0) >= MAX_ACTIVE:
            return False
        self._active[owner] = self._active.get(owner, 0) + 1
        return True

    def release(self, owner: str) -> None:
        n = self._active.get(owner, 0) - 1
        if n > 0:
            self._active[owner] = n
        else:
            self._active.pop(owner, None)

    def active(self, owner: str) -> int:
        return self._active.get(owner, 0)


def origin_ok(origin: str | None, host: str | None) -> bool:
    """Protection contre le détournement de WebSocket depuis un autre site : l'`Origin` doit être celui de la page servie par
    Kaji, c'est-à-dire avoir le même hôte (avec port) que l'en-tête `Host`. Un `Origin` absent est refusé : un navigateur
    l'envoie toujours sur un WebSocket."""
    if not origin or not host:
        return False
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.username or parts.password:
        return False
    return parts.netloc.lower() == host.strip().lower()


def valid_proxy_reply(reply, kind: Kind) -> tuple[int, str, str] | None:
    """Réponse de `vncproxy` / `termproxy` -> `(port, ticket, utilisateur)`, ou `None` si elle n'est pas exploitable."""
    if not isinstance(reply, dict):
        return None
    port, ticket, user = reply.get("port"), reply.get("ticket"), reply.get("user")
    if isinstance(port, str) and port.isascii() and port.isdigit():
        port = int(port)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return None
    if not isinstance(ticket, str) or not 1 <= len(ticket) <= 4096 or not isinstance(user, str) or not 1 <= len(user) <= 256:
        return None
    return port, ticket, user
