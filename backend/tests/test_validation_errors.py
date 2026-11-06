"""Les erreurs de validation ne doivent jamais renvoyer les valeurs saisies (mots de passe, secrets de token)."""
PWD = "un-mot-de-passe-solide"


def test_missing_field_does_not_echo_the_body(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    r = client.post("/api/connections", json={"host": "10.0.0.1", "user": "a@b", "token_id": "t", "token_secret": "SECRET-A-NE-PAS-REVELER"})
    assert r.status_code == 422 and "SECRET-A-NE-PAS-REVELER" not in r.text
    assert "input" not in r.text and r.json()["detail"][0]["loc"] == ["body", "name"]


def test_invalid_value_does_not_echo_the_value(client):
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    r = client.post("/api/connections", json={"name": "x", "host": "https://mauvais", "user": "a@b", "token_id": "t", "token_secret": "SECRET-A-NE-PAS-REVELER"})
    assert r.status_code == 422 and "SECRET-A-NE-PAS-REVELER" not in r.text and "mauvais" not in r.text


def test_setup_and_login_do_not_echo_passwords(client):
    r = client.post("/api/auth/setup", json={"username": "admin", "password": "COURT"})
    assert r.status_code == 422 and "COURT" not in r.text
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    r = client.post("/api/auth/login", json={"username": 12345, "password": "MOT-DE-PASSE-SECRET"})
    assert r.status_code == 422 and "MOT-DE-PASSE-SECRET" not in r.text


def test_error_format_stays_usable_by_the_interface(client):
    r = client.post("/api/auth/setup", json={"username": "ab", "password": PWD})
    d = r.json()["detail"]
    assert r.status_code == 422 and isinstance(d, list) and all({"loc", "msg", "type"} <= set(e) for e in d) and d[0]["msg"]
