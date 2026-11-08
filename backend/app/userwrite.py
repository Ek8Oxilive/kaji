"""Écriture des utilisateurs, groupes et appartenances Proxmox. Une écriture à la fois ; tout est validé, rien n'est transmis tel quel.

Garde-fous (`docs/m6-ecriture.md`, §5), vérifiés côté serveur :
- seuls les utilisateurs du realm **`pve`** sont gérés ici (pam, LDAP… se gèrent ailleurs) ; `root@pam`, le compte de Kaji et le compte de la session
  administrateur ne sont jamais modifiables ;
- **ajouter quelqu'un à un groupe** lui donne les droits du groupe : refusé si le groupe porte un rôle qui permet de modifier les droits
  (Administrator, `Permissions.Modify`, `User.Modify`, `Group.Allocate`, `Realm.*`) ou une entrée sous `/access` ;
- supprimer un groupe encore utilisé (membres ou ACL) est refusé : on ne perd pas de droits en silence ;
- `confirm=true` et l'identifiant retapé ; état relu chez Proxmox avant et après ; mot de passe en `SecretStr`, jamais journalisé.
"""
import re

from pydantic import BaseModel, Field, SecretStr, field_validator

from .accessspec import FORBIDDEN_PRIVS
from .aclwrite import GROUP, ROOT, role_privs

PVE_USER = re.compile(r"^[A-Za-z0-9._\-]{1,64}@pve$")
NOTE = re.compile(r"^[^\x00-\x1f\x7f\\]{0,100}$")
MAX_EXPIRE = 4_102_444_800                      # 2100-01-01


def _user(v: str) -> str:
    if not isinstance(v, str) or not PVE_USER.fullmatch(v):
        raise ValueError("Identifiant invalide (attendu : nom@pve)")
    return v


def _group(v: str) -> str:
    if not isinstance(v, str) or not GROUP.fullmatch(v):
        raise ValueError("Identifiant de groupe invalide")
    return v


def _note(v: str | None) -> str | None:
    if v is not None and not NOTE.fullmatch(v):
        raise ValueError("Commentaire invalide : une seule ligne de 100 caractères, sans antislash")
    return v


class Confirmed(BaseModel):
    confirm: bool = False
    type_name: str | None = Field(default=None, max_length=80, description="Identifiant retapé")


class UserCreate(Confirmed):
    userid: str = Field(max_length=80)
    comment: str | None = Field(default=None, max_length=100)
    enable: bool = True
    expire: int | None = Field(default=None, ge=0, le=MAX_EXPIRE, description="Secondes depuis 1970 ; 0 = jamais")
    password: SecretStr | None = Field(default=None, min_length=12, max_length=128, description="Secret : jamais renvoyé ni journalisé")

    _u = field_validator("userid")(lambda cls, v: _user(v))
    _c = field_validator("comment")(lambda cls, v: _note(v))

    @field_validator("password")
    @classmethod
    def _pw(cls, v: SecretStr | None):
        if v is not None and ("\n" in v.get_secret_value() or "\r" in v.get_secret_value()):
            raise ValueError("Mot de passe invalide")
        return v


class UserUpdate(Confirmed):
    enable: bool | None = None
    comment: str | None = Field(default=None, max_length=100)
    expire: int | None = Field(default=None, ge=0, le=MAX_EXPIRE)

    _c = field_validator("comment")(lambda cls, v: _note(v))


class Membership(Confirmed):
    group: str = Field(max_length=64)
    action: str = Field(pattern=r"^(add|remove)$")

    _g = field_validator("group")(lambda cls, v: _group(v))


class GroupCreate(Confirmed):
    groupid: str = Field(max_length=64)
    comment: str | None = Field(default=None, max_length=100)

    _g = field_validator("groupid")(lambda cls, v: _group(v))
    _c = field_validator("comment")(lambda cls, v: _note(v))


def protected_reason(userid: str, conn_user: str, admin_user: str) -> str | None:
    if userid in {ROOT, conn_user, admin_user}:
        return "Interdit : cette identité est protégée (Kaji, session administrateur ou root@pam)"
    return None


def dangerous_group_reason(group: str, acl: list[dict], roles: list[dict]) -> str | None:
    """Refuse d'ajouter quelqu'un à un groupe qui lui donnerait le pouvoir de modifier les droits."""
    for a in acl:
        if a.get("ugid") != group:                  # un identifiant de groupe ne peut pas contenir « @ » : aucune confusion possible avec un utilisateur ou un token
            continue
        privs = role_privs(roles, a.get("roleid") or "")
        if str(a.get("path", "")).startswith("/access") or a.get("roleid") == "Administrator" or privs is None or privs & FORBIDDEN_PRIVS:
            return "Interdit : ce groupe porte un droit qui permet de modifier les droits ou un rôle illisible (Administrator, Permissions.Modify, User.Modify…)"
    return None


def group_usage(group: str, groups: list[dict], acl: list[dict]) -> tuple[list[str], int]:
    members = next((list(g.get("users") or []) for g in groups if g.get("groupid") == group), [])
    return members, sum(1 for a in acl if a.get("ugid") == group and a.get("type") in (None, "group"))


def user_params(b: UserCreate) -> dict[str, str | int]:
    p: dict[str, str | int] = {"userid": b.userid, "enable": 1 if b.enable else 0}
    if b.comment:
        p["comment"] = b.comment
    if b.expire is not None:
        p["expire"] = b.expire
    if b.password is not None:
        p["password"] = b.password.get_secret_value()
    return p


def update_params(b: UserUpdate) -> dict[str, str | int]:
    p: dict[str, str | int] = {}
    if b.enable is not None:
        p["enable"] = 1 if b.enable else 0
    if b.comment is not None:
        p["comment"] = b.comment
    if b.expire is not None:
        p["expire"] = b.expire
    return p
