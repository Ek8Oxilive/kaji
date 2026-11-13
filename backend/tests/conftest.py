import os

os.environ.setdefault("KAJI_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("KAJI_COOKIE_SECURE", "false")
# Les tests ne doivent jamais dépendre du .env de la machine (il prime sur les valeurs par défaut) :
# toute variable de configuration utilisée par un test est fixée ici explicitement.
os.environ["KAJI_PROTECTED_VMIDS"] = ""
os.environ["KAJI_SESSION_HOURS"] = "12"
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
