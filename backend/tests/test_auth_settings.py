"""Menu « Authentification » (lot #443) : réglages du SSO et de l'annuaire saisis dans l'interface, secrets chiffrés en écriture seule, base prioritaire sur le `.env`."""
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import authconfig, backup, crypto, ldaplogin, oidc
from app.config import get_settings
from app.db import get_engine
from app.main import app
from app.models import AuditLog, AuthSetting
from app.secretrotate import rotate_secret_key
from app.security import throttle
from tests.test_ldap_login import ALICE_DN, ALICE_PWD, BASE, READER_DN, READER_PWD, FakeDirectory
from tests.test_secret_rotation import NEW, OLD, old_db, session

PWD = "un-mot-de-passe-solide"
LDAP = {"url": "ldaps://annuaire.test:636", "base_dn": BASE, "bind_dn": READER_DN}
OIDC = {"issuer": "https://idp.test/realms/lab", "client_id": "kaji", "redirect_uri": "https://kaji.test/api/auth/oidc/callback"}
SECRET_FIELD = "ce-secret-ne-doit-apparaitre-nulle-part"


@pytest.fixture
def adm(client, monkeypatch):
    for k in ("URL", "START_TLS", "CA_FILE", "BASE_DN", "BIND_DN", "BIND_PASSWORD", "USER_FILTER", "USERNAME_ATTR", "AUTO_CREATE", "DEFAULT_ROLE", "ALLOW_ADMIN", "LABEL"):
        monkeypatch.delenv(f"KAJI_LDAP_{k}", raising=False)
    for k in ("ISSUER", "CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI", "SCOPES", "USERNAME_CLAIM", "AUTO_CREATE", "DEFAULT_ROLE", "ALLOW_ADMIN", "LABEL"):
        monkeypatch.delenv(f"KAJI_OIDC_{k}", raising=False)
    get_settings.cache_clear()
    directory = FakeDirectory()
    monkeypatch.setattr(ldaplogin, "_connection", directory.connect)
    assert client.post("/api/auth/setup", json={"username": "admin", "password": PWD}).status_code == 201
    client.setenv = monkeypatch.setenv
    client.dir = directory
    yield client
    get_settings.cache_clear()
    oidc.reset_cache()
    throttle.reset()


def put(c, provider, values=None, secrets=None, **kw):
    return c.put(f"/api/auth-settings/{provider}", json={"values": values or {}, "secrets": secrets or {}, **kw})


def save_ldap(c, **extra):
    r = put(c, "ldap", {**LDAP, **extra}, {"bind_password": READER_PWD}, confirm=True)
    assert r.status_code == 200, r.text
    return r


def audit_rows():
    with Session(get_engine()) as db:
        return db.scalars(select(AuditLog).where(AuditLog.action == "auth-settings").order_by(AuditLog.id)).all()


# ---------------------------------------------------------------- lecture
def test_nothing_configured_by_default(adm):
    r = adm.get("/api/auth-settings").json()
    assert set(r) == {"ldap", "oidc"}
    for p in r.values():
        assert p["enabled"] is False and p["source"] == "none" and p["problems"] == [] and p["updated_by"] is None
    assert r["ldap"]["secrets"] == {"bind_password": False} and r["oidc"]["secrets"] == {"client_secret": False}


def test_the_env_configuration_is_shown_and_applies_without_any_row(adm):
    adm.setenv("KAJI_LDAP_URL", LDAP["url"])
    adm.setenv("KAJI_LDAP_BASE_DN", BASE)
    adm.setenv("KAJI_LDAP_BIND_DN", READER_DN)
    adm.setenv("KAJI_LDAP_BIND_PASSWORD", READER_PWD)
    get_settings.cache_clear()
    v = adm.get("/api/auth-settings").json()["ldap"]
    assert v["enabled"] is True and v["source"] == "env" and v["values"]["url"] == LDAP["url"] and v["secrets"] == {"bind_password": True}
    assert READER_PWD not in json.dumps(v) and adm.get("/api/auth/ldap/status").json()["enabled"] is True


# ---------------------------------------------------------------- écriture
def test_dry_run_validates_and_writes_nothing(adm):
    r = put(adm, "ldap", LDAP, {"bind_password": READER_PWD}, dry_run=True)
    assert r.status_code == 200 and r.json()["dry_run"] is True and "url" in r.json()["changes"] and "bind_password (secret défini)" in r.json()["changes"]
    assert adm.get("/api/auth-settings").json()["ldap"]["source"] == "none" and audit_rows() == []


def test_a_write_needs_confirmation(adm):
    assert put(adm, "ldap", LDAP, {"bind_password": READER_PWD}).status_code == 400
    assert adm.get("/api/auth-settings").json()["ldap"]["source"] == "none"


def test_a_confirmed_write_is_saved_shown_applied_and_audited_without_values(adm):
    r = save_ldap(adm, label="Annuaire Lab").json()
    assert r["enabled"] is True and r["source"] == "database" and r["values"]["label"] == "Annuaire Lab" and r["secrets"] == {"bind_password": True} and r["updated_by"] == "admin"
    assert adm.get("/api/auth/ldap/status").json() == {"enabled": True, "label": "Annuaire Lab"}
    row = audit_rows()[0]
    assert row.status == "started" and "url" in row.detail and "bind_password (secret défini)" in row.detail and LDAP["url"] not in row.detail and READER_PWD not in row.detail


def test_a_partial_update_keeps_the_rest_and_an_unchanged_secret(adm):
    save_ldap(adm)
    r = put(adm, "ldap", {"label": "Autre"}, confirm=True).json()
    assert r["values"]["url"] == LDAP["url"] and r["values"]["label"] == "Autre" and r["secrets"] == {"bind_password": True}
    with Session(get_engine()) as db:
        assert authconfig.stored(db, "ldap")[1] == {"bind_password": READER_PWD}


def test_secrets_are_write_only_everywhere(adm):
    put(adm, "oidc", OIDC, {"client_secret": SECRET_FIELD}, confirm=True)
    blob = json.dumps(adm.get("/api/auth-settings").json()) + json.dumps(put(adm, "oidc", {"label": "x"}, confirm=True).json()) + adm.get("/api/auth/oidc/status").text
    blob += repr([(a.target, a.detail) for a in audit_rows()])
    assert SECRET_FIELD not in blob
    c = sqlite3.connect(Path(str(get_engine().url.database))) if get_engine().url.database else None
    with Session(get_engine()) as db:
        row = db.get(AuthSetting, "oidc")
        assert SECRET_FIELD not in row.secret_enc and SECRET_FIELD not in row.values_json                    # chiffré dans la base, pas en clair
        assert json.loads(crypto.decrypt(get_settings().kaji_secret_key, row.secret_enc)) == {"client_secret": SECRET_FIELD}
    del c


def test_a_secret_can_be_cleared_and_a_missing_required_one_refuses_the_configuration(adm):
    save_ldap(adm)
    r = put(adm, "ldap", {}, clear_secrets=["bind_password"], confirm=True)
    assert r.status_code == 422 and "manquant" in r.json()["detail"]                                      # url définie sans mot de passe de lecture : refusé
    with Session(get_engine()) as db:
        assert authconfig.stored(db, "ldap")[1] == {"bind_password": READER_PWD}                           # rien n'a changé
    assert put(adm, "ldap", {"url": ""}, clear_secrets=["bind_password"], confirm=True).status_code == 200       # désactiver ET retirer le secret : accepté
    v = adm.get("/api/auth-settings").json()["ldap"]
    assert v["enabled"] is False and v["secrets"] == {"bind_password": False}


@pytest.mark.parametrize("values,secrets,clear,word", [
    ({"inconnu": "x"}, {}, [], "inconnu"),
    ({"timeout": "5"}, {}, [], "entier"),
    ({"timeout": 0}, {}, [], "entier"),
    ({"timeout": 31}, {}, [], "entier"),
    ({"timeout": True}, {}, [], "entier"),
    ({"auto_create": "true"}, {}, [], "vrai ou faux"),
    ({"label": 5}, {}, [], "texte"),
    ({"label": "a\nb"}, {}, [], "contrôle"),
    ({"label": "a" * 513}, {}, [], "texte"),
    ({"ca_file": "relatif/ca.pem"}, {}, [], "chemin absolu"),
    ({"ca_file": "/etc/../etc/passwd"}, {}, [], "chemin absolu"),
    ({"default_role": "superuser"}, {}, [], "operator ou viewer"),
    ({"url": "http://annuaire.test"}, {}, [], "ldaps"),
    ({"url": "ldap://annuaire.test"}, {"bind_password": "x"}, [], "chiffrement"),
    ({}, {"inconnu": "x"}, [], "secret inconnu"),
    ({}, {"bind_password": ""}, [], "1 à 256"),
    ({}, {"bind_password": "a\nb"}, [], "une seule ligne"),
    ({}, {"bind_password": "x" * 257}, [], "1 à 256"),
    ({}, {"bind_password": "x"}, ["bind_password"], "défini et retiré"),
    ({}, {}, ["inconnu"], "secret inconnu"),
])
def test_invalid_input_is_refused_without_echoing_the_value_and_nothing_is_saved(adm, values, secrets, clear, word):
    r = put(adm, "ldap", {**LDAP, **values}, secrets or {"bind_password": READER_PWD}, clear_secrets=clear, confirm=True) if not clear and not secrets else put(adm, "ldap", {**LDAP, **values}, secrets, clear_secrets=clear, confirm=True)
    assert r.status_code == 422 and word in r.json()["detail"]
    for v in list(values.values()) + list(secrets.values()):
        if isinstance(v, str) and len(v) > 3:
            assert v not in r.text and v not in repr([(a.target, a.detail) for a in audit_rows()])
    assert adm.get("/api/auth-settings").json()["ldap"]["source"] == "none"
    assert audit_rows()[-1].status == "error"


def test_the_sso_configuration_is_checked_like_at_startup(adm):
    assert put(adm, "oidc", {**OIDC, "issuer": "http://idp.test"}, {"client_secret": "x"}, confirm=True).status_code == 422
    assert put(adm, "oidc", {**OIDC, "redirect_uri": "https://kaji.test/autre"}, {"client_secret": "x"}, confirm=True).status_code == 422
    assert put(adm, "oidc", {**OIDC, "client_id": ""}, {"client_secret": "x"}, confirm=True).status_code == 422
    assert put(adm, "oidc", {**OIDC, "username_claim": "a b"}, {"client_secret": "x"}, confirm=True).status_code == 422
    assert put(adm, "oidc", OIDC, {"client_secret": "x"}, confirm=True).status_code == 200
    assert adm.get("/api/auth/oidc/status").json()["enabled"] is True


def test_an_unknown_provider_is_a_404_and_too_many_fields_a_422(adm):
    assert put(adm, "saml", {"a": 1}, confirm=True).status_code == 404
    assert adm.delete("/api/auth-settings/saml?confirm=true").status_code == 404 and adm.post("/api/auth-settings/saml/test").status_code == 404
    assert put(adm, "ldap", {f"k{i}": "x" for i in range(21)}, confirm=True).status_code == 422


# ---------------------------------------------------------------- la base prime, retour au .env
def test_the_database_wins_over_the_env_and_a_reset_goes_back_to_it(adm):
    adm.setenv("KAJI_LDAP_URL", "ldaps://depuis-env.test:636")
    adm.setenv("KAJI_LDAP_BASE_DN", "dc=env,dc=test")
    adm.setenv("KAJI_LDAP_BIND_DN", "cn=env,dc=test")
    adm.setenv("KAJI_LDAP_BIND_PASSWORD", "mot-de-passe-de-l-env")
    get_settings.cache_clear()
    save_ldap(adm)
    assert adm.get("/api/auth-settings").json()["ldap"]["values"]["url"] == LDAP["url"]
    assert adm.delete("/api/auth-settings/ldap").status_code == 400                                       # confirmation requise
    r = adm.delete("/api/auth-settings/ldap?confirm=true").json()
    assert r["source"] == "env" and r["values"]["url"] == "ldaps://depuis-env.test:636"
    assert audit_rows()[-1].detail == "retour au .env"
    assert adm.delete("/api/auth-settings/ldap?confirm=true").json()["source"] == "env" and audit_rows()[-1].detail == "rien à retirer"


def test_a_login_works_with_settings_saved_in_the_interface_only(adm):
    adm.post("/api/kaji-users", json={"username": "alice", "password": PWD, "role": "operator"})
    save_ldap(adm)
    b = TestClient(app)
    r = b.post("/api/auth/ldap/login", json={"username": "alice", "password": ALICE_PWD})
    assert r.status_code == 200 and r.json() == {"username": "alice"}
    assert adm.dir.binds[0] == (READER_DN, READER_PWD)                                                       # le secret saisi dans l'interface est bien celui qui sert


def test_auto_create_saved_in_the_interface_is_used(adm):
    save_ldap(adm, auto_create=True, default_role="viewer")
    adm.dir.person("bob", "pw-de-bob-assez-long")
    b = TestClient(app)
    assert b.post("/api/auth/ldap/login", json={"username": "bob", "password": "pw-de-bob-assez-long"}).status_code == 200
    assert b.get("/api/auth/me").json()["role"] == "viewer"


def test_unreadable_stored_secrets_count_as_not_defined(adm, monkeypatch):
    save_ldap(adm)
    monkeypatch.setenv("KAJI_SECRET_KEY", "une-autre-cle-secrete-pour-ce-test-0123456789ab")
    get_settings.cache_clear()
    with Session(get_engine()) as db:
        assert authconfig.stored(db, "ldap")[1] == {}
        assert authconfig.view(db, "ldap")["secrets"] == {"bind_password": False} and authconfig.view(db, "ldap")["problems"]


# ---------------------------------------------------------------- droits
@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_only_administrators_can_read_or_write(adm, role):
    adm.post("/api/kaji-users", json={"username": "paul", "password": PWD, "role": role})
    b = TestClient(app)
    assert b.post("/api/auth/login", json={"username": "paul", "password": PWD}).status_code == 200
    assert b.get("/api/auth-settings").status_code == 403
    assert put(b, "ldap", LDAP, {"bind_password": READER_PWD}, confirm=True).status_code == 403
    assert b.delete("/api/auth-settings/ldap?confirm=true").status_code == 403 and b.post("/api/auth-settings/ldap/test").status_code == 403
    assert adm.get("/api/auth-settings").json()["ldap"]["source"] == "none"


# ---------------------------------------------------------------- test de connexion
def test_the_ldap_test_binds_the_reader_only_and_reports_short_fixed_texts(adm):
    assert adm.post("/api/auth-settings/ldap/test").json() == {"ok": False, "detail": "annuaire non configuré"}
    save_ldap(adm)
    r = adm.post("/api/auth-settings/ldap/test").json()
    assert r["ok"] is True and adm.dir.binds == [(READER_DN, READER_PWD)] and ALICE_PWD not in str(adm.dir.binds)       # le mot de passe de personne n'est jamais envoyé
    adm.dir.down = True
    r = adm.post("/api/auth-settings/ldap/test").json()
    assert r == {"ok": False, "detail": "annuaire injoignable"}
    adm.dir.down = False
    put(adm, "ldap", {}, {"bind_password": "mauvais-mot-de-passe-du-lecteur"}, confirm=True)
    r = adm.post("/api/auth-settings/ldap/test").json()
    assert r["ok"] is False and "mauvais-mot-de-passe" not in json.dumps(r) and "compte de lecture" in r["detail"]


def test_the_sso_test_reads_the_discovery_and_never_returns_what_the_provider_said(adm, monkeypatch):
    assert adm.post("/api/auth-settings/oidc/test").json() == {"ok": False, "detail": "SSO non configuré"}
    put(adm, "oidc", OIDC, {"client_secret": SECRET_FIELD}, confirm=True)
    seen = []

    async def good(s=None):
        seen.append(s.kaji_oidc_client_secret)
        return {"issuer": OIDC["issuer"]}
    monkeypatch.setattr(oidc, "discovery", good)
    assert adm.post("/api/auth-settings/oidc/test").json()["ok"] is True and seen == [SECRET_FIELD]            # la configuration EFFECTIVE (base) est celle qui sert

    async def bad(s=None):
        raise oidc.OidcError("fournisseur injoignable")
    monkeypatch.setattr(oidc, "discovery", bad)
    assert adm.post("/api/auth-settings/oidc/test").json() == {"ok": False, "detail": "fournisseur injoignable"}


def test_the_test_refuses_a_broken_env_configuration_with_the_reason(adm):
    adm.setenv("KAJI_LDAP_URL", "ldap://annuaire.test")
    get_settings.cache_clear()
    r = adm.post("/api/auth-settings/ldap/test").json()
    assert r["ok"] is False and "chiffrement" in r["detail"]


# ---------------------------------------------------------------- test avec les valeurs de la fenêtre, NON enregistrées
def test_the_test_can_use_the_unsaved_values_of_the_form_and_saves_nothing(adm):
    r = adm.post("/api/auth-settings/ldap/test", json={"values": LDAP, "secrets": {"bind_password": READER_PWD}}).json()
    assert r["ok"] is True and adm.dir.binds == [(READER_DN, READER_PWD)]
    assert adm.get("/api/auth-settings").json()["ldap"]["source"] == "none" and audit_rows() == []                   # rien n'est enregistré ni audité
    with Session(get_engine()) as db:
        assert db.get(AuthSetting, "ldap") is None


def test_the_unsaved_test_falls_back_on_the_stored_secret_when_none_is_typed(adm):
    save_ldap(adm)
    adm.dir.binds.clear()
    r = adm.post("/api/auth-settings/ldap/test", json={"values": {"label": "x"}}).json()
    assert r["ok"] is True and adm.dir.binds == [(READER_DN, READER_PWD)]                                             # le secret enregistré sert, aucun besoin de le retaper


def test_the_unsaved_test_reports_invalid_input_without_echoing_it(adm):
    r = adm.post("/api/auth-settings/ldap/test", json={"values": {**LDAP, "ca_file": "relatif/ca.pem"}, "secrets": {"bind_password": READER_PWD}}).json()
    assert r["ok"] is False and "chemin absolu" in r["detail"] and "relatif/ca.pem" not in r["detail"] and not adm.dir.binds
    r2 = adm.post("/api/auth-settings/ldap/test", json={"values": {**LDAP, "tls_server_name": "*"}, "secrets": {"bind_password": READER_PWD}}).json()
    assert r2["ok"] is False and "joker" in r2["detail"] and not adm.dir.binds


def test_the_unsaved_test_never_leaks_the_typed_secret(adm):
    blob = adm.post("/api/auth-settings/ldap/test", json={"values": LDAP, "secrets": {"bind_password": "mauvais-mot-de-passe-du-lecteur"}}).text
    assert "mauvais-mot-de-passe" not in blob and "mauvais-mot-de-passe" not in repr([(a.target, a.detail) for a in audit_rows()])


def test_the_tls_server_name_is_validated_and_saved_like_the_other_settings(adm):
    assert put(adm, "ldap", {**LDAP, "tls_server_name": "*"}, {"bind_password": READER_PWD}, confirm=True).status_code == 422
    assert put(adm, "ldap", {**LDAP, "tls_server_name": "ad test"}, {"bind_password": READER_PWD}, confirm=True).status_code == 422
    r = save_ldap(adm, tls_server_name="WIN-8FOU54ASDHT.homelab.local").json()
    assert r["values"]["tls_server_name"] == "WIN-8FOU54ASDHT.homelab.local"


def test_a_non_admin_cannot_use_the_unsaved_test_either(adm):
    adm.post("/api/kaji-users", json={"username": "paul", "password": PWD, "role": "operator"})
    b = TestClient(app)
    assert b.post("/api/auth/login", json={"username": "paul", "password": PWD}).status_code == 200
    assert b.post("/api/auth-settings/ldap/test", json={"values": LDAP}).status_code == 403


# ---------------------------------------------------------------- rotation de clé et sauvegarde
def test_the_rotation_reencrypts_the_stored_secrets_and_the_backup_check_reads_them(tmp_path):
    p = old_db(tmp_path)
    with session(p) as db:
        db.add(AuthSetting(provider="ldap", values_json="{}", secret_enc=crypto.encrypt(OLD, json.dumps({"bind_password": READER_PWD}))))
        db.add(AuthSetting(provider="oidc", values_json="{}", secret_enc=None))
        db.commit()
    good = backup.verify(Path(p), OLD)
    assert "Secrets SSO / annuaire : 1 ; déchiffrés : 1/1" in "\n".join(good.lines) and READER_PWD not in "\n".join(good.lines)
    bad = backup.verify(Path(p), NEW)
    assert any("SSO / annuaire illisible" in x for x in bad.problems)
    with session(p) as db:
        res = rotate_secret_key(db, NEW, OLD)
        assert res.auth == 1
        assert json.loads(crypto.decrypt(NEW, db.get(AuthSetting, "ldap").secret_enc)) == {"bind_password": READER_PWD}
        assert db.get(AuthSetting, "oidc").secret_enc is None
    assert not any("SSO / annuaire" in x for x in backup.verify(Path(p), NEW).problems)
