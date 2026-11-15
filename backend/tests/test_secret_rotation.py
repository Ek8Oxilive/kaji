"""Rotation de `KAJI_SECRET_KEY` (lot #461) : jetons des connexions et webhooks d'alerte ré-chiffrés, tout ou rien, rejouable, sans rien afficher de secret."""
import sqlite3

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app import admin_cli, crypto
from app.config import get_settings
from app.models import AlertRule, AuditLog, Connection, UserTotp
from app.secretrotate import SecretRotationError, rotate_secret_key
from app.security import create_session_token, decode_session
from tests.test_backup_restore import HOOK, TOKEN, make_db

OLD = "ancienne-cle-secrete-de-kaji-0123456789abcdefghij"
NEW = "nouvelle-cle-secrete-de-kaji-0123456789abcdefghij"
OTHER = "troisieme-cle-sans-rapport-0123456789abcdefghijk"


def session(path) -> Session:
    return Session(create_engine(URL.create("sqlite", database=str(path))))


def old_db(tmp_path):
    return make_db(tmp_path / "kaji.db", key=OLD)


def blobs(path):
    c = sqlite3.connect(path)
    out = (c.execute("SELECT token_secret_enc FROM connections ORDER BY id").fetchall(), c.execute("SELECT webhook_enc FROM alert_rules ORDER BY id").fetchall())
    c.close()
    return out


def test_every_connection_token_and_webhook_is_reencrypted_and_nothing_else_changes(tmp_path):
    p = old_db(tmp_path)
    before = blobs(p)
    c = sqlite3.connect(p); other_before = c.execute("SELECT name, host, user, token_id FROM connections").fetchall() + c.execute("SELECT name, kind, threshold FROM alert_rules").fetchall(); c.close()
    with session(p) as db:
        res = rotate_secret_key(db, NEW, OLD)
    assert (res.connections, res.webhooks, res.already_current) == (1, 1, 0)
    assert blobs(p) != before
    with session(p) as db:
        conn = db.scalars(select(Connection)).one()
        assert crypto.decrypt(NEW, conn.token_secret_enc) == TOKEN                                  # lisible avec la NOUVELLE clé
        with pytest.raises(ValueError):
            crypto.decrypt(OLD, conn.token_secret_enc)                                              # plus avec l'ancienne
        hooks = {r.name: r.webhook_enc for r in db.scalars(select(AlertRule))}
        assert crypto.decrypt(NEW, hooks["cpu"]) == HOOK and hooks["sans-webhook"] is None            # une règle sans webhook reste sans webhook
    c = sqlite3.connect(p); other_after = c.execute("SELECT name, host, user, token_id FROM connections").fetchall() + c.execute("SELECT name, kind, threshold FROM alert_rules").fetchall(); c.close()
    assert other_after == other_before


def test_a_replayed_rotation_changes_nothing(tmp_path):
    p = old_db(tmp_path)
    with session(p) as db:
        rotate_secret_key(db, NEW, OLD)
    after_first = blobs(p)
    with session(p) as db:
        res = rotate_secret_key(db, NEW, OLD)
    assert (res.connections, res.webhooks, res.already_current) == (0, 0, 2) and blobs(p) == after_first


def test_missing_or_identical_keys_are_refused_and_nothing_changes(tmp_path):
    p = old_db(tmp_path); before = blobs(p)
    with session(p) as db:
        for new, old, needle in ((NEW, "", "DEUX clés"), ("", OLD, "DEUX clés"), (NEW, NEW, "identique")):
            with pytest.raises(SecretRotationError, match=needle):
                rotate_secret_key(db, new, old)
    assert blobs(p) == before


def test_one_secret_that_neither_key_reads_aborts_everything(tmp_path):
    p = old_db(tmp_path)
    with session(p) as db:
        db.scalars(select(AlertRule).where(AlertRule.name == "cpu")).one().webhook_enc = crypto.encrypt(OTHER, HOOK); db.commit()
    before = blobs(p)
    with session(p) as db:
        with pytest.raises(SecretRotationError, match=r"1 secret\(s\) sur 2") as e:
            rotate_secret_key(db, NEW, OLD)
        assert OTHER not in str(e.value) and TOKEN not in str(e.value)
    assert blobs(p) == before                                                                        # la connexion lisible n'a pas été touchée non plus


def test_a_failure_in_the_middle_rolls_everything_back_even_for_a_later_commit(tmp_path, monkeypatch):
    p = old_db(tmp_path); before = blobs(p)
    import app.secretrotate as module
    real, calls = module.encrypt, []

    def flaky(key, text):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("panne")
        return real(key, text)
    monkeypatch.setattr(module, "encrypt", flaky)
    db = session(p)
    with pytest.raises(RuntimeError):
        rotate_secret_key(db, NEW, OLD)
    db.commit(); db.close()                                                                          # un commit ultérieur ne doit rien valider
    assert blobs(p) == before


def test_a_rotation_that_would_produce_an_unreadable_secret_is_aborted(tmp_path, monkeypatch):
    p = old_db(tmp_path); before = blobs(p)
    import app.secretrotate as module
    monkeypatch.setattr(module, "encrypt", lambda key, text: real_other(text))
    real_other = lambda text: crypto.encrypt(OTHER, text)                                            # noqa: E731
    db = session(p)
    with pytest.raises(SecretRotationError, match="pas lisible avec la nouvelle clé"):
        rotate_secret_key(db, NEW, OLD)
    db.commit(); db.close()
    assert blobs(p) == before


def test_sessions_signed_with_the_old_key_are_invalid_with_the_new_one():
    """Documenté : la rotation fait tomber toutes les sessions (reconnexion)."""
    token = create_session_token(OLD, 1, 12, "jti-1")
    assert decode_session(OLD, token) == (1, "jti-1") and decode_session(NEW, token) is None


@pytest.fixture
def cli(tmp_path, monkeypatch):
    path = old_db(tmp_path)
    monkeypatch.setattr("app.db.get_engine", lambda: create_engine(URL.create("sqlite", database=str(path))))
    s = get_settings()
    monkeypatch.setattr(s, "kaji_secret_key", NEW)
    monkeypatch.setattr(s, "kaji_secret_key_previous", OLD)
    return path


def test_cli_needs_yes_then_rotates_audits_and_prints_only_numbers(cli, capsys):
    assert admin_cli.main(["rotate-secret-key"]) == 2
    assert admin_cli.main(["rotate-secret-key", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "1 jeton(s) de connexion, 1 webhook(s), 0 secret(s) TOTP et 0 secret(s) SSO / annuaire" in out and "KAJI_SECRET_KEY_PREVIOUS" in out and "sessions" in out
    for secret in (TOKEN, HOOK, OLD, NEW):
        assert secret not in out
    with session(cli) as db:
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "secret-key-rotated")).one()
        assert entry.username == "cli-local" and not any(x in (entry.detail or "") for x in (TOKEN, HOOK, OLD, NEW))
        assert crypto.decrypt(NEW, db.scalars(select(Connection)).one().token_secret_enc) == TOKEN


def test_cli_refuses_a_weak_new_key_and_a_missing_previous_one_without_touching_anything(cli, monkeypatch, capsys):
    before = blobs(cli)
    monkeypatch.setattr(get_settings(), "kaji_secret_key", "changeme")
    assert admin_cli.main(["rotate-secret-key", "--yes"]) == 1 and "valeur d'exemple" in capsys.readouterr().out
    monkeypatch.setattr(get_settings(), "kaji_secret_key", NEW)
    monkeypatch.setattr(get_settings(), "kaji_secret_key_previous", "")
    assert admin_cli.main(["rotate-secret-key", "--yes"]) == 1 and "DEUX clés" in capsys.readouterr().out
    assert blobs(cli) == before


def _with_totp(path, key, secret="JBSWY3DPEHPK3PXP"):
    with session(path) as db:
        db.add(UserTotp(user_id=1, secret_enc=crypto.encrypt(key, secret), confirmed=True, last_step=7))
        db.add(UserTotp(user_id=2, secret_enc=crypto.encrypt(key, "KRSXG5CTMVRXEZLU"), confirmed=False, last_step=0))        # un enrôlement en attente : réchiffré aussi
        db.commit()
    return secret


def test_totp_secrets_are_reencrypted_confirmed_or_pending_and_the_rest_of_the_row_is_untouched(tmp_path):
    p = old_db(tmp_path)
    secret = _with_totp(p, OLD)
    with session(p) as db:
        res = rotate_secret_key(db, NEW, OLD)
    assert (res.connections, res.webhooks, res.totp, res.already_current) == (1, 1, 2, 0)
    with session(p) as db:
        rows = {r.user_id: r for r in db.scalars(select(UserTotp))}
        assert crypto.decrypt(NEW, rows[1].secret_enc) == secret and crypto.decrypt(NEW, rows[2].secret_enc) == "KRSXG5CTMVRXEZLU"
        with pytest.raises(ValueError):
            crypto.decrypt(OLD, rows[1].secret_enc)
        assert (rows[1].confirmed, rows[1].last_step, rows[2].confirmed, rows[2].last_step) == (True, 7, False, 0)           # état et anti-rejeu conservés


def test_a_replayed_rotation_leaves_totp_secrets_alone_and_counts_them_as_current(tmp_path):
    p = old_db(tmp_path)
    _with_totp(p, OLD)
    with session(p) as db:
        rotate_secret_key(db, NEW, OLD)
    c = sqlite3.connect(p); first = c.execute("SELECT secret_enc FROM user_totp ORDER BY user_id").fetchall(); c.close()
    with session(p) as db:
        res = rotate_secret_key(db, NEW, OLD)
    c = sqlite3.connect(p); second = c.execute("SELECT secret_enc FROM user_totp ORDER BY user_id").fetchall(); c.close()
    assert (res.connections, res.webhooks, res.totp, res.already_current) == (0, 0, 0, 4) and first == second


def test_one_totp_secret_that_neither_key_reads_aborts_everything_and_the_totp_login_still_works_with_the_new_key(tmp_path):
    p = old_db(tmp_path)
    _with_totp(p, OLD)
    with session(p) as db:
        db.get(UserTotp, 2).secret_enc = crypto.encrypt(OTHER, "KRSXG5CTMVRXEZLU")
        db.commit()
    before = blobs(p)
    c = sqlite3.connect(p); totp_before = c.execute("SELECT secret_enc FROM user_totp ORDER BY user_id").fetchall(); c.close()
    with session(p) as db:
        with pytest.raises(SecretRotationError, match="aucune des deux clés"):
            rotate_secret_key(db, NEW, OLD)
    c = sqlite3.connect(p); totp_after = c.execute("SELECT secret_enc FROM user_totp ORDER BY user_id").fetchall(); c.close()
    assert blobs(p) == before and totp_after == totp_before                                                                  # rien n'a bougé, même pas les connexions


def test_cli_counts_and_audits_the_totp_secrets_without_printing_any(cli, capsys):
    secret = _with_totp(cli, OLD)
    assert admin_cli.main(["rotate-secret-key", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "1 jeton(s) de connexion, 1 webhook(s), 2 secret(s) TOTP et 0 secret(s) SSO / annuaire" in out and secret not in out and "KRSXG5CTMVRXEZLU" not in out
    with session(cli) as db:
        entry = db.scalars(select(AuditLog).where(AuditLog.action == "secret-key-rotated")).one()
        assert "2 secret(s) TOTP" in entry.detail and "user_totp" in entry.target and "auth_settings" in entry.target and secret not in entry.detail
        assert crypto.decrypt(NEW, db.get(UserTotp, 1).secret_enc) == secret


def test_verify_reads_the_totp_secrets_and_flags_the_unreadable_ones_without_printing_any(tmp_path):
    from pathlib import Path

    from app import backup
    p = old_db(tmp_path)
    secret = _with_totp(p, OLD)
    good = backup.verify(Path(p), OLD)
    text = "\n".join(good.lines)
    assert "Secrets TOTP de connexion : 2 ; déchiffrés : 2/2" in text and secret not in text and not any("TOTP" in x for x in good.problems)
    bad = backup.verify(Path(p), NEW)
    assert "Secrets TOTP de connexion : 2 ; déchiffrés : 0/2" in "\n".join(bad.lines) and any("TOTP illisible" in x for x in bad.problems)
