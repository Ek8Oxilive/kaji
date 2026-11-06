"""Migrations de schéma : versionnées, sauvegardées, transactionnelles.

Règle pour les contributeurs
- **Nouvelle table** : l'ajouter dans `models.py` suffit (`create_all` la crée).
- **Modifier une table existante** (ajouter, renommer, supprimer une colonne, ajouter un index…) : écrire une migration,
  l'ajouter à `MIGRATIONS` avec le numéro suivant, **et** refléter le changement dans `models.py`.

Une base neuve reçoit le schéma final directement (`create_all`) et est marquée « à jour » sans rejouer les migrations.
Une base d'avant ce système est reconnue (tables présentes, pas de `schema_migrations`) et marquée à la version 1.

CLI : `python -m app.migrations status` (ou `upgrade`).
"""
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.engine import make_url

KEEP_BACKUPS = 5


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: Callable[[Connection], None] | None = None     # None = état initial (rien à exécuter)


def add_column(conn: Connection, table: str, ddl: str) -> None:
    """ALTER TABLE … ADD COLUMN, sans échec si la colonne existe déjà (migration rejouable)."""
    name = ddl.split()[0]
    if name not in {c["name"] for c in inspect(conn).get_columns(table)}:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


MIGRATIONS: list[Migration] = [
    Migration(1, "schéma initial"),
]


class SchemaTooNew(RuntimeError):
    pass


def _versions(conn: Connection) -> dict[int, str]:
    return {r[0]: r[1] for r in conn.execute(text("SELECT version, name FROM schema_migrations ORDER BY version"))}


def _record(conn: Connection, m: Migration) -> None:
    conn.execute(text("INSERT INTO schema_migrations (version, name, applied_at) VALUES (:v, :n, :t)"),
                 {"v": m.version, "n": m.name, "t": datetime.now(timezone.utc).isoformat()})


def backup_sqlite(engine: Engine, from_version: int) -> Path | None:
    """Copie cohérente de la base avant migration (API de sauvegarde SQLite), en 600. None pour une base en mémoire."""
    path = make_url(str(engine.url)).database
    if engine.dialect.name != "sqlite" or not path or path == ":memory:":
        return None
    dest = Path(f"{path}.bak-v{from_version}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
    src, dst = sqlite3.connect(path), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    dest.chmod(0o600)
    for old in sorted(Path(path).parent.glob(f"{Path(path).name}.bak-v*"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return dest


def _apply_atomically(engine: Engine, m: Migration) -> None:
    """Une transaction par migration : tout ou rien, schéma compris.

    Le pilote SQLite de Python n'ouvre pas de transaction avant un ALTER/CREATE TABLE : sans BEGIN explicite, un échec en
    cours de route laisserait une partie du schéma modifié (constaté par test). D'où le BEGIN ci-dessous."""
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN")
        try:
            if m.upgrade:
                m.upgrade(conn)
            _record(conn, m)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def run_migrations(engine: Engine, migrations: list[Migration] | None = None) -> dict:
    """Met la base à jour. Renvoie {from, to, applied, backup}. Refuse une base plus récente que le code."""
    from .db import Base       # import tardif : db importe ce module
    from . import models       # noqa: F401  (enregistre les tables)

    migrations = sorted(migrations if migrations is not None else MIGRATIONS, key=lambda m: m.version)
    latest = migrations[-1].version
    with engine.begin() as conn:
        insp = inspect(conn)
        had_registry, legacy = insp.has_table("schema_migrations"), insp.has_table("admin_users")
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations "
                          "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"))
    Base.metadata.create_all(engine)                  # tables manquantes uniquement

    with engine.begin() as conn:
        done = _versions(conn)
        if not done:
            # Base neuve : schéma final déjà créé, tout est « appliqué ». Base d'avant ce système : version 1.
            for m in migrations if not legacy else [m for m in migrations if m.version == 1]:
                _record(conn, m)
            done = _versions(conn)
    current = max(done)
    if current > latest:
        raise SchemaTooNew(f"La base est à la version {current}, ce code ne connaît que la {latest} : "
                           "mets Kaji à jour (ou restaure une sauvegarde d'avant la mise à niveau de la base).")
    pending = [m for m in migrations if m.version > current]
    result = {"from": current, "to": current, "applied": [], "backup": None}
    if not pending:
        return result
    result["backup"] = backup_sqlite(engine, current)
    for m in pending:
        try:
            _apply_atomically(engine, m)
        except Exception as e:
            raise RuntimeError(f"Migration {m.version} « {m.name} » échouée, base inchangée par cette migration "
                               f"(sauvegarde : {result['backup']}) : {e}") from e
        result["applied"].append(m.version); result["to"] = m.version
    return result


def status(engine: Engine, migrations: list[Migration] | None = None) -> dict:
    migrations = migrations if migrations is not None else MIGRATIONS
    with engine.connect() as conn:
        done = _versions(conn) if inspect(conn).has_table("schema_migrations") else {}
    return {"current": max(done, default=0), "latest": max(m.version for m in migrations),
            "pending": [m.version for m in migrations if m.version > max(done, default=0)]}


if __name__ == "__main__":
    from .db import get_engine
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    eng = get_engine()
    print(status(eng) if cmd == "status" else run_migrations(eng) if cmd == "upgrade" else f"commande inconnue : {cmd}")
