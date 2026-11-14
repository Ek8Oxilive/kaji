"""Sauvegarde, vérification et restauration de la base (jalon J1, ticket #429).

Les bases de ces tests sont de VRAIS fichiers SQLite construits par le vrai code (migrations, modèles, chiffrement des jetons et des webhooks) : on teste l'aller-retour
complet « sauvegarder, perdre, restaurer, relire », pas une simulation. Le garde-fou principal : restaurer avec la mauvaise clé est REFUSÉ, rien n'est modifié.
"""
import io
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app import admin_cli
from app.backup import BackupError, key_fingerprint, make_backup, restore, verify
from app.crypto import decrypt, encrypt
from app.migrations import MIGRATIONS, run_migrations
from app.models import AdminUser, AlertRule, AuditLog, Connection, ScheduledAction
from app.security import hash_password, verify_password

KEY = "test-secret-key-not-for-production"          # celle de conftest : c'est aussi la clé des commandes `admin_cli`
OTHER_KEY = "une-tout-autre-cle-de-32-caracteres-au-moins"
TOKEN = "jeton-proxmox-secret-0123456789"
HOOK = "https://hooks.example.org/services/SECRET-WEBHOOK-PATH"
PASSWORD = "mot-de-passe-de-test-12"
LATEST = max(m.version for m in MIGRATIONS)


def make_db(path: Path, key: str = KEY, suffix: str = "") -> Path:
    """Une base réelle : schéma migré, deux comptes (admin et opérateur), une connexion avec jeton, une règle avec webhook, une planification, de l'audit."""
    engine = create_engine(URL.create("sqlite", database=str(path)))
    run_migrations(engine)
    with Session(engine) as db:
        db.add_all([
            AdminUser(username="alice" + suffix, password_hash=hash_password(PASSWORD), role="admin"),
            AdminUser(username="bob" + suffix, password_hash=hash_password(PASSWORD), role="operator"),
        ])
        db.add(Connection(name="lab" + suffix, host="10.0.0.5", port=8006, user="kaji@pve", token_id="kaji",
                          token_secret_enc=encrypt(key, TOKEN), verify_ssl=False, tls_cert_pem="-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----"))
        db.flush()
        db.add(AlertRule(conn_id=1, name="cpu" + suffix, kind="cpu", threshold=90, minutes=5, enabled=True, webhook_enc=encrypt(key, HOOK), created_by="alice"))
        db.add(AlertRule(conn_id=1, name="sans-webhook", kind="mem", threshold=90, minutes=5, enabled=True, created_by="alice"))
        db.add(ScheduledAction(conn_id=1, node="n1", gtype="qemu", vmid=115, action="start", days="0,1", time="08:00", enabled=True, created_by="alice"))
        db.add(AuditLog(username="alice", action="x", target="y", status="started"))
        db.commit()
    engine.dispose()
    os.chmod(path, 0o600)
    return path


def fresh_dir(parent: Path, name: str) -> Path:
    d = parent / name
    d.mkdir()
    return d


def read_back(path: Path, key: str = KEY) -> dict:
    """Relit tout par le code de l'application (ORM + déchiffrement), comme après une restauration réelle."""
    engine = create_engine(URL.create("sqlite", database=str(path)))
    run_migrations(engine)                                     # une base plus ancienne est migrée au démarrage : le restaurée doit l'accepter
    with Session(engine) as db:
        users = {u.username: (u.role, verify_password(PASSWORD, u.password_hash)) for u in db.scalars(select(AdminUser))}
        conn = db.scalars(select(Connection)).one()
        rules = {r.name: (decrypt(key, r.webhook_enc) if r.webhook_enc else None) for r in db.scalars(select(AlertRule))}
        sched = db.scalars(select(ScheduledAction)).one()
        out = {"users": users, "token": decrypt(key, conn.token_secret_enc), "pinned": bool(conn.tls_cert_pem), "rules": rules,
               "schedule": (sched.vmid, sched.action, sched.days, sched.time), "audit": len(db.scalars(select(AuditLog)).all())}
    engine.dispose()
    return out


# ------------------------------------------------------------------ sauvegarde

def test_backup_of_a_live_database_is_a_consistent_copy_with_only_committed_data(tmp_path):
    db_file = make_db(tmp_path / "kaji.db")
    writer = sqlite3.connect(db_file)
    writer.execute("BEGIN")
    writer.execute("INSERT INTO audit_log (ts, username, action, target, status) VALUES ('2026-01-01', 'non-validé', 'x', 'y', 'started')")      # écriture EN COURS, non validée
    dest = tmp_path / "copie.db"
    size = make_backup(db_file, dest)
    writer.rollback(); writer.close()
    assert size == dest.stat().st_size > 0 and dest.stat().st_mode & 0o777 == 0o600
    copy = sqlite3.connect(dest)
    assert copy.execute("SELECT count(*) FROM audit_log WHERE username='non-validé'").fetchone()[0] == 0
    assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    copy.close()
    assert read_back(dest)["token"] == TOKEN


def test_backup_refuses_to_overwrite_and_to_read_a_missing_database(tmp_path):
    db_file = make_db(tmp_path / "kaji.db")
    dest = tmp_path / "copie.db"
    make_backup(db_file, dest)
    before = dest.read_bytes()
    with pytest.raises(BackupError, match="existe déjà"):
        make_backup(db_file, dest)
    assert dest.read_bytes() == before
    with pytest.raises(BackupError, match="introuvable"):
        make_backup(tmp_path / "absente.db", tmp_path / "x.db")
    assert not list(tmp_path.glob("*.partiel"))


def test_backup_works_when_the_folder_name_has_uri_special_characters(tmp_path):
    folder = tmp_path / "données ? #1"
    folder.mkdir()
    db_file = make_db(folder / "kaji.db")
    make_backup(db_file, tmp_path / "ok.db")
    assert verify(folder / "kaji.db", KEY).ok


# ------------------------------------------------------------------ vérification

def test_verify_reads_every_secret_and_prints_numbers_never_values(tmp_path):
    rep = verify(make_db(tmp_path / "kaji.db"), KEY)
    assert rep.ok and rep.tokens == (1, 1) and rep.webhooks == (1, 1) and rep.schema == LATEST
    text = rep.render()
    assert "Comptes de Kaji : 2 (admin 1, operator 1, viewer 0)" in text
    assert "jetons déchiffrés : 1/1" in text and "certificats épinglés : 1" in text
    assert "webhooks déchiffrés : 1/1" in text and "Actions planifiées : 1 (1 active(s))" in text
    assert "Résultat : OK" in text and f"empreinte {key_fingerprint(KEY)}" in text
    for secret in (TOKEN, HOOK, PASSWORD, KEY, "SECRET-WEBHOOK-PATH", "alice", "kaji@pve", "10.0.0.5"):
        assert secret not in text, f"« {secret} » fuit dans le rapport"


def test_verify_with_the_wrong_key_fails_and_says_so(tmp_path):
    rep = verify(make_db(tmp_path / "kaji.db"), OTHER_KEY)
    assert not rep.ok and rep.tokens == (0, 1) and rep.webhooks == (0, 1)
    assert "illisible" in rep.render() and "Résultat : ÉCHEC" in rep.render()
    assert key_fingerprint(KEY) != key_fingerprint(OTHER_KEY)
    assert TOKEN not in rep.render() and OTHER_KEY not in rep.render()


def test_verify_survives_garbage_truncated_and_foreign_databases(tmp_path):
    garbage = tmp_path / "bruit.db"; garbage.write_bytes(os.urandom(4096))
    assert not verify(garbage, KEY).ok
    good = make_db(tmp_path / "kaji.db")
    truncated = tmp_path / "coupee.db"; truncated.write_bytes(good.read_bytes()[: len(good.read_bytes()) // 2])
    assert not verify(truncated, KEY).ok
    foreign = tmp_path / "autre.db"
    c = sqlite3.connect(foreign); c.execute("CREATE TABLE notes (t TEXT)"); c.commit(); c.close()
    rep = verify(foreign, KEY)
    assert not rep.ok and "Tables absentes" in rep.render()
    assert not verify(tmp_path / "absente.db", KEY).ok


def test_verify_reads_a_database_from_an_older_version_without_newer_tables_or_columns(tmp_path):
    old = tmp_path / "ancienne.db"
    c = sqlite3.connect(old)
    c.executescript("""
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES (1, 'base', '2026-11-06');
        CREATE TABLE admin_users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, created_at TEXT);
        INSERT INTO admin_users (username, password_hash) VALUES ('alice', 'x');
        CREATE TABLE connections (id INTEGER PRIMARY KEY, token_secret_enc TEXT);
    """)
    c.execute("INSERT INTO connections (token_secret_enc) VALUES (?)", (encrypt(KEY, TOKEN),))
    c.commit(); c.close()
    rep = verify(old, KEY)
    assert rep.ok and rep.schema == 1 and "Comptes de Kaji : 1 (admin 1" in rep.render() and "table absente" in rep.render()


def test_verify_flags_each_kind_of_unreadable_secret_on_its_own(tmp_path):
    only_hook = make_db(tmp_path / "a.db")                                       # jeton lisible, webhook chiffré avec une AUTRE clé
    c = sqlite3.connect(only_hook); c.execute("UPDATE alert_rules SET webhook_enc=?", (encrypt(OTHER_KEY, HOOK),)); c.commit(); c.close()
    rep = verify(only_hook, KEY)
    assert not rep.ok and rep.tokens == (1, 1) and rep.webhooks[0] < rep.webhooks[1] and "webhook" in rep.render()
    only_token = make_db(tmp_path / "b.db")                                      # webhook lisible, jeton chiffré avec une AUTRE clé
    c = sqlite3.connect(only_token); c.execute("UPDATE connections SET token_secret_enc=?", (encrypt(OTHER_KEY, TOKEN),)); c.commit(); c.close()
    rep = verify(only_token, KEY)
    assert not rep.ok and rep.tokens == (0, 1) and rep.webhooks == (1, 1) and "jeton" in rep.render()


def test_verify_detects_a_structurally_damaged_database_that_still_opens(tmp_path):
    damaged = make_db(tmp_path / "kaji.db")
    c = sqlite3.connect(damaged)
    c.execute("CREATE TABLE gros (a TEXT)"); c.execute("CREATE INDEX gros_a ON gros (a)")
    c.executemany("INSERT INTO gros VALUES (?)", [(str(i) * 20,) for i in range(500)]); c.commit()
    c.execute("PRAGMA writable_schema=1"); c.execute("DELETE FROM sqlite_master WHERE name='gros_a'"); c.commit(); c.close()      # pages d'index orphelines
    rep = verify(damaged, KEY)
    assert not rep.ok and "endommagée" in rep.render() and "Intégrité SQLite : ok" not in rep.render()


def test_verify_flags_a_database_without_any_administrator(tmp_path):
    db_file = make_db(tmp_path / "kaji.db")
    c = sqlite3.connect(db_file); c.execute("UPDATE admin_users SET role='viewer'"); c.commit(); c.close()
    rep = verify(db_file, KEY)
    assert not rep.ok and "Aucun compte administrateur" in rep.render()


# ------------------------------------------------------------------ restauration

def test_full_round_trip_backup_lose_restore_and_read_everything_back(tmp_path):
    original = make_db(fresh_dir(tmp_path, "prod") / "kaji.db")
    expected = read_back(original)
    backup = tmp_path / "sauvegarde.db"
    make_backup(original, backup)
    # La « catastrophe » : la base d'exploitation est remplacée par une autre, avec un journal périmé à côté.
    other = make_db(tmp_path / "autre.db", suffix="-autre")
    target = tmp_path / "neuf" / "kaji.db"
    target.parent.mkdir()
    target.write_bytes(other.read_bytes()); os.chmod(target, 0o644)
    (tmp_path / "neuf" / "kaji.db-journal").write_bytes(b"journal d'une autre base : corromprait la restauration")
    rep, kept = restore(backup.read_bytes(), target, KEY, LATEST)
    assert rep.ok and kept is not None and kept.name.startswith("kaji.db.avant-restauration-")
    assert target.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "neuf" / "kaji.db-journal").exists()                 # le journal de l'ancienne base est retiré
    assert read_back(target) == expected                                       # comptes, rôles, jeton, webhooks, planification, audit : tout est relu à l'identique
    assert "alice" in read_back(target)["users"] and read_back(target)["users"]["bob"] == ("operator", True)
    assert "alice-autre" in read_back(kept)["users"]                           # l'ancienne base est intacte à côté
    assert not list((tmp_path / "neuf").glob("*.restauration-*"))              # aucun fichier temporaire


def test_restore_into_a_fresh_install_without_existing_database(tmp_path):
    backup = tmp_path / "s.db"; make_backup(make_db(tmp_path / "a.db"), backup)
    target = tmp_path / "data" / "kaji.db"
    rep, kept = restore(backup.read_bytes(), target, KEY, LATEST)
    assert rep.ok and kept is None and read_back(target)["token"] == TOKEN


def test_restore_with_the_wrong_key_is_refused_and_changes_nothing(tmp_path):
    backup = tmp_path / "s.db"; make_backup(make_db(tmp_path / "a.db"), backup)
    target = make_db(tmp_path / "b.db", suffix="-cible")
    before = target.read_bytes()
    with pytest.raises(BackupError) as e:
        restore(backup.read_bytes(), target, OTHER_KEY, LATEST)
    assert "illisible" in str(e.value) and TOKEN not in str(e.value)
    assert target.read_bytes() == before                                       # la base en place n'a pas bougé
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.db", "b.db", "s.db"]      # ni sauvegarde « avant restauration », ni temporaire


def test_restore_refuses_files_that_are_not_a_healthy_kaji_database(tmp_path):
    target = make_db(tmp_path / "b.db")
    before = target.read_bytes()
    with pytest.raises(BackupError, match="pas une base SQLite") as e:
        restore(b"ceci n'est pas une base", target, KEY, LATEST)
    assert "Résultat" not in str(e.value)                                       # refusé dès l'en-tête, avant toute lecture
    good = make_db(tmp_path / "g.db").read_bytes()
    with pytest.raises(BackupError):
        restore(good[: len(good) // 2], target, KEY, LATEST)                    # tronquée
    foreign = tmp_path / "autre.db"
    c = sqlite3.connect(foreign); c.execute("CREATE TABLE notes (t TEXT)"); c.commit(); c.close()
    with pytest.raises(BackupError, match="Tables absentes"):
        restore(foreign.read_bytes(), target, KEY, LATEST)
    assert target.read_bytes() == before and sorted(p.name for p in tmp_path.iterdir()) == ["autre.db", "b.db", "g.db"]


def test_restore_refuses_a_backup_newer_than_this_code(tmp_path):
    backup = make_db(tmp_path / "s.db")
    c = sqlite3.connect(backup); c.execute("INSERT INTO schema_migrations VALUES (?, 'futur', '2099-01-01')", (LATEST + 5,)); c.commit(); c.close()
    target = make_db(tmp_path / "b.db"); before = target.read_bytes()
    with pytest.raises(BackupError, match="mets Kaji à jour"):
        restore(backup.read_bytes(), target, KEY, LATEST)
    assert target.read_bytes() == before


def test_restore_puts_the_old_database_back_if_the_final_replacement_fails(tmp_path, monkeypatch):
    backup = tmp_path / "s.db"; make_backup(make_db(tmp_path / "a.db"), backup)
    target = make_db(tmp_path / "b.db", suffix="-cible"); before = target.read_bytes()
    import app.backup as backup_module
    real_replace = os.replace
    calls = []

    def flaky(src, dst):
        calls.append((Path(src).name, Path(dst).name))
        if Path(dst).name == "b.db" and ".restauration-" in Path(src).name:      # le remplacement FINAL échoue
            raise OSError("disque plein")
        return real_replace(src, dst)

    monkeypatch.setattr(backup_module.os, "replace", flaky)
    with pytest.raises(OSError, match="disque plein"):
        restore(backup.read_bytes(), target, KEY, LATEST)
    assert target.read_bytes() == before                                       # l'ancienne base est revenue à sa place
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.db", "b.db", "s.db"]


# ------------------------------------------------------------------ commandes

@pytest.fixture
def cli(tmp_path, monkeypatch):
    path = make_db(fresh_dir(tmp_path, "data") / "kaji.db")
    monkeypatch.setattr(admin_cli, "_db_file", lambda: path)
    return path


def test_cli_backup_to_a_file_then_verify_reports_ok(cli, tmp_path, capsys):
    out = tmp_path / "copie.db"
    assert admin_cli.main(["backup", "--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert f"Empreinte de la clé : {key_fingerprint(KEY)}" in err and KEY not in err and out.exists()
    assert admin_cli.main(["verify", "--file", str(out)]) == 0 and "Résultat : OK" in capsys.readouterr().out
    assert admin_cli.main(["backup", "--out", str(out)]) == 1                   # n'écrase jamais
    assert admin_cli.main(["backup"]) == 2


def test_cli_backup_stdout_streams_only_the_database_bytes(cli, tmp_path, capfdbinary):
    assert admin_cli.main(["backup", "--stdout"]) == 0
    cap = capfdbinary.readouterr()
    assert cap.out.startswith(b"SQLite format 3\x00") and b"Empreinte" in cap.err and b"Sauvegarde de la base" in cap.err
    page_size = int.from_bytes(cap.out[16:18], "big") or 65536
    assert len(cap.out) % page_size == 0 and b"Sauvegarde de la base" not in cap.out and b"Empreinte" not in cap.out      # le flux est EXACTEMENT la base
    copy = tmp_path / "flux.db"; copy.write_bytes(cap.out)
    assert verify(copy, KEY).ok


def test_cli_verify_fails_with_a_nonzero_code_when_the_key_does_not_match(cli, monkeypatch, capsys):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "kaji_secret_key", OTHER_KEY)
    assert admin_cli.main(["verify"]) == 1
    out = capsys.readouterr().out
    assert "Résultat : ÉCHEC" in out and TOKEN not in out and OTHER_KEY not in out


def test_cli_restore_needs_yes_and_restores_from_stdin(cli, tmp_path, monkeypatch, capsys):
    other = tmp_path / "autre.db"; make_db(other, suffix="-b")
    backup_bytes = other.read_bytes()
    assert admin_cli.main(["restore", str(other)]) == 2                         # sans --yes : usage, rien n'est fait
    assert "alice-b" not in read_back_names(cli)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(backup_bytes)})())
    assert admin_cli.main(["restore", "-", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Base restaurée" in out and "Résultat : OK" in out and PASSWORD not in out
    assert "alice-b" in read_back_names(cli)


def read_back_names(path: Path) -> set[str]:
    c = sqlite3.connect(path); names = {r[0] for r in c.execute("SELECT username FROM admin_users")}; c.close()
    return names


def test_cli_restore_with_a_wrong_key_fails_with_code_1_and_keeps_the_database(cli, tmp_path, monkeypatch, capsys):
    from app.config import get_settings
    foreign = tmp_path / "etrangere.db"; make_db(foreign, key=OTHER_KEY, suffix="-x")
    before = cli.read_bytes()
    assert admin_cli.main(["restore", str(foreign), "--yes"]) == 1
    out = capsys.readouterr().out
    assert "refusée" in out and "illisible" in out and OTHER_KEY not in out and get_settings().kaji_secret_key not in out
    assert cli.read_bytes() == before


def test_reports_are_json_free_of_secrets_when_serialised(tmp_path):
    rep = verify(make_db(tmp_path / "kaji.db"), KEY)
    dumped = json.dumps({"lines": rep.lines, "problems": rep.problems})
    assert TOKEN not in dumped and HOOK not in dumped
