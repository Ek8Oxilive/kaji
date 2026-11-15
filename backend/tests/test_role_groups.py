"""Groupes de l'annuaire / du SSO → rôle de Kaji (lot #443) : « le groupe informatique est administrateur ». Correspondance exacte, rien sans groupe configuré, jamais sans administrateur."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ldaplogin, rolemap
from app.config import get_settings
from app.db import get_engine
from app.main import app
from app.models import AdminUser, AuditLog
from app.security import throttle
from tests.test_ldap_login import ALICE_DN, ALICE_PWD, BASE, READER_DN, READER_PWD, FakeDirectory

PWD = "un-mot-de-passe-solide"
ADMINS = "cn=informatique,ou=groupes,dc=lab,dc=test"
OPERATORS = "cn=exploitation,ou=groupes,dc=lab,dc=test"


class S:
    """Réglages minimaux pour `rolemap` (le fournisseur « ldap »)."""

    def __init__(self, admin="", operator="", allow=True, default="viewer"):
        self.kaji_ldap_admin_group, self.kaji_ldap_operator_group, self.kaji_ldap_allow_admin, self.kaji_ldap_default_role = admin, operator, allow, default


# ---------------------------------------------------------------- le calcul du rôle
def test_without_any_group_configured_nothing_is_touched():
    assert rolemap.target_role(S(), "ldap", [ADMINS]) is None


def test_membership_gives_the_role_and_the_highest_wins():
    s = S(admin=ADMINS, operator=OPERATORS)
    assert rolemap.target_role(s, "ldap", [ADMINS]) == "admin"
    assert rolemap.target_role(s, "ldap", [OPERATORS]) == "operator"
    assert rolemap.target_role(s, "ldap", [OPERATORS, ADMINS]) == "admin"
    assert rolemap.target_role(s, "ldap", ["cn=autre,dc=lab"]) == "viewer"
    assert rolemap.target_role(s, "ldap", []) == "viewer"


def test_the_match_is_exact_and_ignores_case_and_spaces_around_separators_only():
    s = S(admin=ADMINS)
    assert rolemap.target_role(s, "ldap", ["CN=Informatique, OU=Groupes , DC=lab,dc=test"]) == "admin"
    assert rolemap.target_role(s, "ldap", [ADMINS + ",dc=extra"]) == "viewer"                  # plus long : pas le même groupe
    assert rolemap.target_role(s, "ldap", [ADMINS[:-3]]) == "viewer"                           # plus court
    assert rolemap.target_role(s, "ldap", ["cn=informatique-externes,ou=groupes,dc=lab,dc=test"]) == "viewer"
    assert rolemap.target_role(S(admin="kaji-admins"), "oidc" if False else "ldap", ["xkaji-admins", "kaji-admins-test"]) == "viewer"


def test_the_administrator_group_is_ignored_when_administrators_are_not_allowed():
    assert rolemap.target_role(S(admin=ADMINS, operator=OPERATORS, allow=False), "ldap", [ADMINS]) == "viewer"
    assert rolemap.target_role(S(admin=ADMINS, operator=OPERATORS, allow=False), "ldap", [ADMINS, OPERATORS]) == "operator"


def test_an_unsafe_default_role_falls_back_to_viewer():
    assert rolemap.target_role(S(admin=ADMINS, default="admin"), "ldap", []) == "viewer"
    assert rolemap.new_account_role(S(default="admin"), "ldap", []) is None                    # sans groupe configuré : pas de création avec un rôle administrateur par défaut
    assert rolemap.new_account_role(S(default="operator"), "ldap", []) == "operator"
    assert rolemap.new_account_role(S(admin=ADMINS), "ldap", [ADMINS]) == "admin"              # administrateur SEULEMENT par groupe


@pytest.mark.parametrize("raw,expected", [("g", ["g"]), (["a", "b"], ["a", "b"]), (("a",), ["a"]), ([1, "a", None], ["a"]), (None, []), (5, []), ({"a": 1}, [])])
def test_groups_are_read_defensively(raw, expected):
    assert rolemap.as_list(raw) == expected


# ---------------------------------------------------------------- l'annuaire, de bout en bout
@pytest.fixture
def d(client, monkeypatch):
    directory = FakeDirectory()
    for k, v in {"KAJI_LDAP_URL": "ldaps://annuaire.test:636", "KAJI_LDAP_BASE_DN": BASE, "KAJI_LDAP_BIND_DN": READER_DN, "KAJI_LDAP_BIND_PASSWORD": READER_PWD,
                 "KAJI_LDAP_GROUPS_ATTR": "description", "KAJI_LDAP_ADMIN_GROUP": ADMINS, "KAJI_LDAP_OPERATOR_GROUP": OPERATORS, "KAJI_LDAP_AUTO_CREATE": "true"}.items():
        monkeypatch.setenv(k, v)
    for k in ("START_TLS", "CA_FILE", "USER_FILTER", "USERNAME_ATTR", "DEFAULT_ROLE", "ALLOW_ADMIN", "LABEL"):
        monkeypatch.delenv(f"KAJI_LDAP_{k}", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(ldaplogin, "_connection", directory.connect)
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    directory.setenv = monkeypatch.setenv
    yield directory
    get_settings.cache_clear()
    throttle.reset()


def person(d, uid, groups):
    d.person(uid, f"pw-de-{uid}-assez-long", description=groups)


def sign_in(uid):
    b = TestClient(app)
    r = b.post("/api/auth/ldap/login", json={"username": uid, "password": f"pw-de-{uid}-assez-long"})
    return r, b


def role_of(uid):
    with Session(get_engine()) as db:
        u = db.scalar(select(AdminUser).where(AdminUser.username == uid))
        return u.role if u else None


def sync_rows():
    with Session(get_engine()) as db:
        return db.scalars(select(AuditLog).where(AuditLog.action == "role-sync").order_by(AuditLog.id)).all()


def test_a_member_of_the_it_group_is_created_as_an_administrator_and_can_drive_everything(d):
    person(d, "ines", [ADMINS])
    r, b = sign_in("ines")
    assert r.status_code == 200 and role_of("ines") == "admin" and b.get("/api/auth/me").json()["role"] == "admin"
    assert b.get("/api/kaji-users").status_code == 200                                         # vraiment administrateur : la gestion des comptes lui est ouverte


def test_the_other_groups_give_operator_or_the_default_role(d):
    person(d, "omar", [OPERATORS])
    person(d, "vera", ["cn=compta,dc=lab"])
    person(d, "nogroup", [])
    assert [sign_in(u)[0].status_code for u in ("omar", "vera", "nogroup")] == [200, 200, 200]
    assert (role_of("omar"), role_of("vera"), role_of("nogroup")) == ("operator", "viewer", "viewer")


def test_an_existing_account_follows_its_groups_at_every_sign_in_and_each_change_is_audited(d):
    person(d, "paul", [])
    sign_in("paul")
    assert role_of("paul") == "viewer"
    d.admin.strategy.remove_entry("uid=paul,ou=people," + BASE)
    person(d, "paul", [OPERATORS])
    sign_in("paul")
    assert role_of("paul") == "operator"
    d.admin.strategy.remove_entry("uid=paul,ou=people," + BASE)
    person(d, "paul", [ADMINS])
    sign_in("paul")
    assert role_of("paul") == "admin"
    d.admin.strategy.remove_entry("uid=paul,ou=people," + BASE)
    person(d, "paul", [])                                                                       # retiré du groupe : le rôle suit à la connexion suivante
    sign_in("paul")
    assert role_of("paul") == "viewer"
    assert [e.detail for e in sync_rows()] == ["rôle viewer → operator (groupes de l'annuaire)", "rôle operator → admin (groupes de l'annuaire)", "rôle admin → viewer (groupes de l'annuaire)"]
    assert all(e.username == "paul" and e.target == "ldap" for e in sync_rows())


def test_the_last_administrator_is_never_demoted(d):
    d.setenv("KAJI_LDAP_ALLOW_ADMIN", "true")
    get_settings.cache_clear()
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "admin", "password": PWD})
    d.person("admin", "pw-de-admin-assez-long", description=[])                                 # le seul administrateur de Kaji n'est dans aucun groupe
    r, _b = sign_in("admin")
    assert r.status_code == 200 and role_of("admin") == "admin" and sync_rows() == []


def test_an_administrator_can_be_demoted_when_another_one_remains(d):
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "admin", "password": PWD})
    assert c.post("/api/kaji-users", json={"username": "second", "password": PWD, "role": "admin"}).status_code in (200, 201)
    person(d, "second", [])
    sign_in("second")
    assert role_of("second") == "viewer" and role_of("admin") == "admin"


def test_without_a_configured_group_roles_are_never_touched(d):
    d.setenv("KAJI_LDAP_ADMIN_GROUP", "")
    d.setenv("KAJI_LDAP_OPERATOR_GROUP", "")
    get_settings.cache_clear()
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "admin", "password": PWD})
    c.post("/api/kaji-users", json={"username": "nina", "password": PWD, "role": "operator"})
    person(d, "nina", [ADMINS])                                                                 # dans le groupe, mais la correspondance n'est pas configurée
    assert sign_in("nina")[0].status_code == 200 and role_of("nina") == "operator" and sync_rows() == []


def test_administrators_by_group_can_be_switched_off(d):
    d.setenv("KAJI_LDAP_ALLOW_ADMIN", "false")
    get_settings.cache_clear()
    person(d, "ines", [ADMINS])
    r, _b = sign_in("ines")
    assert r.status_code == 200 and role_of("ines") == "viewer"                                 # créée, mais pas administratrice


def test_a_group_name_that_only_contains_the_admin_group_does_not_give_the_role(d):
    person(d, "eve", [ADMINS + "-externes", "x" + ADMINS])
    sign_in("eve")
    assert role_of("eve") == "viewer"


def test_the_groups_of_a_directory_entry_are_read_from_the_configured_attribute_only(d):
    d.person("tom", "pw-de-tom-assez-long", description=["autre"], cn="tom", sn=ADMINS)       # le groupe est dans un AUTRE attribut : sans effet
    sign_in("tom")
    assert role_of("tom") == "viewer"
    assert ldaplogin.authenticate("alice", ALICE_PWD)[2] == []
    assert ALICE_DN


def test_a_wrong_groups_attribute_name_is_refused_by_the_configuration_check(d):
    d.setenv("KAJI_LDAP_GROUPS_ATTR", "memberOf)(x")
    get_settings.cache_clear()
    with pytest.raises(ldaplogin.LdapError, match="attribut"):
        ldaplogin.authenticate("alice", ALICE_PWD)
