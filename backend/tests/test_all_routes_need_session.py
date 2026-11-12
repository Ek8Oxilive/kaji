"""Garde de sécurité (V1) : TOUTE route de l'API, sauf une liste blanche, répond 401 sans session. Un nouveau routeur qui oublierait `current_user` fait échouer ce test."""
import re

import pytest

from app.main import app

# Routes publiques voulues : état de l'authentification, première configuration, connexion, déconnexion, santé (sonde du conteneur).
PUBLIC = {("GET", "/api/auth/status"), ("POST", "/api/auth/setup"), ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"), ("GET", "/api/health")}


def _routes():
    """`(MÉTHODE, chemin)` lus dans le schéma OpenAPI (même source que `test_routes_manifest.py` : FastAPI regroupe les routeurs inclus)."""
    return sorted((m.upper(), path) for path, item in app.openapi()["paths"].items() for m in item if m in ("get", "post", "put", "patch", "delete"))


def _fill(path: str) -> str:
    return re.sub(r"\{[^}:]+(:[^}]+)?\}", "1", path)


def test_the_route_list_is_not_empty():
    assert len(_routes()) > 300


@pytest.mark.parametrize("method,path", [r for r in _routes() if r not in PUBLIC])
def test_route_answers_401_without_a_session(client, method, path):
    r = client.request(method, _fill(path), json={} if method in ("POST", "PUT", "PATCH") else None)
    assert r.status_code == 401, f"{method} {path} répond {r.status_code} sans session"


def test_the_public_routes_are_exactly_the_expected_ones():
    existing = set(_routes())
    assert PUBLIC <= existing
