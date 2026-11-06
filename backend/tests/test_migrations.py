import os
import stat

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db import Base
from app.migrations import (Migration, SchemaTooNew, add_column, backup_sqlite, run_migrations, status)

V1 = Migration(1, "schéma initial")
calls = {"n": 0}


def add_note(conn):
    calls["n"] += 1
    add_column(conn, "connections", "note TEXT")


V2 = Migration(2, "note sur les connexions", add_note)


@pytest.fixture
def db_path(tmp_path):
    calls["n"] = 0
    return tmp_path / "kaji.db"


def engine_for(path):
    return create_engine(f"sqlite:///{path}")


def legacy_db(path):
    """Une base d'avant le système de migrations : tables présentes, aucune table schema_migrations, des données."""
    e = engine_for(path)
    from app import models  # noqa: F401
    Base.metadata.create_all(e)
    with e.begin() as c:
        c.execute(text("INSERT INTO admin_users (username, password_hash, created_at) VALUES ('admin', 'h', '2026-01-01')"))
        c.execute(text("INSERT INTO connections (name, host, port, user, token_id, token_secret_enc, verify_ssl, created_at) "
                       "VALUES ('perso', '10.0.0.1', 8006, 'kaji@pve', 'kaji', 'chiffre', 0, '2026-01-01')"))
    return e


def versions(e):
    with e.connect() as c:
        return [r[0] for r in c.execute(text("SELECT version FROM schema_migrations ORDER BY version"))]


def columns(e, table):
    return {c["name"] for c in inspect(e).get_columns(table)}


# ---------- bases neuves et anciennes ----------

def test_fresh_database_is_stamped_up_to_date_without_replaying_migrations(db_path):
    e = engine_for(db_path)
    r = run_migrations(e, [V1, V2])
    assert versions(e) == [1, 2] and calls["n"] == 0 and r["applied"] == [] and r["backup"] is None
    assert {"admin_users", "connections", "audit_log", "user_sessions", "schema_migrations"} <= set(inspect(e).get_table_names())


def test_legacy_database_is_recognised_and_stamped_version_1_keeping_its_data(db_path):
    e = legacy_db(db_path)
    r = run_migrations(e, [V1])
    assert versions(e) == [1] and r["applied"] == [] and r["backup"] is None
    with e.connect() as c:
        assert c.execute(text("SELECT username FROM admin_users")).scalar() == "admin"
        assert c.execute(text("SELECT name FROM connections")).scalar() == "perso"


def test_legacy_database_gets_pending_migrations_after_a_backup(db_path):
    e = legacy_db(db_path)
    r = run_migrations(e, [V1, V2])
    assert r["applied"] == [2] and (r["from"], r["to"]) == (1, 2) and versions(e) == [1, 2]
    assert "note" in columns(e, "connections")
    with e.connect() as c:
        assert c.execute(text("SELECT name FROM connections")).scalar() == "perso"          # données conservées
    bak = r["backup"]
    assert bak is not None and bak.exists() and stat.S_IMODE(os.stat(bak).st_mode) == 0o600
    old = create_engine(f"sqlite:///{bak}")
    assert "note" not in columns(old, "connections")                                          # la sauvegarde est AVANT la migration
    with old.connect() as c:
        assert c.execute(text("SELECT name FROM connections")).scalar() == "perso"


def test_rerun_applies_nothing_and_makes_no_new_backup(db_path):
    e = legacy_db(db_path)
    run_migrations(e, [V1, V2])
    before = sorted(db_path.parent.glob("kaji.db.bak-*"))
    r = run_migrations(e, [V1, V2])
    assert r["applied"] == [] and r["backup"] is None and calls["n"] == 1
    assert sorted(db_path.parent.glob("kaji.db.bak-*")) == before


# ---------- sûreté ----------

def test_database_newer_than_the_code_is_refused_and_left_untouched(db_path):
    e = legacy_db(db_path)
    run_migrations(e, [V1])
    with e.begin() as c:
        c.execute(text("INSERT INTO schema_migrations VALUES (99, 'du futur', '2030-01-01')"))
    with pytest.raises(SchemaTooNew, match="99"):
        run_migrations(e, [V1, V2])
    assert versions(e) == [1, 99] and "note" not in columns(e, "connections")


def test_failing_migration_stops_with_a_clear_error_and_does_not_record_itself(db_path):
    e = legacy_db(db_path)

    def boom(conn):
        raise ValueError("boum")
    with pytest.raises(RuntimeError, match=r"Migration 2 .*boum"):
        run_migrations(e, [V1, Migration(2, "casse", boom), Migration(3, "jamais", add_note)])
    assert versions(e) == [1] and calls["n"] == 0                                             # la 3 n'a pas été tentée
    assert list(db_path.parent.glob("kaji.db.bak-v1-*"))                                      # la sauvegarde existe


def test_failure_after_a_schema_change_leaves_nothing_half_done(db_path):
    """Une migration qui modifie le schéma puis échoue ne doit laisser aucune trace : tout ou rien."""
    e = legacy_db(db_path)

    def half(conn):
        conn.execute(text("CREATE TABLE a_moitie (x INTEGER)"))
        conn.execute(text("ALTER TABLE connections ADD COLUMN moitie TEXT"))
        raise ValueError("échec après le DDL")
    with pytest.raises(RuntimeError):
        run_migrations(e, [V1, Migration(2, "a moitié", half)])
    assert "a_moitie" not in inspect(e).get_table_names() and "moitie" not in columns(e, "connections")
    assert versions(e) == [1]


def test_add_column_helper_is_replayable(db_path):
    e = legacy_db(db_path)
    with e.begin() as c:
        add_column(c, "connections", "note TEXT")
        add_column(c, "connections", "note TEXT")                                            # deuxième appel : sans effet
    assert "note" in columns(e, "connections")


# ---------- sauvegardes et état ----------

def test_only_the_last_five_backups_are_kept(db_path):
    e = legacy_db(db_path)
    run_migrations(e, [V1])
    for v in range(1, 8):
        backup_sqlite(e, v)
    assert len(list(db_path.parent.glob("kaji.db.bak-v*"))) == 5


def test_memory_database_has_no_backup_and_still_migrates():
    e = create_engine("sqlite://", poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool)
    assert backup_sqlite(e, 1) is None
    assert run_migrations(e, [V1, V2])["applied"] == []


def test_status_reports_current_latest_and_pending(db_path):
    e = legacy_db(db_path)
    assert status(e, [V1, V2])["current"] == 0                                                # pas encore marquée
    run_migrations(e, [V1])
    assert status(e, [V1, V2]) == {"current": 1, "latest": 2, "pending": [2]}
    run_migrations(e, [V1, V2])
    assert status(e, [V1, V2]) == {"current": 2, "latest": 2, "pending": []}
