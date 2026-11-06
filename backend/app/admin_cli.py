"""Commandes d'administration LOCALES, à lancer sur le serveur (jamais exposées par l'API).

    docker compose exec backend python -m app.admin_cli reset-password

Sert quand le mot de passe est perdu : la création de compte par l'interface n'est possible qu'à la toute première
utilisation, et elle serait ouverte à tout le monde si on supprimait le compte. Ici, seul quelqu'un qui a déjà un
accès au serveur peut agir. Le mot de passe est saisi de façon masquée, jamais passé en argument ni en variable.
"""
import getpass
import sys

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import audit
from .models import AdminUser, UserSession
from .security import hash_password

MIN_LENGTH = 12


class AdminError(Exception):
    pass


def reset_password(db: Session, new_password: str, username: str | None = None) -> str:
    """Change le mot de passe d'un administrateur existant et révoque TOUTES ses sessions. Renvoie son nom."""
    if len(new_password) < MIN_LENGTH:
        raise AdminError(f"Le mot de passe doit faire au moins {MIN_LENGTH} caractères.")
    users = db.scalars(select(AdminUser)).all()
    if not users:
        raise AdminError("Aucun compte administrateur : crée-le depuis l'interface (première configuration).")
    if username is None:
        if len(users) > 1:
            raise AdminError("Plusieurs comptes : précise lequel avec --user.")
        user = users[0]
    else:
        user = next((u for u in users if u.username == username), None)
        if user is None:
            raise AdminError(f"Compte inconnu : {username}")
    user.password_hash = hash_password(new_password)
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.commit()
    audit.record(db, username="cli-local", connection_id=None, action="password-reset", target=user.username,
                 status="started", detail="réinitialisé en local, toutes les sessions révoquées")
    return user.username


def main(argv: list[str]) -> int:
    from .db import get_engine, init_db

    if not argv or argv[0] != "reset-password":
        print(__doc__)
        return 2
    user = argv[argv.index("--user") + 1] if "--user" in argv and argv.index("--user") + 1 < len(argv) else None
    init_db()
    first = getpass.getpass("Nouveau mot de passe : ")
    if first != getpass.getpass("Confirmer : "):
        print("Les deux saisies diffèrent : rien n'a été changé.")
        return 1
    try:
        with Session(get_engine()) as db:
            name = reset_password(db, first, user)
    except AdminError as e:
        print(f"Échec : {e}")
        return 1
    print(f"Mot de passe de « {name} » changé ; toutes ses sessions sont révoquées.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
