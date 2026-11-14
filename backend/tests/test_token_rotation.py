"""Rotation de la clé des jetons personnels et contrôle de ces jetons par `verify` / `restore` (lot #440)."""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app import admin_cli, tokenkey
from app.backup import BackupError, make_backup, restore, verify
from app.config import get_settings
from app.migrations import MIGRATIONS, run_migrations
from app.models import AuditLog, UserToken
from app.tokenrotate import RotationError, rotate_all
from tests.test_backup_restore import KEY as SECRET_KEY, make_db

OLD = "ancienne-cle-des-jetons-personnels-0123456789abc"
NEW = "nouvelle-cle-des-jetons-personnels-0123456789abc"
OTHER = "autre-cle-sans-rapport-des-jetons-0123456789abcd"
SECRETS = ["secret-un-00000001", "secret-deux-0000002", "secret-trois-000003"]
LATEST = max(m.version for m in MIGRATIONS)


def db_with_tokens(path: Path, key: str = OLD, secrets=SECRETS, expired: bool = False) -> Path:
    make_db(path)
    engine = create_engine(URL.create("sqlite", database=str(path)))
    with Session(engine) as db:
        for i, sec in enumerate(secrets, 1):
            db.add(UserToken(user_id=i, conn_id=1, pve_user=f"u{i}@pve", token_id="perso", secret_enc=tokenkey.encrypt(sec, [key]),
                             expires_at=datetime.now(timezone.utc) + timedelta(days=-1 if expired else 30), privsep=True, verified=True))
        db.commit()
    engine.dispose()
    return path


def session(path: Path) -> Session:
    return Session(create_engine(URL.create("sqlite", database=str(path))))


# ------------------------------------------------------------------ rotation

def test_rotation_rewrites_every_token_with_the_new_key_and_loses_none(tmp_path):
    p = db_with_tokens(tmp_path / "kaji.db")
    with session(p) as db:
        before = [r.secret_enc for r in db.scalars(select(UserToken).order_by(UserToken.id))]
        res = rotate_all(db, [NEW, OLD])
    assert (res.total, res.rotated, res.dropped) == (3, 3, 0)
    with session(p) as db:
        rows = list(db.scalars(select(UserToken).order_by(UserToken.id)))
        assert [r.secret_enc for r in rows] != before
        assert [tokenkey.decrypt(r.secret_enc, [NEW]) for r in rows] == SECRETS            # la NOUVELLE clé seule suffit
        assert not any(tokenkey.readable(r.secret_enc, [OLD]) for r in rows)                  # l'ancienne ne lit plus rien
        assert [(r.pve_user, r.expires_at is not None, r.verified) for r in rows] == [("u1@pve", True, True), ("u2@pve", True, True), ("u3@pve", True, True)]


def test_rotation_is_replayable_with_the_old_key_still_set(tmp_path):
    p = db_with_tokens(tmp_path / "kaji.db")
    with session(p) as db:
        rotate_all(db, [NEW, OLD])
        assert rotate_all(db, [NEW, OLD]).rotated == 3                                           # déjà fait : sans effet néfaste
        assert [tokenkey.decrypt(r.secret_enc, [NEW]) for r in db.scalars(select(UserToken).order_by(UserToken.id))] == SECRETS


def test_rotation_needs_both_keys_and_changes_nothing_otherwise(tmp_path):
    p = db_with_tokens(tmp_path / "kaji.db")
    raw = p.read_bytes()
    with session(p) as db:
        with pytest.raises(RotationError, match="DEUX clés"):
            rotate_all(db, [NEW])
        with pytest.raises(RotationError, match="DEUX clés"):
            rotate_all(db, [])
    assert p.read_bytes() == raw


def test_one_unreadable_token_aborts_everything_unless_dropping_is_asked(tmp_path):
    p = db_with_tokens(tmp_path / "kaji.db")
    with session(p) as db:
        db.scalars(select(UserToken).where(UserToken.user_id == 2)).one().secret_enc = tokenkey.encrypt("x-secret-00000000", [OTHER])
        db.commit()
    snapshot = sqlite3.connect(p).execute("SELECT id, secret_enc FROM user_tokens ORDER BY id").fetchall()
    with session(p) as db:
        with pytest.raises(RotationError, match=r"1 jeton\(s\) personnel\(s\) sur 3") as e:
            rotate_all(db, [NEW, OLD])
        assert "x-secret-00000000" not in str(e.value) and OTHER not in str(e.value)
    assert sqlite3.connect(p).execute("SELECT id, secret_enc FROM user_tokens ORDER BY id").fetchall() == snapshot       # rien n'a bougé
    with session(p) as db:
        res = rotate_all(db, [NEW, OLD], drop_unreadable=True)
    assert (res.total, res.rotated, res.dropped) == (3, 2, 1)
    with session(p) as db:
        assert sorted(r.user_id for r in db.scalars(select(UserToken))) == [1, 3]


def test_a_failure_in_the_middle_rolls_everything_back(tmp_path, monkeypatch):
    p = db_with_tokens(tmp_path / "kaji.db")
    snapshot = sqlite3.connect(p).execute("SELECT id, secret_enc FROM user_tokens ORDER BY id").fetchall()
    real, calls = tokenkey.rotate, []

    def flaky(blob, keys):
        calls.append(1)
        if len(calls) == 3:
            raise tokenkey.TokenKeyError("panne")
        return real(blob, keys)
    monkeypatch.setattr(tokenkey, "rotate", flaky)
    db = session(p)
    with pytest.raises(tokenkey.TokenKeyError):
        rotate_all(db, [NEW, OLD])
    db.commit(); db.close()                                                            # même un commit ultérieur de la session ne doit rien valider
    assert sqlite3.connect(p).execute("SELECT id, secret_enc FROM user_tokens ORDER BY id").fetchall() == snapshot          # ni 1 ni 2 ne sont restés ré-chiffrés


def test_a_rotation_that_produces_unreadable_output_is_aborted_and_the_session_stays_clean(tmp_path, monkeypatch):
    """Défense en profondeur : même si `rotate` rendait un chiffré illisible avec la nouvelle clé, rien n'est validé, ni maintenant ni par un `commit` ultérieur de la même session."""
    p = db_with_tokens(tmp_path / "kaji.db")
    snapshot = sqlite3.connect(p).execute("SELECT id, secret_enc FROM user_tokens ORDER BY id").fetchall()
    monkeypatch.setattr(tokenkey, "rotate", lambda blob, keys: tokenkey.encrypt("n-importe-quoi-00000", [OTHER]))
    db = session(p)
    with pytest.raises(RotationError, match="pas lisible avec la nouvelle clé"):
        rotate_all(db, [NEW, OLD])
    db.commit()                                                                     # un commit qui suit ne doit rien « valider » des changements annulés
    db.close()
    assert sqlite3.connect(p).execute("SELECT id, secret_enc FROM user_tokens ORDER BY id").fetchall() == snapshot


# ------------------------------------------------------------------ commande

@pytest.fixture
def cli(tmp_path, monkeypatch):
    path = db_with_tokens(tmp_path / "kaji.db")
    monkeypatch.setattr(admin_cli, "_db_file", lambda: path)
    monkeypatch.setattr("app.db.get_engine", lambda: create_engine(URL.create("sqlite", database=str(path))))
    s = get_settings()
    monkeypatch.setattr(s, "kaji_token_key", NEW)
    monkeypatch.setattr(s, "kaji_token_key_file", "")
    monkeypatch.setattr(s, "kaji_token_key_previous", OLD)
    return path


def test_cli_rotation_needs_yes_then_rotates_audits_and_prints_only_numbers(cli, capsys):
    assert admin_cli.main(["rotate-token-key"]) == 2
    assert admin_cli.main(["rotate-token-key", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "3 jeton(s) ré-chiffré(s) sur 3" in out and "KAJI_TOKEN_KEY_PREVIOUS" in out
    for secret in SECRETS + [OLD, NEW]:
        assert secret not in out
    with session(cli) as db:
        assert all(tokenkey.readable(r.secret_enc, [NEW]) for r in db.scalars(select(UserToken)))
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "token-key-rotated")).one()
        assert entry.username == "cli-local" and "3 jeton" in entry.detail and not any(s in (entry.detail or "") for s in SECRETS)


def test_cli_rotation_refuses_without_the_previous_key_or_with_a_bad_key(cli, monkeypatch, capsys):
    monkeypatch.setattr(get_settings(), "kaji_token_key_previous", "")
    assert admin_cli.main(["rotate-token-key", "--yes"]) == 1 and "DEUX clés" in capsys.readouterr().out
    monkeypatch.setattr(get_settings(), "kaji_token_key", "trop-courte")
    assert admin_cli.main(["rotate-token-key", "--yes"]) == 1 and "trop courte" in capsys.readouterr().out
    with session(cli) as db:
        assert all(tokenkey.readable(r.secret_enc, [OLD]) for r in db.scalars(select(UserToken)))       # intacts


# ------------------------------------------------------------------ verify et restore relisent aussi les jetons personnels

def test_verify_counts_personal_tokens_and_flags_a_wrong_or_missing_key(tmp_path):
    p = db_with_tokens(tmp_path / "kaji.db")
    rep = verify(p, SECRET_KEY, [OLD])
    assert rep.ok and rep.user_tokens == (3, 3) and "Jetons Proxmox personnels : 3 ; déchiffrés : 3/3" in rep.render()
    assert not any(s in rep.render() for s in SECRETS + [OLD])
    bad = verify(p, SECRET_KEY, [OTHER])
    assert not bad.ok and bad.user_tokens == (0, 3) and "rotation oubliée" in bad.render()
    missing = verify(p, SECRET_KEY, [])
    assert not missing.ok and "n'est pas configurée" in missing.render() and "non vérifiés" in missing.render() and missing.user_tokens == (0, 3)
    assert verify(p, SECRET_KEY).ok is False                                                         # défaut : pas de clé fournie = pas de preuve
    assert verify(p, SECRET_KEY, [NEW, OLD]).ok                                                      # fenêtre de rotation : la précédente lit encore


def test_verify_without_personal_tokens_needs_no_separate_key(tmp_path):
    p = make_db(tmp_path / "kaji.db")
    rep = verify(p, SECRET_KEY, [])
    assert rep.ok and "Jetons Proxmox personnels" not in rep.render() or "personnels : 0" in rep.render()
    with session(p) as db:
        db.add(UserToken(user_id=1, conn_id=1, pve_user="a@pve", token_id="t", secret_enc="x", expires_at=datetime.now(timezone.utc), privsep=True)); db.commit(); db.delete(db.scalars(select(UserToken)).one()); db.commit()
    assert verify(p, SECRET_KEY, []).ok                                                              # table vide : rien à relire


def test_verify_reports_expired_tokens_without_failing(tmp_path):
    p = db_with_tokens(tmp_path / "kaji.db", expired=True)
    rep = verify(p, SECRET_KEY, [OLD])
    assert rep.ok and "échéance dépassée : 3" in rep.render()


def test_restore_refuses_a_backup_whose_personal_tokens_the_current_separate_key_cannot_read(tmp_path):
    backup = tmp_path / "s.db"; make_backup(db_with_tokens(tmp_path / "a.db"), backup)
    target = make_db(tmp_path / "b.db", suffix="-cible"); before = target.read_bytes()
    with pytest.raises(BackupError, match="illisible"):
        restore(backup.read_bytes(), target, SECRET_KEY, LATEST, [NEW])                  # la clé a été changée sans rotation
    with pytest.raises(BackupError, match="KAJI_TOKEN_KEY"):
        restore(backup.read_bytes(), target, SECRET_KEY, LATEST, [])
    assert target.read_bytes() == before
    rep, kept = restore(backup.read_bytes(), target, SECRET_KEY, LATEST, [OLD])
    assert rep.ok and rep.user_tokens == (3, 3)


def test_a_backup_made_before_rotation_still_restores_with_the_previous_key_in_the_window(tmp_path):
    backup = tmp_path / "s.db"; make_backup(db_with_tokens(tmp_path / "a.db"), backup)
    target = tmp_path / "data" / "kaji.db"
    rep, _ = restore(backup.read_bytes(), target, SECRET_KEY, LATEST, [NEW, OLD])
    assert rep.ok
    with session(target) as db:
        rotate_all(db, [NEW, OLD])                                                      # puis on met la base restaurée à jour
    assert verify(target, SECRET_KEY, [NEW]).ok


def test_cli_rotation_can_drop_unreadable_tokens_only_when_asked(cli, capsys):
    with session(cli) as db:
        db.scalars(select(UserToken).where(UserToken.user_id == 2)).one().secret_enc = tokenkey.encrypt("x-secret-00000000", [OTHER]); db.commit()
    assert admin_cli.main(["rotate-token-key", "--yes"]) == 1 and "--drop-unreadable" in capsys.readouterr().out
    with session(cli) as db:
        assert len(list(db.scalars(select(UserToken)))) == 3
    assert admin_cli.main(["rotate-token-key", "--yes", "--drop-unreadable"]) == 0 and "1 supprimé(s)" in capsys.readouterr().out
    with session(cli) as db:
        assert sorted(r.user_id for r in db.scalars(select(UserToken))) == [1, 3]


def test_cli_verify_uses_the_separate_key_on_the_base_and_on_a_copy_from_stdin(cli, monkeypatch, capsys):
    import io
    import sys
    monkeypatch.setattr(get_settings(), "kaji_token_key_previous", "")
    monkeypatch.setattr(get_settings(), "kaji_token_key", OLD)
    assert admin_cli.main(["verify", "--file", str(cli)]) == 0 and "déchiffrés : 3/3" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(cli.read_bytes())})())
    assert admin_cli.main(["verify", "--file", "-"]) == 0 and "déchiffrés : 3/3" in capsys.readouterr().out
    monkeypatch.setattr(get_settings(), "kaji_token_key", NEW)                         # mauvaise clé : échec, code 1
    assert admin_cli.main(["verify", "--file", str(cli)]) == 1 and "rotation oubliée" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(cli.read_bytes())})())
    assert admin_cli.main(["verify", "--file", "-"]) == 1
    monkeypatch.setattr(get_settings(), "kaji_token_key", "trop-courte")               # clé inutilisable : refus net, pas de traceback
    assert admin_cli.main(["verify", "--file", str(cli)]) == 1 and "trop courte" in capsys.readouterr().out


def test_cli_restore_checks_personal_tokens_with_the_separate_key(cli, tmp_path, monkeypatch, capsys):
    backup = tmp_path / "s.db"; make_backup(cli, backup)
    monkeypatch.setattr(get_settings(), "kaji_token_key_previous", "")
    monkeypatch.setattr(get_settings(), "kaji_token_key", NEW)                         # clé changée sans rotation
    before = cli.read_bytes()
    assert admin_cli.main(["restore", str(backup), "--yes"]) == 1 and "illisible" in capsys.readouterr().out and cli.read_bytes() == before
    monkeypatch.setattr(get_settings(), "kaji_token_key", OLD)
    assert admin_cli.main(["restore", str(backup), "--yes"]) == 0
