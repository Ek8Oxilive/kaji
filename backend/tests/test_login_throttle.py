"""Limiteur de connexions PERSISTANT (lot #446) : un redémarrage ne remet plus le compteur à zéro."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.db import get_engine
from app.main import app
from app.migrations import run_migrations
from app.models import LoginFailure
from app.security import LoginThrottle, throttle

PWD = "un-mot-de-passe-solide"


@pytest.fixture
def file_db(tmp_path):
    path = tmp_path / "kaji.db"
    engine = create_engine(URL.create("sqlite", database=str(path)))
    run_migrations(engine)
    yield path, (lambda: Session(engine))
    engine.dispose()


def rows(factory=None):
    with (factory() if factory else Session(get_engine())) as db:
        return list(db.scalars(select(LoginFailure)))


def test_five_failures_block_the_key_and_others_stay_free(file_db):
    _, factory = file_db
    t = LoginThrottle(5, 300, factory)
    for _ in range(4):
        t.fail("1.2.3.4")
    assert not t.blocked("1.2.3.4")
    t.fail("1.2.3.4")
    assert t.blocked("1.2.3.4") and not t.blocked("1.2.3.5") and not t.blocked("setup:1.2.3.4")        # par clé : une autre adresse, ou le jeton de première configuration, ne sont pas touchés


def test_a_restart_does_not_reset_the_counter(file_db):
    """CRITÈRE DE SORTIE : un nouvel objet (= un backend redémarré, mémoire vide) sur la même base voit les échecs d'avant."""
    path, factory = file_db
    before = LoginThrottle(5, 300, factory)
    for _ in range(5):
        before.fail("10.0.0.9")
    assert before.blocked("10.0.0.9")
    engine2 = create_engine(URL.create("sqlite", database=str(path)))                               # « redémarrage » : nouveau moteur, nouvel objet
    after = LoginThrottle(5, 300, lambda: Session(engine2))
    assert after.blocked("10.0.0.9") and not after.blocked("10.0.0.10")
    engine2.dispose()


def test_failures_older_than_the_window_are_ignored_then_purged(file_db):
    path, factory = file_db
    t = LoginThrottle(3, 300, factory)
    old = datetime.now(timezone.utc) - timedelta(seconds=301)
    with factory() as db:
        db.add_all([LoginFailure(key="9.9.9.9", ts=old) for _ in range(5)])
        db.commit()
    assert not t.blocked("9.9.9.9")                                                                 # hors fenêtre : ignorés
    t.fail("9.9.9.9")                                                                               # et supprimés au passage
    assert len(rows(factory)) == 1
    just_inside = datetime.now(timezone.utc) - timedelta(seconds=290)
    with factory() as db:
        db.add_all([LoginFailure(key="8.8.8.8", ts=just_inside) for _ in range(3)]); db.commit()
    assert t.blocked("8.8.8.8")                                                                     # 290 s < 300 s : comptés


def test_reset_clears_one_key_or_everything(file_db):
    _, factory = file_db
    t = LoginThrottle(2, 300, factory)
    for k in ("a", "a", "b", "b"):
        t.fail(k)
    t.reset("a")
    assert not t.blocked("a") and t.blocked("b")
    t.reset()
    assert not t.blocked("b") and rows(factory) == []


def test_nothing_but_the_key_and_the_time_is_stored(file_db):
    path, factory = file_db
    LoginThrottle(5, 300, factory).fail("203.0.113.7")
    c = sqlite3.connect(path)
    assert [r[1] for r in c.execute("PRAGMA table_info(login_failures)")] == ["id", "key", "ts"]
    assert [r[0] for r in c.execute("SELECT key FROM login_failures")] == ["203.0.113.7"]
    c.close()


def test_a_blocked_key_does_not_grow_the_table_through_the_login_route(client):
    client.post("/api/auth/setup", json={"username": "alice", "password": PWD})
    anonymous = TestClient(app)
    codes = [anonymous.post("/api/auth/login", json={"username": "alice", "password": f"mauvais-mot-de-passe-{i}"}).status_code for i in range(9)]
    assert codes == [401] * 5 + [429] * 4
    assert len(rows()) == 5                                                                          # les refus 429 n'ajoutent rien : la table reste bornée
    assert all("mauvais" not in r.key and "alice" not in r.key for r in rows())                      # ni mot de passe ni identifiant


def test_the_block_survives_a_restart_through_the_real_login_route(client):
    client.post("/api/auth/setup", json={"username": "alice", "password": PWD})
    anonymous = TestClient(app)
    for i in range(5):
        anonymous.post("/api/auth/login", json={"username": "alice", "password": f"mauvais-mot-de-passe-{i}"})
    app_throttle_before = throttle
    from app import security
    security.throttle = LoginThrottle()                                  # objet neuf : la mémoire d'avant est perdue, comme après un redémarrage
    try:
        import app.routers.auth as auth_routes
        auth_routes.throttle = security.throttle
        r = anonymous.post("/api/auth/login", json={"username": "alice", "password": PWD})            # même le BON mot de passe
        assert r.status_code == 429
    finally:
        security.throttle = app_throttle_before
        auth_routes.throttle = app_throttle_before


def test_a_success_clears_the_failures_of_that_address(client):
    client.post("/api/auth/setup", json={"username": "alice", "password": PWD})
    anonymous = TestClient(app)
    for i in range(3):
        anonymous.post("/api/auth/login", json={"username": "alice", "password": f"mauvais-mot-de-passe-{i}"})
    assert len(rows()) == 3
    assert anonymous.post("/api/auth/login", json={"username": "alice", "password": PWD}).status_code == 200
    assert rows() == []


def test_the_setup_token_guess_counter_is_persistent_too(client, monkeypatch):
    from app.config import get_settings
    client.post("/api/auth/logout")
    with Session(get_engine()) as db:
        from app.models import AdminUser
        for u in db.scalars(select(AdminUser)):
            db.delete(u)
        db.commit()
    monkeypatch.setattr(get_settings(), "kaji_setup_token", "le-vrai-jeton-de-premiere-configuration")
    anonymous = TestClient(app)
    codes = [anonymous.post("/api/auth/setup", json={"username": "alice", "password": PWD, "setup_token": f"faux-{i}"}).status_code for i in range(7)]
    assert codes[:5] == [403] * 5 and codes[5:] == [429, 429]
    assert {r.key.split(":")[0] for r in rows()} == {"setup"}
