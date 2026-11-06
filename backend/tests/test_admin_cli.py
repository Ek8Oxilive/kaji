import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_cli import AdminError, main, reset_password
from app.db import get_engine
from app.models import AdminUser, UserSession

PWD = "un-mot-de-passe-solide"
NEW = "un-nouveau-mot-de-passe-12"


def db():
    return Session(get_engine())


def test_reset_changes_the_password_and_revokes_every_session(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    other = type(client)(client.app)
    other.post("/api/auth/login", json={"username": "admin", "password": PWD})
    with db() as s:
        assert reset_password(s, NEW) == "admin"
        assert s.scalars(select(UserSession)).all() == []
    assert client.get("/api/auth/me").status_code == 401 and other.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": PWD}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": NEW}).status_code == 200


def test_reset_is_audited_without_the_password(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    with db() as s:
        reset_password(s, NEW)
    client.post("/api/auth/login", json={"username": "admin", "password": NEW})
    log = client.get("/api/audit").text
    assert "password-reset" in log and "cli-local" in log and NEW not in log and PWD not in log


@pytest.mark.parametrize("pwd", ["", "court", "onze-chars-"])
def test_short_passwords_are_refused_and_nothing_changes(client, pwd):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    with db() as s, pytest.raises(AdminError):
        reset_password(s, pwd)
    assert client.get("/api/auth/me").status_code == 200                        # la session existe toujours
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "admin", "password": PWD}).status_code == 200


def test_reset_needs_an_existing_account_and_never_creates_one(client):
    with db() as s, pytest.raises(AdminError, match="Aucun compte"):
        reset_password(s, NEW)
    with db() as s:
        assert s.scalars(select(AdminUser)).all() == []                          # rien n'a été créé


def test_unknown_user_and_ambiguity(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    with db() as s:
        with pytest.raises(AdminError, match="inconnu"):
            reset_password(s, NEW, "quelquun")
        s.add(AdminUser(username="autre", password_hash="x"))
        s.commit()
        with pytest.raises(AdminError, match="Plusieurs comptes"):
            reset_password(s, NEW)
        assert reset_password(s, NEW, "autre") == "autre"


def test_cli_asks_twice_and_refuses_a_mismatch(client, monkeypatch, capsys):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    answers = iter([NEW, "autre-chose-12345"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert main(["reset-password"]) == 1
    assert "diffèrent" in capsys.readouterr().out
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "admin", "password": PWD}).status_code == 200


def test_cli_success_and_usage(client, monkeypatch, capsys):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    monkeypatch.setattr("getpass.getpass", lambda prompt="": NEW)
    assert main(["reset-password"]) == 0 and NEW not in capsys.readouterr().out      # le mot de passe n'est jamais affiché
    assert main([]) == 2 and main(["autre-commande"]) == 2
    assert client.post("/api/auth/login", json={"username": "admin", "password": NEW}).status_code == 200
