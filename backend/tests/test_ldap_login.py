"""Connexion par annuaire LDAP / AD (lot #443, jalon J2), contre un ANNUAIRE SIMULÉ (`ldap3` en mode MOCK_SYNC : vraies recherches avec filtres, vraies liaisons avec mot de passe)."""
import ssl

import pytest
from fastapi.testclient import TestClient
from ldap3 import MOCK_SYNC, OFFLINE_SLAPD_2_4, Connection, Server
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ldaplogin
from app.config import get_settings
from app.db import get_engine
from app.main import app
from app.models import AdminUser, AuditLog, UserIdentity
from app.security import throttle

PWD = "un-mot-de-passe-solide"
BASE = "dc=lab,dc=test"
READER_DN, READER_PWD = "cn=lecteur,dc=lab,dc=test", "mot-de-passe-du-compte-de-lecture"
ALICE_DN = "uid=alice,ou=people,dc=lab,dc=test"
ALICE_PWD = "mot-de-passe-annuaire-d-alice"


class FakeDirectory:
    def __init__(self):
        self.server = Server("annuaire.test", get_info=OFFLINE_SLAPD_2_4)
        self.admin = Connection(self.server, user="cn=admin", password="x", client_strategy=MOCK_SYNC)
        self.admin.strategy.add_entry(READER_DN, {"objectClass": "person", "cn": "lecteur", "sn": "x", "userPassword": READER_PWD})
        self.person("alice", ALICE_PWD)
        self.binds: list[tuple[str, str]] = []
        self.down = False

    def person(self, uid, password, dn=None, **extra):
        self.admin.strategy.add_entry(dn or f"uid={uid},ou=people,{BASE}", {"objectClass": "person", "uid": uid, "cn": uid, "sn": uid, "userPassword": password, **extra})

    def connect(self, s, user, password):
        if self.down:
            raise OSError("annuaire éteint")
        self.binds.append((user, password))
        c = Connection(self.server, user=user, password=password, client_strategy=MOCK_SYNC, raise_exceptions=False)
        if not c.bind():
            raise ldaplogin.LdapError("liaison refusée")
        return c


@pytest.fixture
def d(client, monkeypatch):
    directory = FakeDirectory()
    for k, v in {"KAJI_LDAP_URL": "ldaps://annuaire.test:636", "KAJI_LDAP_BASE_DN": BASE, "KAJI_LDAP_BIND_DN": READER_DN, "KAJI_LDAP_BIND_PASSWORD": READER_PWD}.items():
        monkeypatch.setenv(k, v)
    for k in ("KAJI_LDAP_START_TLS", "KAJI_LDAP_CA_FILE", "KAJI_LDAP_USER_FILTER", "KAJI_LDAP_USERNAME_ATTR", "KAJI_LDAP_AUTO_CREATE", "KAJI_LDAP_DEFAULT_ROLE", "KAJI_LDAP_LABEL"):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(ldaplogin, "_connection", directory.connect)
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    client.post("/api/kaji-users", json={"username": "alice", "password": PWD, "role": "operator"})
    directory.setenv = monkeypatch.setenv
    yield directory
    get_settings.cache_clear()
    throttle.reset()


def login(username="alice", password=ALICE_PWD):
    b = TestClient(app)
    return b.post("/api/auth/ldap/login", json={"username": username, "password": password}), b


def rows(action="login-ldap"):
    with Session(get_engine()) as db:
        return db.scalars(select(AuditLog).where(AuditLog.action == action)).all()


# ---------------------------------------------------------------- désactivé et configuration
def test_disabled_by_default(client):
    assert client.get("/api/auth/ldap/status").json() == {"enabled": False, "label": None}
    assert client.post("/api/auth/ldap/login", json={"username": "alice", "password": "x"}).status_code == 404


def test_status_when_enabled_has_a_bounded_label_and_no_secret(d):
    d.setenv("KAJI_LDAP_LABEL", "Annuaire " + "x" * 80)
    get_settings.cache_clear()
    st = TestClient(app).get("/api/auth/ldap/status").json()
    assert st["enabled"] is True and len(st["label"]) == 40 and READER_PWD not in str(st) and "annuaire.test" not in str(st)


@pytest.mark.parametrize("env,word", [
    ({"KAJI_LDAP_URL": "ldap://annuaire.test"}, "chiffrement"),                                  # ni ldaps ni STARTTLS : mot de passe en clair
    ({"KAJI_LDAP_URL": "http://annuaire.test"}, "invalide"),
    ({"KAJI_LDAP_URL": "ldaps://"}, "invalide"),
    ({"KAJI_LDAP_BASE_DN": ""}, "manquant"),
    ({"KAJI_LDAP_BIND_DN": ""}, "manquant"),
    ({"KAJI_LDAP_BIND_PASSWORD": ""}, "manquant"),
    ({"KAJI_LDAP_USER_FILTER": "(uid=alice)"}, "filtre"),                                        # sans {username} : tout le monde serait « alice »
    ({"KAJI_LDAP_USERNAME_ATTR": "uid)(objectClass=*"}, "filtre"),
])
def test_an_unsafe_configuration_is_refused_before_any_call(d, env, word):
    for k, v in env.items():
        d.setenv(k, v)
    get_settings.cache_clear()
    r, _b = login()
    assert r.status_code == 401 and not d.binds
    assert word in rows()[0].detail


def test_plain_ldap_is_allowed_with_starttls(d):
    d.setenv("KAJI_LDAP_URL", "ldap://annuaire.test")
    d.setenv("KAJI_LDAP_START_TLS", "true")
    get_settings.cache_clear()
    assert ldaplogin.configuration_problem() is None


# ---------------------------------------------------------------- le cas qui marche
def test_a_known_person_gets_a_session_and_is_linked_by_dn(d):
    r, b = login()
    assert r.status_code == 200 and r.json() == {"username": "alice"} and "kaji_session" in r.headers["set-cookie"]
    assert b.get("/api/auth/me").json() == {"username": "alice", "role": "operator", "restricted": False}
    with Session(get_engine()) as db:
        link = db.scalars(select(UserIdentity)).one()
        assert link.issuer == "ldap:ldaps://annuaire.test:636" and link.sub == ALICE_DN.lower() and db.get(AdminUser, link.user_id).username == "alice"
    ok = rows()
    assert len(ok) == 1 and ok[0].status == "started" and ok[0].username == "alice"


def test_the_reader_searches_then_the_person_binds_with_her_own_dn_and_password(d):
    login()
    assert d.binds == [(READER_DN, READER_PWD), (ALICE_DN, ALICE_PWD)]


def test_the_password_is_never_kept_logged_or_returned(d):
    r, _b = login()
    blob = r.text + repr([(x.username, x.target, x.detail) for x in rows()])
    assert ALICE_PWD not in blob
    with Session(get_engine()) as db:
        assert ALICE_PWD not in repr([(u.username, u.password_hash) for u in db.scalars(select(AdminUser))])


def test_a_linked_person_is_found_again_by_the_link_not_by_the_name(d):
    login()
    with Session(get_engine()) as db:                                                             # le compte de Kaji est renommé : le lien fait foi
        db.scalars(select(AdminUser).where(AdminUser.username == "alice")).one().username = "alice-renommee"
        db.commit()
    r, _b = login()
    assert r.status_code == 200 and r.json() == {"username": "alice-renommee"}


# ---------------------------------------------------------------- les refus
def test_a_wrong_password_is_refused_with_the_generic_message_and_audited(d):
    r, _b = login(password="mauvais-mot-de-passe")
    assert r.status_code == 401 and r.json()["detail"] == "Identifiants invalides" and "kaji_session" not in r.headers.get("set-cookie", "")
    e = rows()[0]
    assert e.status == "error" and e.detail == "identifiants refusés" and "mauvais-mot-de-passe" not in e.detail


def test_an_unknown_person_gets_the_same_answer_as_a_wrong_password(d):
    a, _ = login(password="mauvais-mot-de-passe")
    b, _ = login(username="inconnu")
    assert (a.status_code, a.json()) == (b.status_code, b.json()) == (401, {"detail": "Identifiants invalides"})
    assert {x.detail for x in rows()} == {"identifiants refusés"}


def test_an_empty_password_is_refused_before_reaching_the_directory(d):
    """Beaucoup d'annuaires acceptent une liaison sans mot de passe comme une liaison anonyme réussie."""
    with pytest.raises(ldaplogin.LdapError):
        ldaplogin.authenticate("alice", "")
    r = TestClient(app).post("/api/auth/ldap/login", json={"username": "alice", "password": ""})
    assert r.status_code == 422 and not d.binds


def test_a_nul_byte_in_the_password_is_refused(d):
    with pytest.raises(ldaplogin.LdapError):
        ldaplogin.authenticate("alice", "a\x00b")
    assert not d.binds


@pytest.mark.parametrize("name", ["*", "a*", "alice)(uid=*", "*)(uid=alice", "ali ce", "al", "a" * 70, "alice\\", "../alice", "alice\x00"])
def test_names_that_could_inject_into_the_filter_are_refused_before_any_call(d, name):
    with pytest.raises(ldaplogin.LdapError):
        ldaplogin.authenticate(name, ALICE_PWD)
    assert not d.binds


def test_the_filter_value_is_escaped(d):
    assert ldaplogin.escape_filter_value("a*(b)\\c\x00") == "a\\2a\\28b\\29\\5cc\\00"


def test_escaping_alone_stops_an_injection_even_if_the_name_check_were_loosened(d, monkeypatch):
    """Défense en profondeur : même avec un contrôle de nom permissif, `*` ne désigne pas « tout le monde »."""
    import re
    monkeypatch.setattr(ldaplogin, "USERNAME", re.compile(r".+"))
    with pytest.raises(ldaplogin.LdapError):
        ldaplogin.authenticate("*", ALICE_PWD)
    with pytest.raises(ldaplogin.LdapError):
        ldaplogin.authenticate("ali*", ALICE_PWD)
    assert all(u != ALICE_DN for u, _p in d.binds)


def test_two_entries_for_one_name_are_a_refusal_never_the_first(d):
    d.person("alice", "autre-mot-de-passe", dn=f"uid=alice,ou=autre,{BASE}")
    r, _b = login()
    assert r.status_code == 401 and rows()[0].detail == "identifiants refusés"
    assert all(u != ALICE_DN for u, _p in d.binds)                                                 # personne n'a été liée


def test_an_entry_found_under_another_identity_cannot_log_in_as_that_identity(d):
    """Filtre sur `cn` : on se présente avec le `cn` de carol, mais l'entrée porte l'identifiant « bob » : elle ne doit pas ouvrir le compte « bob » de Kaji."""
    d.setenv("KAJI_LDAP_USER_FILTER", "(&(objectClass=person)(cn={username}))")
    get_settings.cache_clear()
    d.person("bob", "pw-de-carol-assez-long", dn=f"cn=carol,ou=people,{BASE}", cn="carol")
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "admin", "password": PWD})
    assert c.post("/api/kaji-users", json={"username": "bob", "password": PWD, "role": "operator"}).status_code in (200, 201)
    r, _b = login(username="carol", password="pw-de-carol-assez-long")
    assert r.status_code == 401
    with Session(get_engine()) as db:
        assert db.scalars(select(UserIdentity)).all() == []


def test_an_entry_with_several_identifier_values_is_ambiguous_and_refused(d):
    d.admin.strategy.add_entry(f"uid=multi,ou=people,{BASE}", {"objectClass": "person", "uid": ["multi", "zzz-second"], "cn": "m", "sn": "m", "userPassword": "pw-multi-assez-long"})
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "admin", "password": PWD})
    c.post("/api/kaji-users", json={"username": "multi", "password": PWD, "role": "operator"})
    assert login(username="multi", password="pw-multi-assez-long")[0].status_code == 401            # sans cette règle, la première valeur suffirait à ouvrir le compte
    assert login(username="zzz-second", password="pw-multi-assez-long")[0].status_code == 401


def test_the_link_does_not_depend_on_the_case_of_the_dn(d):
    login()
    with Session(get_engine()) as db:
        a = ldaplogin.resolve_user(db, "alice", ALICE_DN.upper())
        b = ldaplogin.resolve_user(db, "alice", ALICE_DN)
        assert a is not None and b is not None and a.id == b.id and len(db.scalars(select(UserIdentity)).all()) == 1


def test_an_entry_whose_attribute_differs_from_the_name_is_refused(d):
    d.setenv("KAJI_LDAP_USER_FILTER", "(&(objectClass=person)(cn={username}))")                    # filtre sur cn, attribut d'identifiant uid
    d.person("bob", "pw-de-bob-assez-long", dn=f"cn=carol,ou=people,{BASE}", cn="carol")
    get_settings.cache_clear()
    r, _b = login(username="carol", password="pw-de-bob-assez-long")
    assert r.status_code == 401


def test_the_reader_account_refused_by_the_directory_is_a_refusal(d):
    d.setenv("KAJI_LDAP_BIND_PASSWORD", "mauvais-mot-de-passe-du-lecteur")
    get_settings.cache_clear()
    r, _b = login()
    assert r.status_code == 401 and "compte de lecture" in rows()[0].detail and "mauvais-mot-de-passe-du-lecteur" not in rows()[0].detail


def test_a_directory_that_is_down_is_a_refusal_with_a_short_fixed_reason(d):
    d.down = True
    r, _b = login()
    assert r.status_code == 401 and rows()[0].detail == "annuaire injoignable"


def test_after_five_failures_the_address_is_blocked_even_with_the_right_password(d):
    for _ in range(5):
        assert login(password="mauvais-mot-de-passe")[0].status_code == 401
    r, _b = login()
    assert r.status_code == 429 and "kaji_session" not in r.headers.get("set-cookie", "")


def test_a_success_resets_the_counter(d):
    for _ in range(4):
        login(password="mauvais-mot-de-passe")
    assert login()[0].status_code == 200
    for _ in range(4):
        login(password="mauvais-mot-de-passe")
    assert login()[0].status_code == 200


# ---------------------------------------------------------------- qui devient quel compte
def test_a_person_without_a_kaji_account_is_refused_by_default(d):
    d.person("bob", "pw-de-bob-assez-long")
    r, _b = login(username="bob", password="pw-de-bob-assez-long")
    assert r.status_code == 401 and rows()[0].detail == "aucun compte de Kaji pour cette personne" and rows()[0].username == "bob"
    with Session(get_engine()) as db:
        assert db.scalar(select(AdminUser).where(AdminUser.username == "bob")) is None


def test_auto_create_makes_a_viewer_who_cannot_use_the_local_password(d):
    d.setenv("KAJI_LDAP_AUTO_CREATE", "true")
    get_settings.cache_clear()
    d.person("bob", "pw-de-bob-assez-long")
    r, b = login(username="bob", password="pw-de-bob-assez-long")
    assert r.status_code == 200 and b.get("/api/auth/me").json()["role"] == "viewer"
    assert TestClient(app).post("/api/auth/login", json={"username": "bob", "password": "pw-de-bob-assez-long"}).status_code == 401      # mot de passe local inconnu de tous


@pytest.mark.parametrize("role,ok", [("operator", True), ("viewer", True), ("admin", False), ("root", False), ("", False)])
def test_auto_create_never_creates_an_administrator(d, role, ok):
    d.setenv("KAJI_LDAP_AUTO_CREATE", "true")
    d.setenv("KAJI_LDAP_DEFAULT_ROLE", role)
    get_settings.cache_clear()
    d.person("bob", "pw-de-bob-assez-long")
    r, _b = login(username="bob", password="pw-de-bob-assez-long")
    assert (r.status_code == 200) is ok


def test_a_directory_namesake_never_becomes_the_local_administrator(d):
    """Un « admin » de l'annuaire ne prend pas le compte administrateur local : les administrateurs gardent leur mot de passe local."""
    d.person("admin", "pw-annuaire-de-l-homonyme")
    r, _b = login(username="admin", password="pw-annuaire-de-l-homonyme")
    assert r.status_code == 401 and rows()[0].detail == "aucun compte de Kaji pour cette personne"
    with Session(get_engine()) as db:
        assert db.scalars(select(UserIdentity)).all() == []


def test_a_name_taken_over_in_the_directory_does_not_reach_an_already_linked_account(d):
    login()                                                                                        # alice est reliée à SON entrée
    d.person("alice", "pw-du-nouvel-arrivant", dn=f"uid=alice,ou=nouveaux,{BASE}")                  # une AUTRE entrée reprend le nom (et l'ancienne disparaît du filtre)
    d.admin.strategy.remove_entry(ALICE_DN)
    r, _b = login(password="pw-du-nouvel-arrivant")
    assert r.status_code == 401 and rows()[-1].detail == "aucun compte de Kaji pour cette personne"


def test_two_links_cannot_share_one_directory_entry(d):
    login()
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": PWD})
    client.post("/api/kaji-users", json={"username": "alice2", "password": PWD, "role": "viewer"})
    with Session(get_engine()) as db:
        assert len(db.scalars(select(UserIdentity)).all()) == 1


# ---------------------------------------------------------------- double authentification de Kaji
def test_a_person_with_totp_gets_a_challenge_not_a_session(d):
    import app.totpstore as ts
    orig = ts.is_enabled
    ts.is_enabled = lambda db, user_id: True
    try:
        r, _b = login()
    finally:
        ts.is_enabled = orig
    assert r.status_code == 200 and r.json()["totp_required"] is True and "kaji_session" not in r.headers.get("set-cookie", "")


# ---------------------------------------------------------------- la connexion réelle (ldap3 simulé au niveau de la classe)
def test_the_real_connection_requires_a_verified_certificate(monkeypatch):
    s = get_settings()
    srv = ldaplogin._server(s.model_copy(update={"kaji_ldap_url": "ldaps://annuaire.test:636", "kaji_ldap_ca_file": ""}))
    assert srv.tls.validate == ssl.CERT_REQUIRED and srv.ssl is True


def test_starttls_is_negotiated_before_the_bind_and_a_failure_is_a_refusal(monkeypatch):
    calls = []

    class Stub:
        def __init__(self, server, **kw):
            calls.append(("new", kw["user"]))

        def open(self):
            calls.append("open")
            return True

        def start_tls(self):
            calls.append("starttls")
            return self.ok

        def bind(self):
            calls.append("bind")
            return True
    Stub.ok = True
    import ldap3
    monkeypatch.setattr(ldap3, "Connection", Stub)
    s = get_settings().model_copy(update={"kaji_ldap_url": "ldap://annuaire.test", "kaji_ldap_start_tls": True})
    ldaplogin._connection(s, "cn=x", "pw")
    assert calls == [("new", "cn=x"), "open", "starttls", "bind"]
    calls.clear()
    Stub.ok = False
    with pytest.raises(ldaplogin.LdapError, match="chiffrement"):
        ldaplogin._connection(s, "cn=x", "pw")
    assert "bind" not in calls                                                                      # jamais de mot de passe avant le chiffrement
