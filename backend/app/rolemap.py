"""Groupes de l'annuaire ou du SSO → rôle de Kaji (lot #443). Détail : `docs/api/auth-settings.md`.

Une entreprise indique « le groupe `informatique` est administrateur de Kaji » : à CHAQUE connexion par l'annuaire ou le SSO, le rôle du compte est recalculé d'après ses groupes.
- Sans groupe saisi (`admin_group` et `operator_group` vides, défaut), AUCUN rôle n'est touché : le rôle reste celui du compte de Kaji.
- Correspondance EXACTE (insensible à la casse et aux espaces autour de `,` et `=`), jamais « contient » : « kaji-admins-test » n'est pas « kaji-admins ».
- Administrateur seulement si `allow_admin` est vrai ; opérateur pour le groupe opérateur ; sinon le rôle par défaut du fournisseur (`default_role`).
- Le DERNIER administrateur n'est jamais rétrogradé (Kaji ne peut pas se retrouver sans administrateur).
- Retirer quelqu'un du groupe lui retire le rôle à sa connexion suivante ; une session déjà ouverte garde l'ancien rôle jusqu'à sa déconnexion ou son expiration.
"""
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import roles
from .models import AdminUser


def norm(value: str) -> str:
    """Forme de comparaison d'un nom de groupe ou d'un DN : minuscules, sans espaces autour des virgules et des signes égal."""
    return re.sub(r"\s*([,=])\s*", r"\1", value.strip()).lower()


def as_list(raw) -> list[str]:
    """Les groupes lus chez le fournisseur : une chaîne, ou une liste de chaînes ; le reste est ignoré."""
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple, set)):
        return [x for x in raw if isinstance(x, str)]
    return []


def target_role(s, provider: str, groups) -> str | None:
    """Le rôle que donnent les groupes, ou `None` si la correspondance n'est pas configurée (rien à toucher)."""
    admin_group = norm(getattr(s, f"kaji_{provider}_admin_group"))
    operator_group = norm(getattr(s, f"kaji_{provider}_operator_group"))
    if not admin_group and not operator_group:
        return None
    mine = {norm(g) for g in as_list(groups)}
    if admin_group and admin_group in mine and getattr(s, f"kaji_{provider}_allow_admin"):
        return "admin"
    if operator_group and operator_group in mine:
        return "operator"
    default = getattr(s, f"kaji_{provider}_default_role")
    return default if default in ("operator", "viewer") else "viewer"


def new_account_role(s, provider: str, groups) -> str | None:
    """Rôle d'un compte créé à la première connexion : celui des groupes (administrateur compris, SEULEMENT par groupe), sinon le rôle par défaut ; `None` = pas de création."""
    mapped = target_role(s, provider, groups)
    if mapped is not None:
        return mapped
    default = getattr(s, f"kaji_{provider}_default_role")
    return default if default in ("operator", "viewer") else None


def apply(db: Session, user: AdminUser, target: str | None) -> tuple[str, str] | None:
    """Applique `target` au compte. Renvoie `(ancien, nouveau)` si le rôle a changé, sinon `None` (rien à faire, ou rétrogradation du dernier administrateur refusée)."""
    current = roles.normalize(user.role)
    if target is None or target == current:
        return None
    if current == "admin" and (db.scalar(select(func.count()).select_from(AdminUser).where(AdminUser.role == "admin")) or 0) <= 1:
        return None
    user.role = target
    db.commit()
    return current, target
