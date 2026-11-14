"""Commandes d'administration LOCALES, à lancer sur le serveur (jamais exposées par l'API).

    docker compose exec backend python -m app.admin_cli reset-password
    docker compose exec -T backend python -m app.admin_cli backup --stdout > kaji.db      (voir tools/backup.sh)
    docker compose exec backend python -m app.admin_cli verify
    docker compose run --rm -T --no-deps backend python -m app.admin_cli restore - --yes < kaji.db      (voir tools/restore.sh)
    docker compose exec backend python -m app.admin_cli rotate-token-key --yes      (rotation de KAJI_TOKEN_KEY : docs/deploiement.md)
    docker compose exec backend python -m app.admin_cli rotate-secret-key --yes     (rotation de KAJI_SECRET_KEY : docs/runbook.md)

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


def _token_keys() -> list[str]:
    """[clé courante des jetons personnels, précédente] ; vide si non configurée ; une clé inutilisable (trop courte, identique à KAJI_SECRET_KEY) lève `AdminError`."""
    from . import tokenkey
    try:
        return tokenkey.keys()
    except tokenkey.TokenKeyError as e:
        raise AdminError(str(e))


def rotate_cmd(argv: list[str]) -> int:
    """`rotate-token-key --yes [--drop-unreadable]` : ré-chiffre les jetons Proxmox personnels avec KAJI_TOKEN_KEY (la nouvelle) ; KAJI_TOKEN_KEY_PREVIOUS = l'ancienne."""
    from sqlalchemy.orm import Session

    from . import audit
    from .db import get_engine
    from .tokenrotate import RotationError, rotate_all
    if "--yes" not in argv:
        print("usage : rotate-token-key --yes [--drop-unreadable]   (fais d'abord une sauvegarde : tools/backup.sh)")
        return 2
    try:
        keys = _token_keys()
        with Session(get_engine()) as db:
            res = rotate_all(db, keys, drop_unreadable="--drop-unreadable" in argv)
            audit.record(db, username="cli-local", connection_id=None, action="token-key-rotated", target="user_tokens", status="started",
                         detail=f"{res.rotated} jeton(s) ré-chiffré(s), {res.dropped} supprimé(s)")
    except (AdminError, RotationError) as e:
        print(f"Échec : {e}")
        return 1
    print(f"Rotation faite : {res.rotated} jeton(s) ré-chiffré(s) sur {res.total}, {res.dropped} supprimé(s). "
          "Retire maintenant KAJI_TOKEN_KEY_PREVIOUS de la configuration et redémarre Kaji. Les anciennes sauvegardes restent chiffrées avec l'ANCIENNE clé : garde-la tant que tu en as besoin.")
    return 0


def rotate_secret_cmd(argv: list[str]) -> int:
    """`rotate-secret-key --yes` : ré-chiffre les jetons des connexions et les webhooks d'alerte avec KAJI_SECRET_KEY (la nouvelle) ; KAJI_SECRET_KEY_PREVIOUS = l'ancienne."""
    from sqlalchemy.orm import Session

    from . import audit
    from .config import check_secret_key, get_settings
    from .db import get_engine
    from .secretrotate import SecretRotationError, rotate_secret_key
    if "--yes" not in argv:
        print("usage : rotate-secret-key --yes   (fais d'abord une sauvegarde : tools/backup.sh ; les sessions tomberont toutes)")
        return 2
    s = get_settings()
    try:
        try:
            check_secret_key(s.kaji_secret_key)
        except RuntimeError as e:
            raise AdminError(str(e))
        with Session(get_engine()) as db:
            res = rotate_secret_key(db, s.kaji_secret_key, s.kaji_secret_key_previous.strip())
            audit.record(db, username="cli-local", connection_id=None, action="secret-key-rotated", target="connections, alert_rules", status="started",
                         detail=f"{res.connections} connexion(s) et {res.webhooks} webhook(s) ré-chiffré(s), {res.already_current} déjà à jour")
    except (AdminError, SecretRotationError) as e:
        print(f"Échec : {e}")
        return 1
    print(f"Rotation faite : {res.connections} jeton(s) de connexion et {res.webhooks} webhook(s) ré-chiffré(s), {res.already_current} déjà à jour. "
          "Retire maintenant KAJI_SECRET_KEY_PREVIOUS de la configuration et redémarre Kaji : toutes les sessions sont invalides (reconnexion). "
          "Les anciennes sauvegardes restent chiffrées avec l'ANCIENNE clé : garde-la tant que tu en as besoin.")
    return 0


def verify_cmd(argv: list[str]) -> int:
    from pathlib import Path

    from .backup import verify
    from .config import get_settings
    import tempfile
    try:
        wanted = _opt(argv, "--file")
        db = Path(wanted) if wanted and wanted != "-" else None if wanted == "-" else _db_file()
        keys = _token_keys()
    except AdminError as e:
        print(f"Échec : {e}")
        return 1
    if db is None:                                   # `--file -` : la copie arrive sur l'entrée standard (contrôler une sauvegarde sans la déposer dans le conteneur)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "copie.db"
            copy.write_bytes(sys.stdin.buffer.read())
            rep = verify(copy, get_settings().kaji_secret_key, keys)
    else:
        rep = verify(db, get_settings().kaji_secret_key, keys)
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
        rep, kept = restore(data, db, get_settings().kaji_secret_key, max(m.version for m in MIGRATIONS), _token_keys())
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
    if argv and argv[0] == "rotate-token-key":
        return rotate_cmd(argv[1:])
    if argv and argv[0] == "rotate-secret-key":
        return rotate_secret_cmd(argv[1:])
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
