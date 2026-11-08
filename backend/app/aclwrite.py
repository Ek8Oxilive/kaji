"""Écriture d'une entrée d'ACL Proxmox : validation, interdits absolus et aperçu. Une seule entrée à la fois, jamais en masse.

Garde-fous du cadrage (`docs/m6-ecriture.md`, §5), tous vérifiés **côté serveur** :
- chemins en **liste blanche** (un pool, une VM, un stockage, un nœud) ; jamais `/`, `/access`, ni un chemin « parent » (`/vms`, `/pool`) ;
- rôles : jamais `Administrator` ni un rôle qui porte `Permissions.Modify`, `User.Modify`, `Group.Allocate` ou `Realm.*` (relu chez Proxmox au moment de l'action) ;
- jamais l'identité de Kaji, `root@pam`, ni celle de la session administrateur, ni un groupe qui les contient ;
- `confirm=true` et l'identifiant retapé ; l'aperçu dit ce qui existe déjà et les privilèges du rôle.
Retirer une entrée est permis pour tout rôle (retirer un droit ne l'augmente jamais), sauf sur les identités protégées.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .accessspec import FORBIDDEN_PRIVS
from .adminsession import TOKEN_ID, USER

PATHS = (
    re.compile(r"/pool/[A-Za-z0-9][A-Za-z0-9_\-]{0,39}"),
    re.compile(r"/vms/[0-9]{3,9}"),
    re.compile(r"/storage/[A-Za-z0-9][A-Za-z0-9_\-]{0,39}"),
    re.compile(r"/nodes/[A-Za-z0-9][A-Za-z0-9\-]{0,62}"),
)
GROUP = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,63}")
ROLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,63}")
USER_RX = re.compile(USER.pattern)
TOKEN_RX = re.compile(TOKEN_ID.pattern)
ROOT = "root@pam"


def check_path(p: str) -> str:
    if not isinstance(p, str) or not any(rx.fullmatch(p) for rx in PATHS):
        raise ValueError("Chemin non autorisé (attendu : /pool/…, /vms/…, /storage/… ou /nodes/…)")
    return p


def check_target(kind: str, ugid: str) -> str:
    ok = False
    if isinstance(ugid, str):
        if kind == "user":
            ok = bool(USER_RX.fullmatch(ugid))
        elif kind == "group":
            ok = bool(GROUP.fullmatch(ugid))
        elif kind == "token":
            user, bang, tok = ugid.partition("!")
            ok = bool(bang) and bool(USER_RX.fullmatch(user)) and bool(TOKEN_RX.fullmatch(tok))
    if not ok:
        raise ValueError("Identifiant invalide")
    return ugid


class AclChange(BaseModel):
    action: Literal["add", "remove"]
    path: str = Field(max_length=100)
    kind: Literal["user", "group", "token"]
    ugid: str = Field(max_length=140, description="user@realm, identifiant de groupe, ou user@realm!jeton")
    role: str = Field(max_length=64)
    propagate: bool = True

    @model_validator(mode="after")
    def _check(self):
        check_path(self.path)
        check_target(self.kind, self.ugid)
        if not ROLE.fullmatch(self.role):
            raise ValueError("Rôle invalide")
        return self


class AclApply(AclChange):
    confirm: bool = False
    type_name: str | None = Field(default=None, max_length=140, description="Identifiant retapé")


def role_privs(roles: list[dict], role: str) -> set[str] | None:
    """Privilèges d'un rôle d'après la liste de Proxmox (`shape_roles`), ou None si le rôle n'existe pas."""
    for r in roles:
        if r.get("roleid") == role:
            return set(r.get("privs") or [])
    return None


def protected_users(conn_user: str, admin_user: str) -> set[str]:
    """Comptes protégés : root, celui de Kaji, celui de la session administrateur. Tous leurs tokens le sont aussi (même un token que Kaji ne connaît pas)."""
    return {ROOT, conn_user, admin_user}


def refusal(ch: AclChange, roles: list[dict], groups: list[dict], conn_user: str, admin_user: str) -> str | None:
    """Raison du refus (sans valeur saisie), ou None si l'écriture est permise."""
    users = protected_users(conn_user, admin_user)
    if ch.kind == "user" and ch.ugid in users:
        return "Interdit : cette identité est protégée (Kaji, session administrateur ou root@pam)"
    if ch.kind == "token" and ch.ugid.partition("!")[0] in users:
        return "Interdit : ce token appartient à une identité protégée (Kaji, session administrateur ou root@pam)"
    if ch.kind == "group":
        for g in groups:
            if g.get("groupid") == ch.ugid and users & set(g.get("users") or []):
                return "Interdit : ce groupe contient une identité protégée (Kaji, session administrateur ou root@pam)"
    privs = role_privs(roles, ch.role)
    if privs is None:
        return "Rôle inconnu"
    if ch.action == "add" and (ch.role == "Administrator" or privs & FORBIDDEN_PRIVS):
        return "Interdit : ce rôle permettrait de modifier les droits (Administrator, Permissions.Modify, User.Modify, Group.Allocate, Realm.*)"
    return None


def find_entry(acl: list[dict], ch: AclChange) -> dict | None:
    kind = ch.kind
    for a in acl:
        if a.get("path") == ch.path and a.get("ugid") == ch.ugid and a.get("roleid") == ch.role and (a.get("type") in (None, kind)):
            return a
    return None


def entries_for(acl: list[dict], ch: AclChange) -> list[dict]:
    return [a for a in acl if a.get("path") == ch.path and a.get("ugid") == ch.ugid]


def proxmox_params(ch: AclChange) -> dict[str, str | int]:
    """Paramètres exacts de `PUT /access/acl` : une cible, un rôle, un chemin."""
    target = {"user": "users", "group": "groups", "token": "tokens"}[ch.kind]
    p: dict[str, str | int] = {"path": ch.path, "roles": ch.role, target: ch.ugid}
    if ch.action == "add":
        p["propagate"] = 1 if ch.propagate else 0
    else:
        p["delete"] = 1
    return p
