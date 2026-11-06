import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def secure_sqlite_file(url: str) -> None:
    """Le fichier SQLite contient le hash du mot de passe, les tokens chiffrés et l'audit : lisible par son seul propriétaire."""
    if not url.startswith("sqlite"):
        return
    path = make_url(url).database
    if not path or path == ":memory:":
        return
    f = Path(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch(mode=0o600, exist_ok=True)          # créé directement en 600 s'il n'existe pas
    os.chmod(f, 0o600)                           # et resserré s'il existait déjà en 644


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        secure_sqlite_file(url)
        kwargs = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool  # une seule connexion pour la base en mémoire
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    from . import models  # noqa: F401  (enregistre les tables)

    Base.metadata.create_all(get_engine())


def get_db() -> Iterator[Session]:
    get_engine()
    with _SessionLocal() as session:
        yield session
