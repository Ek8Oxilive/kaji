"""Mise à jour d'une version à l'autre : les bases d'exemple de `backend/tests/fixtures/db/` sont migrées vers le code courant (jalon J3, ticket #456).

Chaque base a été produite par le VRAI code d'une version (`tools/snapshot_db.py`) : `kaji-schema1-…` et `kaji-schema2-…` sont deux anciens états du schéma, `kaji-v1.0.0-rc1.db` la première
version étiquetée. Une base par étiquette Git est exigée (voir `docs/images-et-versions.md`) : la CI échoue si on étiquette une version sans avoir conservé sa base d'exemple.

Ce que ça garantit : aucune ligne ni colonne d'origine perdue ou modifiée, les mots de passe, jetons et webhooks se relisent, les comptes existants gardent leur rôle (ou deviennent
administrateurs quand le rôle n'existait pas), la migration est rejouable, une base plus récente que le code est refusée, et un retour arrière par sauvegarde fonctionne.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.backup import restore, verify
from app.crypto import decrypt
from app.migrations import MIGRATIONS, SchemaTooNew, run_migrations, status
from app.models import AdminUser, AlertRule, Connection, ScheduledAction
from app.security import verify_password

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "db"
FIXTURE_KEY = "cle-de-test-publique-pour-les-bases-d-exemple-0123456789"       # celle de tools/snapshot_db.py
PASSWORD = "mot-de-passe-de-test-12"
LATEST = max(m.version for m in MIGRATIONS)
DBS = sorted(FIXTURES.glob("kaji-*.db"))


def engine_for(path: Path):
    return create_engine(URL.create("sqlite", database=str(path)))


def snapshot(path: Path) -> dict[str, list[tuple]]:
    """Toutes les lignes de toutes les tables, sauf le registre des migrations (qui doit justement changer)."""
    c = sqlite3.connect(path)
    out = {}
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations'"):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        out[t] = (cols, c.execute(f"SELECT {', '.join(cols)} FROM {t} ORDER BY 1").fetchall())
    c.close()
    return out


def version_of(path: Path) -> int:
    c = sqlite3.connect(path)
    v = c.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    c.close()
    return v


@pytest.fixture(params=DBS, ids=[p.name for p in DBS])
def old_db(request, tmp_path):
    copy = tmp_path / "kaji.db"
    shutil.copy(request.param, copy)
    os.chmod(copy, 0o600)
    return copy


def test_the_example_databases_exist_and_cover_old_schemas_and_the_first_release():
    names = [p.name for p in DBS]
    assert "kaji-v1.0.0-rc1.db" in names
    assert {version_of(p) for p in DBS} >= {1, 2, 3}                      # au moins un exemple par état du schéma connu
    for p in DBS:
        assert verify(p, FIXTURE_KEY).ok, f"{p.name} n'est plus lisible avec la clé de test publique"


def test_every_example_database_migrates_to_the_current_code_without_losing_a_single_value(old_db):
    before_version = version_of(old_db)
    before = snapshot(old_db)
    result = run_migrations(engine_for(old_db))
    assert result["from"] == before_version and result["to"] == LATEST
    assert result["applied"] == list(range(before_version + 1, LATEST + 1))
    after = snapshot(old_db)
    for table, (cols, rows) in before.items():
        assert table in after, f"la table {table} a disparu"
        new_cols, _ = after[table]
        assert set(cols) <= set(new_cols), f"{table} : colonnes perdues {set(cols) - set(new_cols)}"
        c = sqlite3.connect(old_db)
        kept = c.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY 1").fetchall()
        c.close()
        assert kept == rows, f"{table} : des valeurs d'origine ont changé"      # valeurs d'origine identiques (colonnes ajoutées exclues)
    assert version_of(old_db) == LATEST


def test_a_backup_of_the_old_database_is_kept_when_a_migration_runs(old_db):
    old_rows, old_version = snapshot(old_db), version_of(old_db)
    result = run_migrations(engine_for(old_db))
    if result["applied"]:
        backup = Path(result["backup"])
        assert backup.exists() and backup.stat().st_mode & 0o777 == 0o600
        assert version_of(backup) == old_version                             # la copie est encore à l'ANCIEN schéma
        assert {t: v for t, v in snapshot(backup).items() if t in old_rows} == old_rows       # et contient les mêmes données (pas octet pour octet : SQLite met à jour son compteur)
        assert verify(backup, FIXTURE_KEY).ok
    else:
        assert result["backup"] is None


def test_after_migration_accounts_tokens_webhooks_and_schedules_are_readable_by_the_current_code(old_db):
    old_has_roles = "role" in {r[1] for r in sqlite3.connect(old_db).execute("PRAGMA table_info(admin_users)")}
    run_migrations(engine_for(old_db))
    rep = verify(old_db, FIXTURE_KEY)
    assert rep.ok and rep.tokens == (1, 1) and rep.schema == LATEST
    with Session(engine_for(old_db)) as db:
        users = {u.username: u for u in db.scalars(select(AdminUser))}
        assert set(users) == {"alice", "bob"} and all(verify_password(PASSWORD, u.password_hash) for u in users.values())
        assert users["alice"].role == "admin"
        assert users["bob"].role == ("operator" if old_has_roles else "admin")      # le rôle d'avant est gardé ; sans rôle, le compte reste administrateur
        conn = db.scalars(select(Connection)).one()
        assert decrypt(FIXTURE_KEY, conn.token_secret_enc) == "jeton-fictif-0123456789" and (conn.tls_cert_pem is None or "FICTIF" in conn.tls_cert_pem)
        for rule in db.scalars(select(AlertRule)):
            assert rule.webhook_enc is None or decrypt(FIXTURE_KEY, rule.webhook_enc).startswith("https://hooks.example.org/")
        for sched in db.scalars(select(ScheduledAction)):
            assert (sched.vmid, sched.action) == (115, "start")


def test_the_migration_is_replayable_and_the_command_line_agrees(old_db):
    run_migrations(engine_for(old_db))
    again = run_migrations(engine_for(old_db))
    assert again["applied"] == [] and again["backup"] is None and again["from"] == again["to"] == LATEST
    assert status(engine_for(old_db)) == {"current": LATEST, "latest": LATEST, "pending": []}
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{old_db}", "KAJI_SECRET_KEY": FIXTURE_KEY, "KAJI_SCHEDULER": "false"}
    r = subprocess.run([sys.executable, "-m", "app.migrations", "status"], cwd=ROOT / "backend", env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "'pending': []" in r.stdout, r.stdout + r.stderr


def test_a_database_newer_than_the_code_is_refused_and_left_untouched(old_db):
    run_migrations(engine_for(old_db))
    c = sqlite3.connect(old_db); c.execute("INSERT INTO schema_migrations VALUES (?, 'futur', '2099-01-01')", (LATEST + 1,)); c.commit(); c.close()
    before = old_db.read_bytes()
    with pytest.raises(SchemaTooNew, match="restaure une sauvegarde"):
        run_migrations(engine_for(old_db))
    assert old_db.read_bytes() == before


def test_rolling_back_restores_the_old_version_database_which_migrates_again(old_db, tmp_path):
    """Retour arrière : on a mis à jour, puis on restaure la sauvegarde d'AVANT (tools/restore.sh) ; l'ancienne base repart et se remigre."""
    old_bytes = old_db.read_bytes()
    run_migrations(engine_for(old_db))                                  # « mise à jour » : la base d'exploitation est migrée
    upgraded_version = version_of(old_db)
    rep, kept = restore(old_bytes, old_db, FIXTURE_KEY, LATEST)         # « retour arrière » avec la sauvegarde faite avant
    assert rep.ok and kept is not None and version_of(kept) == upgraded_version     # la base migrée est gardée à côté
    assert old_db.read_bytes() == old_bytes
    assert run_migrations(engine_for(old_db))["to"] == LATEST            # et l'ancienne version se remigre normalement


def test_every_release_tag_has_its_example_database():
    """Garde de publication : étiqueter `vX.Y.Z` sans `tools/snapshot_db.py vX.Y.Z …` casse la CI (sautée si le dépôt n'a pas ses étiquettes, ex. clone peu profond)."""
    r = subprocess.run(["git", "tag", "-l", "v*"], cwd=ROOT, capture_output=True, text=True)
    tags = r.stdout.split() if r.returncode == 0 else []
    for tag in tags:
        assert (FIXTURES / f"kaji-{tag}.db").exists(), f"{tag} : base d'exemple absente (backend/.venv/bin/python tools/snapshot_db.py {tag} backend/tests/fixtures/db/kaji-{tag}.db)"


def test_the_example_databases_hold_no_real_secret():
    """Les bases sont publiques : elles ne doivent contenir que des données fictives et rien d'autre que la clé de test."""
    for p in DBS:
        raw = p.read_bytes()
        assert b"jeton-fictif-0123456789" not in raw and FIXTURE_KEY.encode() not in raw       # chiffrés : ni le jeton ni la clé en clair
        c = sqlite3.connect(p)
        hosts = {r[0] for r in c.execute("SELECT host FROM connections")}
        c.close()
        assert hosts == {"10.0.0.5"}
