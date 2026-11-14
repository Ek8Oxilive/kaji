"""Sauvegarde, vérification et restauration de la base de Kaji (commandes LOCALES : `python -m app.admin_cli backup | verify | restore`).

Ce qui se sauvegarde : le fichier SQLite (comptes et rôles, connexions Proxmox avec leur jeton CHIFFRÉ, webhooks d'alertes chiffrés, planifications, audit) ET
`KAJI_SECRET_KEY` (dans `.env`), qui n'est JAMAIS dans la base. L'une sans l'autre est inutilisable ; `verify` le constate en relisant chaque secret chiffré.

- `make_backup` : copie cohérente d'une base EN SERVICE (API de sauvegarde de SQLite, pas une copie de fichier : une copie pendant une écriture peut être déchirée).
- `verify` : relit la base avec la clé fournie ; dit combien de jetons et de webhooks se déchiffrent. N'affiche jamais une valeur, seulement des nombres et une empreinte de la clé.
- `restore` : remplace la base par une sauvegarde, après avoir vérifié qu'elle est saine, pas trop récente pour ce code, et **lisible avec la clé actuelle** ; l'ancienne base est gardée à côté.
"""
import hashlib
import os
import sqlite3
import tempfile
from urllib.parse import quote
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import tokenkey
from .crypto import decrypt

SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = ("admin_users", "connections", "schema_migrations")


class BackupError(Exception):
    pass


def _ro(path: Path) -> sqlite3.Connection:
    """Connexion en lecture seule (le chemin est échappé : un `?` ou un `#` dans un nom de dossier casserait l'URI)."""
    return sqlite3.connect(f"file:{quote(str(Path(path).resolve()))}?mode=ro", uri=True)


def key_fingerprint(secret_key: str) -> str:
    """8 caractères qui permettent de reconnaître la clé (« est-ce la même que celle de la sauvegarde ? ») sans la révéler."""
    return hashlib.sha256(b"kaji-key-fingerprint-v1:" + secret_key.encode()).hexdigest()[:8]


def make_backup(db_path: Path, dest: Path) -> int:
    """Copie cohérente de la base (même en service) vers `dest`, en 600. Renvoie la taille en octets. `dest` existant : refusé."""
    db_path, dest = Path(db_path), Path(dest)
    if not db_path.is_file():
        raise BackupError(f"Base introuvable : {db_path}")
    if dest.exists():
        raise BackupError(f"{dest} existe déjà : rien n'a été écrit.")
    tmp = dest.with_name(dest.name + ".partiel")
    tmp.unlink(missing_ok=True)
    src = _ro(db_path)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)
    return dest.stat().st_size


@dataclass
class Report:
    ok: bool = True
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    schema: int = 0
    tokens: tuple[int, int] = (0, 0)            # (déchiffrés, total)
    webhooks: tuple[int, int] = (0, 0)
    user_tokens: tuple[int, int] = (0, 0)       # jetons Proxmox PERSONNELS (clé séparée)

    def line(self, text: str) -> None:
        self.lines.append(text)

    def problem(self, text: str) -> None:
        self.ok = False
        self.problems.append(text)

    def render(self) -> str:
        out = list(self.lines) + [f"PROBLÈME : {p}" for p in self.problems]
        out.append("Résultat : " + ("OK" if self.ok else "ÉCHEC"))
        return "\n".join(out)


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}      # `table` est une constante de ce module


def verify(db_path: Path, secret_key: str, token_keys: list[str] | None = None) -> Report:
    """Relit la base en lecture seule avec `secret_key` (jeton partagé, webhooks) et `token_keys` (clé SÉPARÉE des jetons personnels : [courante, précédente]).
    Ne modifie rien, n'affiche aucune valeur secrète."""
    rep = Report()
    db_path = Path(db_path)
    if not db_path.is_file():
        rep.problem(f"Base introuvable : {db_path}")
        return rep
    rep.line(f"Clé : empreinte {key_fingerprint(secret_key)}")
    try:
        db = _ro(db_path)
        db.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError:
        rep.problem("Ce fichier n'est pas une base SQLite lisible.")
        return rep
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        rep.line(f"Intégrité SQLite : {integrity}")
        if integrity != "ok":
            rep.problem("La base est endommagée (PRAGMA integrity_check).")
        tables = _tables(db)
        missing = [t for t in REQUIRED_TABLES if t not in tables]
        if missing:
            rep.problem("Tables absentes : " + ", ".join(missing) + " (ce n'est pas une base de Kaji ?)")
            return rep
        rep.schema = db.execute("SELECT coalesce(max(version), 0) FROM schema_migrations").fetchone()[0]
        rep.line(f"Schéma n° {rep.schema}")

        roles = {"admin": 0, "operator": 0, "viewer": 0}
        if "role" in _columns(db, "admin_users"):
            for role, n in db.execute("SELECT role, count(*) FROM admin_users GROUP BY role"):
                roles[role] = roles.get(role, 0) + n
        else:
            roles["admin"] = db.execute("SELECT count(*) FROM admin_users").fetchone()[0]
        total = sum(roles.values())
        rep.line(f"Comptes de Kaji : {total} (" + ", ".join(f"{r} {n}" for r, n in roles.items()) + ")")
        if total == 0:
            rep.problem("Aucun compte administrateur dans cette base.")
        elif roles.get("admin", 0) == 0:
            rep.problem("Aucun compte administrateur (rôle « admin ») dans cette base.")

        encrypted = list(db.execute("SELECT token_secret_enc FROM connections"))
        good = sum(1 for (c,) in encrypted if _readable(secret_key, c))
        rep.tokens = (good, len(encrypted))
        pinned = 0
        if "tls_cert_pem" in _columns(db, "connections"):
            pinned = db.execute("SELECT count(*) FROM connections WHERE tls_cert_pem IS NOT NULL AND tls_cert_pem != ''").fetchone()[0]
        rep.line(f"Connexions Proxmox : {len(encrypted)} ; jetons déchiffrés : {good}/{len(encrypted)} ; certificats épinglés : {pinned}")
        if good != len(encrypted):
            rep.problem(f"{len(encrypted) - good} jeton(s) Proxmox illisible(s) avec cette clé : ce n'est pas la clé de cette base.")

        if "user_tokens" in tables:
            personal = [r[0] for r in db.execute("SELECT secret_enc FROM user_tokens")]
            expired = db.execute("SELECT count(*) FROM user_tokens WHERE expires_at < datetime('now')").fetchone()[0]
            if not personal:
                rep.line("Jetons Proxmox personnels : 0")
            elif not token_keys:
                rep.user_tokens = (0, len(personal))
                rep.line(f"Jetons Proxmox personnels : {len(personal)} ; clé KAJI_TOKEN_KEY non fournie : non vérifiés")
                rep.problem(f"{len(personal)} jeton(s) Proxmox personnel(s) dans cette base, mais la clé KAJI_TOKEN_KEY (ou KAJI_TOKEN_KEY_FILE) n'est pas configurée : ils seraient inutilisables.")
            else:
                good = sum(1 for c in personal if tokenkey.readable(c, token_keys))
                rep.user_tokens = (good, len(personal))
                rep.line(f"Jetons Proxmox personnels : {len(personal)} ; déchiffrés : {good}/{len(personal)} ; échéance dépassée : {expired}")
                if good != len(personal):
                    rep.problem(f"{len(personal) - good} jeton(s) Proxmox personnel(s) illisible(s) avec la clé KAJI_TOKEN_KEY : ce n'est pas la clé de cette base (rotation oubliée ?).")
        if "alert_rules" in tables:
            rules = db.execute("SELECT count(*) FROM alert_rules").fetchone()[0]
            hooks = list(db.execute("SELECT webhook_enc FROM alert_rules WHERE webhook_enc IS NOT NULL AND webhook_enc != ''"))
            ok_hooks = sum(1 for (c,) in hooks if _readable(secret_key, c))
            rep.webhooks = (ok_hooks, len(hooks))
            rep.line(f"Règles d'alerte : {rules} ; webhooks déchiffrés : {ok_hooks}/{len(hooks)}")
            if ok_hooks != len(hooks):
                rep.problem(f"{len(hooks) - ok_hooks} webhook(s) d'alerte illisible(s) avec cette clé.")
        else:
            rep.line("Règles d'alerte : table absente (base d'une version plus ancienne)")
        if "scheduled_actions" in tables:
            n, active = db.execute("SELECT count(*), coalesce(sum(enabled), 0) FROM scheduled_actions").fetchone()
            rep.line(f"Actions planifiées : {n} ({active} active(s))")
        else:
            rep.line("Actions planifiées : table absente (base d'une version plus ancienne)")
        if "audit_log" in tables:
            rep.line(f"Journal d'audit : {db.execute('SELECT count(*) FROM audit_log').fetchone()[0]} entrée(s)")
    except sqlite3.DatabaseError as e:
        rep.problem(f"Lecture impossible ({type(e).__name__}).")
    finally:
        db.close()
    return rep


def _readable(secret_key: str, ciphertext: str | None) -> bool:
    try:
        decrypt(secret_key, ciphertext or "")
        return True
    except ValueError:
        return False


def restore(source: bytes | Path, db_path: Path, secret_key: str, latest_schema: int, token_keys: list[str] | None = None) -> tuple[Report, Path | None]:
    """Remplace `db_path` par la sauvegarde `source` (octets ou fichier). Refuse (rien n'est modifié) si le fichier n'est pas une base saine de Kaji, si son schéma est
    plus récent que ce code, ou si un jeton ou un webhook n'est pas lisible avec `secret_key`. L'ancienne base est conservée à côté (`….avant-restauration-<date>`) ;
    les fichiers `-journal`, `-wal` et `-shm` de l'ancienne base sont retirés (un journal d'une autre base corromprait la nouvelle). Le service doit être ARRÊTÉ.
    Renvoie (rapport, chemin de l'ancienne base ou None s'il n'y en avait pas)."""
    db_path = Path(db_path)
    data = Path(source).read_bytes() if isinstance(source, Path) else source
    if not data.startswith(SQLITE_HEADER):
        raise BackupError("Ce fichier n'est pas une base SQLite : rien n'a été modifié.")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=db_path.name + ".restauration-", dir=db_path.parent)      # même dossier : le remplacement final est atomique
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        rep = verify(tmp, secret_key, token_keys)
        if not rep.ok:
            raise BackupError("La sauvegarde est refusée, rien n'a été modifié :\n" + rep.render())
        if rep.schema > latest_schema:
            raise BackupError(f"La sauvegarde est au schéma n° {rep.schema}, ce code ne connaît que le n° {latest_schema} : mets Kaji à jour d'abord. Rien n'a été modifié.")
        kept = None
        if db_path.exists():
            kept = db_path.with_name(f"{db_path.name}.avant-restauration-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
            os.replace(db_path, kept)
        try:
            os.replace(tmp, db_path)
        except OSError:
            if kept:
                os.replace(kept, db_path)
            raise
        for suffix in ("-journal", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        return rep, kept          # 600 : le fichier temporaire (mkstemp, puis chmod) l'était déjà
    finally:
        tmp.unlink(missing_ok=True)
