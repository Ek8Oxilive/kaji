"""`KAJI_SECRET_KEY` : une valeur d'exemple est refusée au démarrage, une clé courte est signalée sans bloquer (un déploiement existant ne doit pas tomber)."""
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import MIN_SECRET_KEY_LENGTH, check_secret_key


@pytest.mark.parametrize("key", ["", " ", "changeme", "CHANGEME", " changeme ", "change-me", "secret", "password"])
def test_example_and_empty_keys_are_refused(key):
    with pytest.raises(RuntimeError, match="KAJI_SECRET_KEY"):
        check_secret_key(key)


def test_a_short_key_is_a_warning_not_an_error():
    msg = check_secret_key("a" * (MIN_SECRET_KEY_LENGTH - 1))
    assert msg and "courte" in msg and str(MIN_SECRET_KEY_LENGTH - 1) in msg
    assert "a" * 5 not in msg                                                  # la clé n'est jamais recopiée dans le message


def test_a_long_key_is_accepted():
    assert check_secret_key("x" * MIN_SECRET_KEY_LENGTH) is None
    assert check_secret_key("test-secret-key-not-for-production") is None


def test_the_application_refuses_to_start_with_an_example_key(monkeypatch):
    from app.config import get_settings
    from app.main import app
    get_settings.cache_clear()
    monkeypatch.setenv("KAJI_SECRET_KEY", "changeme")
    try:
        with pytest.raises(RuntimeError, match="KAJI_SECRET_KEY"):
            with TestClient(app):
                pass
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_the_application_warns_about_a_short_key_and_still_starts(monkeypatch, caplog):
    from app.config import get_settings
    from app.main import app
    get_settings.cache_clear()
    monkeypatch.setenv("KAJI_SECRET_KEY", "short-key-for-test-only")
    try:
        with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
            with TestClient(app) as c:
                assert c.get("/api/health").status_code == 200
        assert any("courte" in r.getMessage() for r in caplog.records)
        assert "short-key-for-test-only" not in caplog.text
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
