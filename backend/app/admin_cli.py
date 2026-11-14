"""Commandes d'administration LOCALES, à lancer sur le serveur (jamais exposées par l'API).

    docker compose exec backend python -m app.admin_cli reset-password
    docker compose exec -T backend python -m app.admin_cli backup --stdout > kaji.db      (voir tools/backup.sh)
    docker compose exec backend python -m app.admin_cli verify
    docker compose run --rm -T --no-deps backend python -m app.admin_cli restore - --yes < kaji.db      (voir tools/restore.sh)

`backup` copie la base de façon cohérente (sans arrêter Kaji), `verify` relit les jetons et webhooks chiffrés avec la clé actuelle (sans rien afficher de secret),
`restore` remplace la base par une sauvegarde après l'avoir vérifiée (Kaji doit être arrêté ; la clé `KAJI_SECRET_KEY` n'est PAS dans la base : `docs/deploiement.md`).

`reset-password` sert quand le mot de passe est perdu : la création de compte par l'interface n'est possible qu'à la toute première
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


def _db_file():
    from pathlib import Path

    from sqlalchemy.engine import make_url

    from .config import get_settings
    url = get_settings().database_url
    path = make_url(url).database if url.startswith("sqlite") else None
    if not path or path == ":memory:":
        raise AdminError("Ces commandes ne gèrent qu'une base SQLite dans un fichier.")
    return Path(path)


def _opt(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


def backup_cmd(argv: list[str]) -> int:
    """`backup --out FICHIER` ou `backup --stdout` (flux binaire sur la sortie standard ; les messages vont sur la sortie d'erreur)."""
    import tempfile
    from pathlib import Path

    from .backup import BackupError, key_fingerprint, make_backup
    from .config import get_settings
    try:
        db = _db_file()
        if "--stdout" in argv:
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "kaji.db"
                size = make_backup(db, dest)
                sys.stdout.buffer.write(dest.read_bytes())
                sys.stdout.buffer.flush()
        elif _opt(argv, "--out"):
            dest = Path(_opt(argv, "--out"))
            size = make_backup(db, dest)
        else:
            print("usage : backup --out FICHIER | backup --stdout", file=sys.stderr)
            return 2
    except (AdminError, BackupError) as e:
        print(f"Échec : {e}", file=sys.stderr)
        return 1
    print(f"Sauvegarde de la base : {size} octets. Empreinte de la clé : {key_fingerprint(get_settings().kaji_secret_key)} "
          "(la clé elle-même n'est PAS dans la sauvegarde : garde `.env` à part).", file=sys.stderr)
    return 0


def verify_cmd(argv: list[str]) -> int:
    from pathlib import Path

    from .backup import verify
    from .config import get_settings
    import tempfile
    try:
        wanted = _opt(argv, "--file")
        db = Path(wanted) if wanted and wanted != "-" else None if wanted == "-" else _db_file()
    except AdminError as e:
        print(f"Échec : {e}")
        return 1
    if db is None:                                   # `--file -` : la copie arrive sur l'entrée standard (contrôler une sauvegarde sans la déposer dans le conteneur)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "copie.db"
            copy.write_bytes(sys.stdin.buffer.read())
            rep = verify(copy, get_settings().kaji_secret_key)
    else:
        rep = verify(db, get_settings().kaji_secret_key)
    print(rep.render())
    return 0 if rep.ok else 1


def restore_cmd(argv: list[str]) -> int:
    """`restore FICHIER --yes` ou `restore - --yes` (lit la sauvegarde sur l'entrée standard). Kaji doit être arrêté."""
    from pathlib import Path

    from .backup import BackupError, restore
    from .config import get_settings
    from .migrations import MIGRATIONS
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1 or "--yes" not in argv:
        print("usage : restore FICHIER|- --yes   (remplace la base ; Kaji doit être arrêté ; l'ancienne base est gardée à côté)")
        return 2
    try:
        db = _db_file()
        data = sys.stdin.buffer.read() if args[0] == "-" else Path(args[0]).read_bytes()
        rep, kept = restore(data, db, get_settings().kaji_secret_key, max(m.version for m in MIGRATIONS))
    except (AdminError, BackupError, OSError) as e:
        print(f"Échec : {e}")
        return 1
    print(rep.render())
    print(f"Base restaurée. Ancienne base conservée : {kept.name if kept else 'aucune (base neuve)'}. Démarre Kaji, puis lance `verify`.")
    return 0


def main(argv: list[str]) -> int:
    from .db import get_engine, init_db

    if argv and argv[0] == "backup":
        return backup_cmd(argv[1:])
    if argv and argv[0] == "verify":
        return verify_cmd(argv[1:])
    if argv and argv[0] == "restore":
        return restore_cmd(argv[1:])
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
