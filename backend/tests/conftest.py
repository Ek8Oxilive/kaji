import os

os.environ.setdefault("KAJI_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("KAJI_COOKIE_SECURE", "false")

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
