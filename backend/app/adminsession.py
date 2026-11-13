"""Session administrateur : une identité Proxmox **temporaire** pour écrire des droits (utilisateurs, ACL, tokens).

Pourquoi : le token permanent de Kaji n'a volontairement ni `Permissions.Modify` ni `User.Modify` (voir `docs/m6-ecriture.md`). S'il les avait, un
Kaji compromis au repos pourrait se donner `Administrator` de façon durable. Ici, le propriétaire colle un token d'administration créé pour
l'occasion ; il vit **en mémoire de ce processus seulement** (jamais en base, jamais dans un journal, jamais renvoyé), expire seul, et disparaît
avec la session de connexion de Kaji à laquelle il est lié.

Limites assumées :
- l'application tourne avec **un seul worker** (voir `Dockerfile`) : l'état n'est pas partagé entre processus ;
- Python ne permet pas d'effacer proprement un secret de la mémoire : on se contente de supprimer toute référence ;
- un redémarrage de Kaji ferme toutes les sessions administrateur (voulu).
"""
import re
import threading
import time
from dataclasses import dataclass, field

from pydantic import SecretStr

TTL_SECONDS = 30 * 60                 # durée d'une session, renouvelable
MAX_AGE_SECONDS = 4 * 3600            # âge maximal absolu, renouvellements compris
MAX_ATTEMPTS = 5                      # essais d'ouverture par fenêtre
ATTEMPT_WINDOW = 60

USER = re.compile(r"^[A-Za-z0-9._\-]{1,64}@[A-Za-z0-9._\-]{1,32}$")
TOKEN_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._\-]{1,63}$")
# Un secret de token Proxmox est un UUID.
SECRET = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _now() -> float:
    return time.monotonic()


@dataclass
class AdminSession:
    conn_id: int
    owner_id: int                     # utilisateur de Kaji
    user: str                         # compte Proxmox du token (user@realm)
    token_id: str
    secret: SecretStr = field(repr=False)
    opened_at: float = 0.0
    expires_at: float = 0.0
    renewals: int = 0
    kind: str = "token"               # « token » (jeton d'API) ou « ticket » (connexion par mot de passe : le seul à pouvoir écrire la double authentification)
    ticket: SecretStr | None = field(default=None, repr=False)
    csrf: SecretStr | None = field(default=None, repr=False)

    def seconds_left(self) -> int:
        return max(0, int(self.expires_at - _now()))

    def __repr__(self) -> str:        # jamais le secret, même par accident (journal, assertion, débogueur)
        who = f"{self.user} (ticket)" if self.kind == "ticket" else f"{self.user}!{self.token_id}"
        return f"AdminSession(conn={self.conn_id}, {who}, left={self.seconds_left()}s)"


class AdminSessions:
    """Magasin en mémoire, indexé par l'identifiant de la session de connexion de Kaji (`jti`)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, AdminSession] = {}
        self._attempts: dict[int, list[float]] = {}

    # -- cycle de vie
    def open(self, jti: str, owner_id: int, conn_id: int, user: str, token_id: str, secret: SecretStr) -> AdminSession:
        now = _now()
        s = AdminSession(conn_id=conn_id, owner_id=owner_id, user=user, token_id=token_id, secret=secret,
                         opened_at=now, expires_at=now + TTL_SECONDS)
        with self._lock:
            self._purge(now)
            self._items[jti] = s                     # remplace une session éventuelle
        return s

    def open_ticket(self, jti: str, owner_id: int, conn_id: int, user: str, ticket: SecretStr, csrf: SecretStr) -> AdminSession:
        """Session par ticket : le mot de passe n'existe plus à ce stade (il n'a servi qu'à obtenir le ticket, jamais gardé)."""
        now = _now()
        s = AdminSession(conn_id=conn_id, owner_id=owner_id, user=user, token_id="", secret=SecretStr(""), opened_at=now, expires_at=now + TTL_SECONDS,
                         kind="ticket", ticket=ticket, csrf=csrf)
        with self._lock:
            self._purge(now)
            self._items[jti] = s
        return s

    def get(self, jti: str, conn_id: int | None = None) -> AdminSession | None:
        """La session si elle existe, n'a pas expiré et (si demandé) concerne bien cette connexion Proxmox."""
        now = _now()
        with self._lock:
            self._purge(now)
            s = self._items.get(jti)
        if s is None or (conn_id is not None and s.conn_id != conn_id):
            return None
        return s

    def renew(self, jti: str, conn_id: int) -> AdminSession | None:
        """Prolonge de `TTL_SECONDS` sans jamais dépasser `MAX_AGE_SECONDS` depuis l'ouverture. None : absente ou expirée."""
        now = _now()
        with self._lock:
            self._purge(now)
            s = self._items.get(jti)
            if s is None or s.conn_id != conn_id:
                return None
            s.expires_at = min(now + TTL_SECONDS, s.opened_at + MAX_AGE_SECONDS)
            s.renewals += 1
            return s

    def at_age_limit(self, jti: str) -> bool:
        s = self._items.get(jti)
        return s is not None and s.expires_at >= s.opened_at + MAX_AGE_SECONDS - 1

    def close(self, jti: str) -> bool:
        with self._lock:
            return self._items.pop(jti, None) is not None

    def close_owner(self, owner_id: int) -> int:
        """Ferme toutes les sessions d'un utilisateur de Kaji (déconnexion de partout)."""
        with self._lock:
            keys = [k for k, s in self._items.items() if s.owner_id == owner_id]
            for k in keys:
                del self._items[k]
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._attempts.clear()

    # -- limite d'essais (un token à deviner, un token périmé qu'on réessaie en boucle…)
    def allow_attempt(self, owner_id: int) -> bool:
        now = _now()
        with self._lock:
            recent = [t for t in self._attempts.get(owner_id, []) if now - t < ATTEMPT_WINDOW]
            if len(recent) >= MAX_ATTEMPTS:
                self._attempts[owner_id] = recent
                return False
            recent.append(now)
            self._attempts[owner_id] = recent
            return True

    def _purge(self, now: float) -> None:
        for k in [k for k, s in self._items.items() if s.expires_at <= now]:
            del self._items[k]


sessions = AdminSessions()
