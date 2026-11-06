from app.security import create_session_token, decode_session_token, hash_password, verify_password

KEY = "cle-de-test-suffisamment-longue"


def test_password_hash_roundtrip():
    h = hash_password("secret-long-1234")
    assert h != "secret-long-1234"
    assert verify_password("secret-long-1234", h)
    assert not verify_password("autre", h)


def test_verify_without_hash_is_false():
    assert not verify_password("n-importe-quoi", None)


def test_session_token_roundtrip_and_wrong_key():
    t = create_session_token(KEY, 7, 1)
    assert decode_session_token(KEY, t) == 7
    assert decode_session_token("autre-cle-de-test-longue", t) is None


def test_expired_token_rejected():
    assert decode_session_token(KEY, create_session_token(KEY, 7, -1)) is None
