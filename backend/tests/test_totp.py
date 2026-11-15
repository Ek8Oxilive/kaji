"""Double authentification (TOTP) pour se connecter à Kaji (lot #444, jalon J2)."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crypto, security, totp
from app.config import get_settings
from app.db import get_engine
from app.main import app
from app.models import AuditLog, TotpRecoveryCode, UserTotp
from app.security import throttle

PWD = "un-mot-de-passe-solide"
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"                  # « 12345678901234567890 » en base32 (annexe B de la RFC 6238)


# ---------------------------------------------------------------- le calcul (vecteurs de la RFC 6238, tronqués à 6 chiffres)
@pytest.mark.parametrize("when,expected", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130")])
def test_codes_match_the_rfc_6238_test_vectors(when, expected):
    assert totp.code_at(RFC_SECRET, when // 30) == expected


def test_verify_accepts_one_step_either_side_but_not_two():
    step = 1000
    now = step * 30 + 5
    for delta, ok in [(-2, False), (-1, True), (0, True), (1, True), (2, False)]:
        assert (totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step + delta), now=now) is not None) is ok, delta


def test_verify_refuses_a_step_that_was_already_used():
    now = 1000 * 30
    code = totp.code_at(RFC_SECRET, 1000)
    assert totp.verify(RFC_SECRET, code, last_step=999, now=now) == 1000
    assert totp.verify(RFC_SECRET, code, last_step=1000, now=now) is None            # même pas, déjà pris
    assert totp.verify(RFC_SECRET, code, last_step=1001, now=now) is None            # plus ancien que le dernier accepté


@pytest.mark.parametrize("text", ["", "12345", "1234567", "abcdef", "12 34 5", "٠١٢٣٤٥", "123456\n7"])
def test_verify_refuses_malformed_codes(text):
    assert totp.verify(RFC_SECRET, text, now=59) is None


def test_spaces_and_hyphens_are_ignored():
    code = totp.code_at(RFC_SECRET, 1000)
    assert totp.verify(RFC_SECRET, f"{code[:3]} {code[3:]}", now=1000 * 30) == 1000
    assert totp.verify(RFC_SECRET, f"{code[:3]}-{code[3:]}", now=1000 * 30) == 1000


def test_generated_secrets_are_160_bits_base32_and_distinct():
    a, b = totp.generate_secret(), totp.generate_secret()
    assert a != b and re.fullmatch(r"[A-Z2-7]{32}", a)


def test_otpauth_uri_is_escaped():
    uri = totp.otpauth_uri("ABCDEFGHIJKLMNOP", "al ice&x=1")
    assert uri.startswith("otpauth://totp/Kaji:al%20ice%26x%3D1?secret=ABCDEFGHIJKLMNOP&issuer=Kaji") and "&x=1" not in uri.split("?")[0]


def test_recovery_codes_are_80_bits_distinct_and_hashed():
    codes = totp.new_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10 and all(re.fullmatch(r"[A-Z2-7]{4}(-[A-Z2-7]{4}){3}", c) for c in codes)
    c = codes[0]
    h = totp.recovery_hash(c)
    assert h == totp.recovery_hash(c.lower().replace("-", ""))                                  # casse et tirets ignorés
    assert re.fullmatch(r"[0-9a-f]{64}", h) and c.replace("-", "") not in h and totp.recovery_hash(codes[1]) != h


# ---------------------------------------------------------------- l'API
@pytest.fixture
def clock(monkeypatch):
    """Horloge TOTP pilotable : on avance d'un pas pour obtenir un code neuf sans attendre 30 secondes."""
    state = {"step": 5_000_000}
    monkeypatch.setattr(totp, "current_step", lambda now=None: state["step"] if now is None else int(now // totp.STEP))
    return state


@pytest.fixture
def admin(client, clock):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    return client


def login(name="admin", pwd=PWD):
    c = TestClient(app)
    return c, c.post("/api/auth/login", json={"username": name, "password": pwd})


def enroll(c, clock, pwd=PWD):
    """Active le TOTP du compte connecté dans `c` ; renvoie (secret, codes de secours). Laisse l'horloge un pas plus loin que le code de confirmation."""
    r = c.post("/api/auth/totp/setup", json={"password": pwd})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = c.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, clock["step"])})
    assert r.status_code == 200, r.text
    clock["step"] += 1
    return secret, r.json()["recovery_codes"]


def code(secret, clock):
    return totp.code_at(secret, clock["step"])


def two_steps(secret, clock, pwd=PWD, name="admin", c2=None):
    c, r = login(name, pwd)
    assert r.status_code == 200 and r.json()["totp_required"] is True
    return c, r.json()["challenge"]


def test_enrollment_flow_and_pending_state_is_not_enforced(admin, clock):
    assert admin.get("/api/auth/totp").json() == {"enabled": False, "pending": False, "recovery_remaining": 0}
    r = admin.post("/api/auth/totp/setup", json={"password": PWD})
    secret = r.json()["secret"]
    assert re.fullmatch(r"[A-Z2-7]{32}", secret) and r.json()["uri"].startswith("otpauth://totp/Kaji:admin?secret=" + secret)
    assert admin.get("/api/auth/totp").json() == {"enabled": False, "pending": True, "recovery_remaining": 0}
    _, r2 = login()
    assert r2.status_code == 200 and "totp_required" not in r2.json() and "kaji_session" in r2.cookies                 # en attente : pas encore exigé
    assert admin.post("/api/auth/totp/confirm", json={"code": "000000"}).status_code == 401
    ok = admin.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, clock["step"])})
    assert ok.status_code == 200 and ok.json()["enabled"] is True and len(ok.json()["recovery_codes"]) == 10
    assert admin.get("/api/auth/totp").json() == {"enabled": True, "pending": False, "recovery_remaining": 10}


def test_setup_needs_the_password_and_refuses_when_already_enabled(admin, clock):
    assert admin.post("/api/auth/totp/setup", json={"password": "mauvais-mot-de-passe"}).status_code == 401
    enroll(admin, clock)
    assert admin.post("/api/auth/totp/setup", json={"password": PWD}).status_code == 409


def test_confirm_without_setup_is_refused(admin):
    assert admin.post("/api/auth/totp/confirm", json={"code": "123456"}).status_code == 409


def test_with_totp_the_password_alone_opens_no_session(admin, clock):
    enroll(admin, clock)
    c, r = login()
    assert r.status_code == 200 and r.json()["totp_required"] is True and r.json()["challenge"]
    assert "kaji_session" not in r.cookies and c.get("/api/auth/me").status_code == 401
    assert "username" not in r.json()


def test_second_step_opens_the_session_with_a_valid_code(admin, clock):
    secret, _ = enroll(admin, clock)
    c, challenge = two_steps(secret, clock)
    r = c.post("/api/auth/login/totp", json={"challenge": challenge, "code": code(secret, clock)})
    assert r.status_code == 200 and r.json() == {"username": "admin"} and c.get("/api/auth/me").json()["username"] == "admin"


def test_a_wrong_code_opens_nothing_and_is_audited_without_the_code(admin, clock):
    secret, _ = enroll(admin, clock)
    c, challenge = two_steps(secret, clock)
    r = c.post("/api/auth/login/totp", json={"challenge": challenge, "code": "000000"})
    assert r.status_code == 401 and "kaji_session" not in r.cookies and c.get("/api/auth/me").status_code == 401
    with Session(get_engine()) as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.action == "login-totp")).all()
    assert len(rows) == 1 and rows[0].status == "error" and "000000" not in (rows[0].detail or "")


def test_a_code_cannot_be_used_twice(admin, clock):
    secret, _ = enroll(admin, clock)
    c1, ch1 = two_steps(secret, clock)
    used = code(secret, clock)
    assert c1.post("/api/auth/login/totp", json={"challenge": ch1, "code": used}).status_code == 200
    c2, ch2 = two_steps(secret, clock)
    assert c2.post("/api/auth/login/totp", json={"challenge": ch2, "code": used}).status_code == 401           # rejeu : même code, même pas
    clock["step"] += 1
    assert c2.post("/api/auth/login/totp", json={"challenge": ch2, "code": code(secret, clock)}).status_code == 200


def test_the_confirmation_code_cannot_be_replayed_to_log_in(admin, clock):
    r = admin.post("/api/auth/totp/setup", json={"password": PWD})
    secret = r.json()["secret"]
    used = totp.code_at(secret, clock["step"])
    admin.post("/api/auth/totp/confirm", json={"code": used})
    c, ch = two_steps(secret, clock)
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": used}).status_code == 401


@pytest.mark.parametrize("challenge", ["x" * 20, "aaaa.bbbb.cccc", "e30.e30.e30"])
def test_garbage_challenges_are_refused(admin, clock, challenge):
    enroll(admin, clock)
    assert TestClient(app).post("/api/auth/login/totp", json={"challenge": challenge, "code": "123456"}).status_code == 401


def test_an_expired_challenge_is_refused(admin, clock, monkeypatch):
    secret, _ = enroll(admin, clock)
    monkeypatch.setattr(security, "CHALLENGE_SECONDS", -10)
    c, ch = two_steps(secret, clock)
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": code(secret, clock)}).status_code == 401


def test_a_session_cookie_is_not_a_challenge_and_a_challenge_is_not_a_session(admin, clock):
    secret, _ = enroll(admin, clock)
    session_token = admin.cookies.get("kaji_session")
    assert TestClient(app).post("/api/auth/login/totp", json={"challenge": session_token, "code": code(secret, clock)}).status_code == 401
    c, ch = two_steps(secret, clock)
    forged = TestClient(app)
    forged.cookies.set("kaji_session", ch)
    assert forged.get("/api/auth/me").status_code == 401


def test_changing_the_password_invalidates_pending_challenges(admin, clock):
    secret, _ = enroll(admin, clock)
    c, ch = two_steps(secret, clock)
    assert admin.post("/api/auth/password", json={"current_password": PWD, "new_password": "un-autre-mot-de-passe-solide"}).status_code == 200
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": code(secret, clock)}).status_code == 401


def test_a_challenge_never_works_with_another_accounts_code(admin, clock):
    secret_a, _ = enroll(admin, clock)
    admin.post("/api/kaji-users", json={"username": "bob", "password": PWD, "role": "viewer"})
    cb, _r = login("bob")
    secret_b, _ = enroll(cb, clock)
    c, ch = two_steps(secret_a, clock)                                                    # défi du compte admin
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": code(secret_b, clock)}).status_code == 401


def test_five_wrong_codes_block_the_address_then_even_the_right_code_is_refused(admin, clock):
    secret, _ = enroll(admin, clock)
    c, ch = two_steps(secret, clock)
    for _ in range(5):
        assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": "000000"}).status_code == 401
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": code(secret, clock)}).status_code == 429
    throttle.reset()
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": code(secret, clock)}).status_code == 200


def test_the_account_is_blocked_independently_of_the_address(admin, clock):
    secret, _ = enroll(admin, clock)
    with Session(get_engine()) as db:
        uid = db.scalar(select(UserTotp.user_id))
    c, ch = two_steps(secret, clock)
    for _ in range(5):
        throttle.fail(f"totp:{uid}")                                                      # d'autres adresses ont essayé : l'adresse de ce client est propre
    assert not throttle.blocked("testclient")
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": code(secret, clock)}).status_code == 429


def test_a_good_second_step_clears_the_failure_counters(admin, clock):
    secret, _ = enroll(admin, clock)
    c, ch = two_steps(secret, clock)
    for _ in range(3):
        c.post("/api/auth/login/totp", json={"challenge": ch, "code": "000000"})
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": code(secret, clock)}).status_code == 200
    assert not throttle.blocked("testclient")


def test_recovery_codes_work_once_whatever_their_spelling(admin, clock):
    secret, codes = enroll(admin, clock)
    c1, ch1 = two_steps(secret, clock)
    r = c1.post("/api/auth/login/totp", json={"challenge": ch1, "code": codes[0].lower().replace("-", " ")})
    assert r.status_code == 200
    c2, ch2 = two_steps(secret, clock)
    assert c2.post("/api/auth/login/totp", json={"challenge": ch2, "code": codes[0]}).status_code == 401           # déjà utilisé
    assert c1.get("/api/auth/totp").json()["recovery_remaining"] == 9
    with Session(get_engine()) as db:
        used = db.scalars(select(AuditLog).where(AuditLog.action == "totp-recovery-used")).all()
    assert len(used) == 1 and "9 code(s)" in used[0].detail and codes[0] not in used[0].detail


def test_an_unknown_recovery_code_is_refused(admin, clock):
    secret, _ = enroll(admin, clock)
    c, ch = two_steps(secret, clock)
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": "AAAA-BBBB-CCCC-DDDD"}).status_code == 401


def test_new_recovery_codes_need_the_password_and_an_app_code_and_replace_the_old(admin, clock):
    secret, old = enroll(admin, clock)
    assert admin.post("/api/auth/totp/recovery", json={"password": "mauvais-mot-de-passe", "code": code(secret, clock)}).status_code == 401
    assert admin.post("/api/auth/totp/recovery", json={"password": PWD, "code": old[0]}).status_code == 401           # un code de secours ne suffit pas ici
    r = admin.post("/api/auth/totp/recovery", json={"password": PWD, "code": code(secret, clock)})
    new = r.json()["recovery_codes"]
    assert r.status_code == 200 and len(new) == 10 and not set(new) & set(old)
    c, ch = two_steps(secret, clock)
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": old[1]}).status_code == 401
    clock["step"] += 1
    c2, ch2 = two_steps(secret, clock)
    assert c2.post("/api/auth/login/totp", json={"challenge": ch2, "code": new[0]}).status_code == 200


def test_disable_needs_the_password_and_a_code_and_restores_the_plain_login(admin, clock):
    secret, codes = enroll(admin, clock)
    assert admin.post("/api/auth/totp/disable", json={"password": "mauvais-mot-de-passe", "code": code(secret, clock)}).status_code == 401
    assert admin.post("/api/auth/totp/disable", json={"password": PWD, "code": "000000"}).status_code == 401
    assert admin.get("/api/auth/totp").json()["enabled"] is True
    assert admin.post("/api/auth/totp/disable", json={"password": PWD, "code": codes[0]}).json() == {"enabled": False}          # un code de secours suffit pour désactiver
    _, r = login()
    assert r.status_code == 200 and "totp_required" not in r.json()
    with Session(get_engine()) as db:
        assert db.scalars(select(UserTotp)).all() == [] and db.scalars(select(TotpRecoveryCode)).all() == []


def test_disable_and_recovery_refuse_when_not_enabled(admin):
    assert admin.post("/api/auth/totp/disable", json={"password": PWD, "code": "123456"}).status_code == 409
    assert admin.post("/api/auth/totp/recovery", json={"password": PWD, "code": "123456"}).status_code == 409


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/auth/totp", None), ("POST", "/api/auth/totp/setup", {"password": PWD}), ("POST", "/api/auth/totp/confirm", {"code": "123456"}),
    ("POST", "/api/auth/totp/recovery", {"password": PWD, "code": "123456"}), ("POST", "/api/auth/totp/disable", {"password": PWD, "code": "123456"}),
])
def test_self_service_routes_need_a_session(client, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize("body", [{"challenge": "x" * 20, "code": ""}, {"challenge": "x" * 20, "code": "12"}, {"challenge": "short", "code": "123456"}, {"code": "123456"}])
def test_the_second_step_validates_its_input(client, body):
    assert client.post("/api/auth/login/totp", json=body).status_code == 422


def test_every_role_can_protect_its_own_account(admin, clock):
    admin.post("/api/kaji-users", json={"username": "viewer1", "password": PWD, "role": "viewer"})
    c, _r = login("viewer1")
    secret, codes = enroll(c, clock)
    assert len(codes) == 10 and c.get("/api/auth/totp").json()["enabled"] is True


def test_the_secret_is_encrypted_at_rest_and_codes_are_only_stored_hashed(admin, clock):
    secret, codes = enroll(admin, clock)
    with Session(get_engine()) as db:
        row = db.scalar(select(UserTotp))
        hashes = [r.code_hash for r in db.scalars(select(TotpRecoveryCode))]
    assert secret not in row.secret_enc and crypto.decrypt(get_settings().kaji_secret_key, row.secret_enc) == secret
    assert len(hashes) == 10 and not any(c.replace("-", "") in h or c in h for c in codes for h in hashes)


def test_no_secret_or_code_ever_reaches_the_audit_or_the_status(admin, clock):
    secret, codes = enroll(admin, clock)
    c, ch = two_steps(secret, clock)
    c.post("/api/auth/login/totp", json={"challenge": ch, "code": codes[0]})
    admin.post("/api/auth/totp/disable", json={"password": PWD, "code": codes[1]})
    with Session(get_engine()) as db:
        text = " ".join(f"{a.action} {a.target} {a.detail}" for a in db.scalars(select(AuditLog)))
    for needle in [secret, *codes, *(x.replace("-", "") for x in codes), PWD, ch]:
        assert needle not in text
    assert secret not in admin.get("/api/auth/totp").text


# ---------------------------------------------------------------- l'administrateur
def _two_users(admin, clock):
    admin.post("/api/kaji-users", json={"username": "alice", "password": PWD, "role": "operator"})
    ca, _r = login("alice")
    secret, codes = enroll(ca, clock)
    uid = next(u["id"] for u in admin.get("/api/kaji-users").json() if u["username"] == "alice")
    return ca, secret, codes, uid


def test_the_list_tells_who_has_the_second_factor(admin, clock):
    _two_users(admin, clock)
    assert {u["username"]: u["totp"] for u in admin.get("/api/kaji-users").json()} == {"admin": False, "alice": True}


def test_an_administrator_removes_another_accounts_totp_and_its_sessions(admin, clock):
    ca, _secret, _codes, uid = _two_users(admin, clock)
    assert admin.delete(f"/api/kaji-users/{uid}/totp").status_code == 400                                           # sans confirmation
    assert admin.delete(f"/api/kaji-users/{uid}/totp?confirm=true&name=bob").status_code == 400                     # mauvais nom
    r = admin.delete(f"/api/kaji-users/{uid}/totp?confirm=true&name=alice")
    assert r.status_code == 200 and r.json() == {"removed": "alice"}
    assert ca.get("/api/auth/me").status_code == 401                                                                 # ses sessions sont révoquées
    _, r2 = login("alice")
    assert r2.status_code == 200 and "totp_required" not in r2.json()
    with Session(get_engine()) as db:
        a = db.scalars(select(AuditLog).where(AuditLog.action == "kaji-user-totp-remove", AuditLog.status == "started")).all()
    assert len(a) == 1 and a[0].username == "admin" and a[0].target == "alice"


def test_an_administrator_cannot_remove_their_own_second_factor_this_way(admin, clock):
    secret, _ = enroll(admin, clock)
    me = next(u["id"] for u in admin.get("/api/kaji-users").json() if u["username"] == "admin")
    assert admin.delete(f"/api/kaji-users/{me}/totp?confirm=true&name=admin").status_code == 409
    assert admin.get("/api/auth/totp").json()["enabled"] is True


def test_removing_a_totp_that_does_not_exist_is_refused(admin, clock):
    admin.post("/api/kaji-users", json={"username": "carol", "password": PWD, "role": "viewer"})
    uid = next(u["id"] for u in admin.get("/api/kaji-users").json() if u["username"] == "carol")
    assert admin.delete(f"/api/kaji-users/{uid}/totp?confirm=true&name=carol").status_code == 409
    assert admin.delete("/api/kaji-users/9999/totp?confirm=true&name=x").status_code == 404


def test_only_administrators_remove_a_second_factor(admin, clock):
    ca, _secret, _codes, uid = _two_users(admin, clock)
    admin.post("/api/kaji-users", json={"username": "dave", "password": PWD, "role": "operator"})
    cd, _r = login("dave")
    assert cd.delete(f"/api/kaji-users/{uid}/totp?confirm=true&name=alice").status_code == 403


def test_deleting_a_user_deletes_their_second_factor(admin, clock):
    _ca, _secret, _codes, uid = _two_users(admin, clock)
    assert admin.delete(f"/api/kaji-users/{uid}?confirm=true&name=alice").status_code == 200
    with Session(get_engine()) as db:
        assert db.get(UserTotp, uid) is None and db.scalars(select(TotpRecoveryCode).where(TotpRecoveryCode.user_id == uid)).all() == []


def test_a_missing_user_after_a_valid_challenge_is_refused(admin, clock):
    ca, secret, _codes, uid = _two_users(admin, clock)
    c, ch = two_steps(secret, clock, name="alice")
    admin.delete(f"/api/kaji-users/{uid}?confirm=true&name=alice")
    assert c.post("/api/auth/login/totp", json={"challenge": ch, "code": code(secret, clock)}).status_code == 401


# ---------------------------------------------------------------- garde-fous de bas niveau (ce que l'API ne laisse pas atteindre)
def _store(db, name="zoe"):
    from app import totpstore
    from app.models import AdminUser
    u = AdminUser(username=name, password_hash="x", role="viewer")
    db.add(u)
    db.commit()
    return totpstore, u.id


def test_two_simultaneous_requests_with_the_same_code_cannot_both_pass(client, monkeypatch):
    """Les deux requêtes ont vérifié le code AVANT que l'une n'enregistre le pas : seul l'UPDATE conditionnel les départage."""
    key = get_settings().kaji_secret_key
    with Session(get_engine()) as db:
        store, uid = _store(db)
        secret = store.start_enrollment(db, key, uid)
        store.confirm_enrollment(db, key, uid, totp.code_at(secret, 5000), now=5000 * 30)
        db.get(UserTotp, uid).last_step = 0
        db.commit()
        monkeypatch.setattr(totp, "verify", lambda *a, **k: 5001)                    # les deux « voient » le code comme valide
        assert store.check(db, key, uid, "123456") == "totp"
        assert store.check(db, key, uid, "123456") is None                           # le pas 5001 est pris : rejeu


def test_a_pending_enrollment_never_authenticates(client):
    key = get_settings().kaji_secret_key
    with Session(get_engine()) as db:
        store, uid = _store(db)
        secret = store.start_enrollment(db, key, uid)
        assert store.check(db, key, uid, totp.code_at(secret, totp.current_step())) is None
        assert not store.is_enabled(db, uid) and store.enabled_ids(db) == set()


def test_an_enrollment_cannot_be_confirmed_twice(client):
    key = get_settings().kaji_secret_key
    with Session(get_engine()) as db:
        store, uid = _store(db)
        secret = store.start_enrollment(db, key, uid)
        first = store.confirm_enrollment(db, key, uid, totp.code_at(secret, 6000), now=6000 * 30)
        assert first and len(first) == 10
        assert store.confirm_enrollment(db, key, uid, totp.code_at(secret, 6001), now=6001 * 30) is None
        assert store.remaining_recovery(db, uid) == 10                              # les codes de secours n'ont pas été remplacés par une seconde confirmation


def test_confirming_without_any_enrollment_returns_nothing(client):
    with Session(get_engine()) as db:
        store, uid = _store(db)
        assert store.confirm_enrollment(db, get_settings().kaji_secret_key, uid, "123456") is None


def _challenge_claims(**over):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    claims = {"sub": "1", "purpose": "totp", "pwf": security._fingerprint("hash"), "iat": now, "exp": now + timedelta(minutes=5)}
    claims.update(over)
    return claims


def test_a_challenge_signed_with_the_session_key_is_refused():
    import jwt
    key = get_settings().kaji_secret_key
    forged = jwt.encode(_challenge_claims(), security._signing_key(key), algorithm="HS256")        # signé avec la clé des SESSIONS
    assert security.decode_totp_challenge(key, forged) is None
    good = jwt.encode(_challenge_claims(), security._challenge_key(key), algorithm="HS256")
    assert security.decode_totp_challenge(key, good) == (1, security._fingerprint("hash"))


def test_a_token_with_another_purpose_or_no_fingerprint_is_not_a_challenge():
    import jwt
    key = get_settings().kaji_secret_key
    for claims in (_challenge_claims(purpose="session"), {k: v for k, v in _challenge_claims().items() if k != "purpose"}, {k: v for k, v in _challenge_claims().items() if k != "pwf"}):
        assert security.decode_totp_challenge(key, jwt.encode(claims, security._challenge_key(key), algorithm="HS256")) is None


def test_a_challenge_lives_five_minutes():
    import jwt
    token = security.create_totp_challenge(get_settings().kaji_secret_key, 1, "hash")
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 300 and claims["purpose"] == "totp"
