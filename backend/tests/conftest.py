import os

os.environ.setdefault("KAJI_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("KAJI_COOKIE_SECURE", "false")
# Les tests ne doivent jamais dépendre du .env de la machine (il prime sur les valeurs par défaut) :
# toute variable de configuration utilisée par un test est fixée ici explicitement.
os.environ["KAJI_PROTECTED_VMIDS"] = ""
os.environ["KAJI_SESSION_HOURS"] = "12"
os.environ["KAJI_TOKEN_CREATE_MAX_DAYS"] = "365"          # expiration des jetons créés par l'administrateur : imposée (lot #442)
os.environ["KAJI_SCHEDULER"] = "false"          # la boucle du planificateur ne tourne jamais pendant les tests (`run_due` est testé directement)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import throttle  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        Base.metadata.drop_all(get_engine())
        Base.metadata.create_all(get_engine())
        throttle.reset()
        yield c


class _AuditSansConnexions:
    """Pendant les tests, les lignes `connection-*` (la mise en place d'une connexion par l'API) ne sont pas écrites : tant de tests créent une
    connexion puis comparent l'audit à une liste exacte de l'action testée. Un test qui veut les voir porte `@pytest.mark.connection_audit`."""
    def __init__(self, real):
        self._real = real

    def record(self, db, **kw):
        if str(kw.get("action", "")).startswith("connection-"):
            return None
        return self._real.record(db, **kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture(autouse=True)
def _connexions_hors_audit(request, monkeypatch):
    if request.node.get_closest_marker("connection_audit"):
        return
    from app.routers import connections
    monkeypatch.setattr(connections, "audit", _AuditSansConnexions(connections.audit))
