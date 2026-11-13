"""Jeton de première configuration (`KAJI_SETUP_TOKEN`) : sans lui, le premier qui atteint le port crée le compte admin."""
import pytest

from app.config import get_settings
from app.security import throttle

PWD = "un-mot-de-passe-solide"
TOKEN = "jeton-de-configuration-0123456789"


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setenv("KAJI_SETUP_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def setup(client, token=None, **kw):
    body = {"username": "admin", "password": PWD, **kw}
    if token is not None:
        body["setup_token"] = token
    return client.post("/api/auth/setup", json=body)


def test_without_a_configured_token_setup_works_as_before(client):
    assert client.get("/api/auth/status").json()["setup_token_required"] is False
    assert setup(client).status_code == 201


def test_status_says_a_token_is_required_only_before_setup(client, with_token):
    assert client.get("/api/auth/status").json() == {"setup_required": True, "authenticated": False, "setup_token_required": True}
    assert setup(client, TOKEN).status_code == 201
    assert client.get("/api/auth/status").json()["setup_token_required"] is False


@pytest.mark.parametrize("token", [None, "", "mauvais", TOKEN + " ", " " + TOKEN, TOKEN.upper(), TOKEN[:-1], TOKEN + "x"])
def test_a_missing_or_wrong_token_is_refused_and_creates_nothing(client, with_token, token):
    r = setup(client, token)
    assert r.status_code == 403 and TOKEN not in r.text and "kaji_session" not in r.headers.get("set-cookie", "")
    assert client.get("/api/auth/status").json()["setup_required"] is True


def test_the_right_token_creates_the_account_and_logs_in(client, with_token):
    r = setup(client, TOKEN)
    assert r.status_code == 201 and "kaji_session" in r.headers["set-cookie"] and TOKEN not in r.text
    assert client.get("/api/auth/me").json() == {"username": "admin", "role": "admin"}


def test_the_token_does_not_unlock_a_second_account(client, with_token):
    assert setup(client, TOKEN).status_code == 201
    assert setup(client, TOKEN, username="autre").status_code == 409


def test_a_non_string_token_is_a_validation_error_without_echo(client, with_token):
    r = client.post("/api/auth/setup", json={"username": "admin", "password": PWD, "setup_token": 12345})
    assert r.status_code == 422 and "12345" not in r.text


def test_guessing_is_throttled_and_blocks_even_the_right_token(client, with_token):
    throttle.reset()
    for _ in range(5):
        assert setup(client, "faux").status_code == 403
    assert setup(client, "faux").status_code == 429
    assert setup(client, TOKEN).status_code == 429
    throttle.reset()
    assert setup(client, TOKEN).status_code == 201


def test_the_token_never_appears_in_the_audit(client, with_token):
    setup(client, "faux")
    setup(client, TOKEN)
    assert TOKEN not in client.get("/api/audit").text
