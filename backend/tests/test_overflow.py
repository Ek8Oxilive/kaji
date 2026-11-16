"""Un entier hors limites dans une adresse est une erreur 422 claire, pas un 500 (sonde de sécurité du jalon J3)."""
import pytest

PWD = "un-mot-de-passe-solide"
HUGE = "9" * 25


@pytest.fixture
def logged(client):
    assert client.post("/api/auth/setup", json={"username": "admin", "password": PWD}).status_code == 201
    return client


@pytest.mark.parametrize("path", [f"/api/connections/{HUGE}", f"/api/connections/{HUGE}/nodes", f"/api/connections/{HUGE}/access/users"])
def test_huge_id_is_422_not_500(logged, path):
    r = logged.get(path)
    assert r.status_code in (404, 422), r.text
    assert "Traceback" not in r.text


def test_huge_id_message_has_no_internals(logged):
    r = logged.get(f"/api/connections/{HUGE}")
    assert r.status_code in (404, 422)
    assert "sqlite" not in r.text.lower() and "overflow" not in r.text.lower()


def test_normal_unknown_id_still_404(logged):
    assert logged.get("/api/connections/424242").status_code == 404
