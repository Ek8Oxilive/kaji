import pytest

from app.crypto import decrypt, encrypt

KEY = "une-cle-de-test-suffisamment-longue"


def test_roundtrip():
    assert decrypt(KEY, encrypt(KEY, "secret-token")) == "secret-token"


def test_ciphertext_is_not_plaintext():
    assert "secret-token" not in encrypt(KEY, "secret-token")


def test_wrong_key_fails():
    with pytest.raises(ValueError):
        decrypt("autre-cle-de-test-longue", encrypt(KEY, "x"))


def test_default_key_rejected():
    with pytest.raises(ValueError):
        encrypt("changeme", "x")
