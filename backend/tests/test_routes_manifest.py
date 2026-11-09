"""Garde-fou contre la perte accidentelle d'une fonction : TOUTE route de l'API connue est listée dans `routes_manifest.txt`, et le test échoue si l'une d'elles disparaît
(fusion ratée, conflit mal résolu, nettoyage trop large). Ajouter des routes ne demande rien ; en RETIRER une volontairement exige de régénérer le manifeste, donc de le faire exprès :

    KAJI_UPDATE_ROUTES=1 .venv/bin/pytest tests/test_routes_manifest.py

(la régénération n'écrit que les routes présentes : relire `git diff backend/tests/routes_manifest.txt` avant de commiter, chaque ligne retirée doit être justifiée).
"""
import os
from pathlib import Path

from app.main import app

MANIFEST = Path(__file__).with_name("routes_manifest.txt")


def current_routes() -> list[str]:
    """`MÉTHODE chemin` de toutes les routes, lues dans le schéma OpenAPI (FastAPI regroupe les routeurs inclus dans des objets internes)."""
    return sorted(f"{m.upper()} {path}" for path, item in app.openapi()["paths"].items() for m in item if m in ("get", "post", "put", "patch", "delete"))


def test_no_route_was_removed():
    if os.environ.get("KAJI_UPDATE_ROUTES"):
        MANIFEST.write_text("\n".join(current_routes()) + "\n", encoding="utf-8")
    expected = {line for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()}
    missing = sorted(expected - set(current_routes()))
    assert not missing, ("Des routes de l'API ont DISPARU (fonction perdue ?). Si c'est voulu, régénère le manifeste (voir l'en-tête de ce fichier) et justifie-le dans la PR :\n  "
                         + "\n  ".join(missing))


def test_the_manifest_is_not_empty_and_covers_the_main_features():
    expected = {line for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()}
    assert len(expected) > 250
    for must in ("POST /api/connections/{conn_id}/ha/resources", "POST /api/connections/{conn_id}/replication", "GET /api/connections/{conn_id}/cluster/config",
                 "PUT /api/connections/{conn_id}/datacenter/options", "POST /api/connections/{conn_id}/metrics/servers", "GET /api/connections/{conn_id}/notifications"):
        assert must in expected, must
