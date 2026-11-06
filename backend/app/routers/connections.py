import re
from collections.abc import Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..db import get_db
from ..deps import get_client_factory
from ..models import Connection
from ..proxmox import ProxmoxClient
from .auth import current_user

router = APIRouter(prefix="/api/connections", tags=["connections"], dependencies=[Depends(current_user)])

_HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$|^[0-9A-Fa-f:]+$")


class ConnectionBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=255, description="IP ou nom d'hôte, sans https:// ni chemin")
    port: int = Field(default=8006, ge=1, le=65535)
    user: str = Field(min_length=3, max_length=100, description="ex. kaji@pve")
    token_id: str = Field(min_length=1, max_length=100)
    verify_ssl: bool = False

    @field_validator("host")
    @classmethod
    def _valid_host(cls, v: str) -> str:
        v = v.strip()
        if not _HOST.match(v):
            raise ValueError("Hôte invalide : indique seulement une IP ou un nom d'hôte")
        return v

    @field_validator("user")
    @classmethod
    def _valid_user(cls, v: str) -> str:
        if "@" not in v or "!" in v:
            raise ValueError("Utilisateur au format user@realm (sans le token)")
        return v


class ConnectionCreate(ConnectionBase):
    token_secret: str = Field(min_length=1, max_length=200)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = None
    token_id: str | None = None
    token_secret: str | None = Field(default=None, min_length=1, max_length=200)
    verify_ssl: bool | None = None


class ConnectionOut(BaseModel):
    """Jamais de token dans les réponses."""

    model_config = {"from_attributes": True}
    id: int
    name: str
    host: str
    port: int
    user: str
    token_id: str
    verify_ssl: bool


Factory = Callable[..., ProxmoxClient]


async def probe(factory: Factory, **params) -> dict:
    client = factory(**params)
    try:
        v = await client.get("/version")
        return {"ok": True, "version": v.get("version"), "release": v.get("release")}
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        msg = "Utilisateur ou token refusé" if code == 401 else f"Proxmox a répondu {code}"
        return {"ok": False, "error": msg}
    except httpx.TimeoutException:
        return {"ok": False, "error": "Délai dépassé : hôte injoignable ?"}
    except httpx.ConnectError as e:
        hint = " (certificat auto-signé ? désactive la vérification SSL)" if "CERTIFICATE" in str(e).upper() else ""
        return {"ok": False, "error": f"Connexion impossible{hint}"}
    except (httpx.HTTPError, KeyError, ValueError):
        return {"ok": False, "error": "Réponse inattendue du serveur"}
    finally:
        await client.aclose()


def _params(c: Connection) -> dict:
    return dict(host=c.host, port=c.port, user=c.user, token_id=c.token_id,
                token_secret=decrypt(get_settings().kaji_secret_key, c.token_secret_enc),
                verify_ssl=c.verify_ssl)


def _get_or_404(db: Session, conn_id: int) -> Connection:
    c = db.get(Connection, conn_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connexion introuvable")
    return c


@router.get("", response_model=list[ConnectionOut])
def list_connections(db: Session = Depends(get_db)):
    return db.scalars(select(Connection).order_by(Connection.name)).all()


@router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
def create_connection(body: ConnectionCreate, db: Session = Depends(get_db)):
    data = body.model_dump(exclude={"token_secret"})
    c = Connection(**data, token_secret_enc=encrypt(get_settings().kaji_secret_key, body.token_secret))
    db.add(c)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce nom de connexion existe déjà")
    return c


@router.post("/test")
async def test_unsaved(body: ConnectionCreate, factory: Factory = Depends(get_client_factory)):
    """Teste des identifiants avant de les enregistrer."""
    return await probe(factory, **body.model_dump(exclude={"name"}))


@router.get("/{conn_id}", response_model=ConnectionOut)
def get_connection(conn_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, conn_id)


@router.patch("/{conn_id}", response_model=ConnectionOut)
def update_connection(conn_id: int, body: ConnectionUpdate, db: Session = Depends(get_db)):
    c = _get_or_404(db, conn_id)
    changes = body.model_dump(exclude_unset=True)
    if "token_secret" in changes:
        c.token_secret_enc = encrypt(get_settings().kaji_secret_key, changes.pop("token_secret"))
    merged = ConnectionBase(**{**ConnectionOut.model_validate(c).model_dump(exclude={"id"}), **changes})
    for k, v in merged.model_dump().items():
        setattr(c, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce nom de connexion existe déjà")
    return c


@router.delete("/{conn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(conn_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, conn_id))
    db.commit()


@router.post("/{conn_id}/test")
async def test_saved(conn_id: int, db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory)):
    return await probe(factory, **_params(_get_or_404(db, conn_id)))
