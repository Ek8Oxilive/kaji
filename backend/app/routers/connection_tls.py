"""Épinglage du certificat d'une connexion Proxmox (V1) : voir le certificat présenté, l'épingler, retirer l'épingle. Règles et justification : `app/tlspin.py`.

Aucune écriture ne part sans `confirm=true` ET l'empreinte que l'utilisateur a vue : le serveur relit le certificat au moment d'épingler et refuse s'il a changé entre-temps.
Seul le certificat public est stocké ; l'audit (`tls-pin`, `tls-unpin`) ne contient que l'empreinte.
"""
import asyncio
import ssl

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import AdminUser, Connection
from ..tlspin import FINGERPRINT, describe, fetch_der, pem_of_der
from .auth import current_user
from .cluster import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}/tls", tags=["connections-tls"], dependencies=[Depends(current_user)])


class PinBody(BaseModel):
    fingerprint: str = Field(pattern=FINGERPRINT.pattern, description="Empreinte SHA-256 affichée, en majuscules, séparée par des deux-points")
    confirm: StrictBool = False


async def _present(c: Connection) -> tuple[bytes, dict] | None:
    """Le certificat que le serveur présente maintenant, ou `None` s'il est injoignable ou présente autre chose qu'un certificat lisible."""
    try:
        der = await asyncio.to_thread(fetch_der, c.host, c.port)
        return der, describe(der)
    except (OSError, ssl.SSLError, ValueError):
        return None


def _view(c: Connection, shown: dict | None) -> dict:
    pinned = c.tls_fingerprint
    out = {"reachable": shown is not None, "pinned": c.tls_pinned, "pinned_fingerprint": pinned, "verify_ssl": c.verify_ssl}
    if shown is not None:
        out.update(shown)
        out["matches"] = (shown["fingerprint"] == pinned) if c.tls_pinned else None
    return out


@router.get("")
async def tls_status(conn_id: int, db: Session = Depends(get_db)):
    """Certificat présenté par le serveur (empreinte, sujet, émetteur, validité) et état de l'épinglage. Lecture seule."""
    c = _get_or_404(db, conn_id)
    got = await _present(c)
    return _view(c, got[1] if got else None)


@router.put("")
async def pin(body: PinBody, conn_id: int, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    """Épingle le certificat que le serveur présente, si son empreinte est celle que l'utilisateur a vue et confirmée."""
    c = _get_or_404(db, conn_id)

    def log(st: str, detail: str | None = None):
        audit.record(db, username=user.username, connection_id=c.id, action="tls-pin", target=f"connexion/{c.name}", status=st, detail=detail)

    if not body.confirm:
        log("error", "confirmation absente")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirmation requise (renvoie la requête avec confirm=true) : après avoir comparé l'empreinte à celle de ton nœud")
    got = await _present(c)
    if got is None:
        log("error", "serveur injoignable")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Proxmox injoignable : impossible de lire son certificat")
    der, shown = got
    if shown["fingerprint"] != body.fingerprint:
        log("error", "le certificat présenté n'est plus celui qui a été vu")
        raise HTTPException(status.HTTP_409_CONFLICT, "Le certificat présenté n'est plus celui que tu as vu : relis son empreinte avant de l'épingler")
    c.tls_cert_pem = pem_of_der(der)
    db.commit()
    log("started", f"empreinte {shown['fingerprint']}")
    return _view(c, shown)


@router.delete("")
async def unpin(conn_id: int, confirm: bool = Query(default=False), db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    """Retire l'épingle : la connexion retrouve la vérification d'avant (`verify_ssl`, souvent « aucune »). Confirmation exigée."""
    c = _get_or_404(db, conn_id)
    if not confirm:
        audit.record(db, username=user.username, connection_id=c.id, action="tls-unpin", target=f"connexion/{c.name}", status="error", detail="confirmation absente")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirmation requise (renvoie la requête avec confirm=true) : sans épingle, le certificat de Proxmox n'est plus vérifié comme avant")
    if not c.tls_pinned:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aucun certificat n'est épinglé pour cette connexion")
    c.tls_cert_pem = None
    db.commit()
    audit.record(db, username=user.username, connection_id=c.id, action="tls-unpin", target=f"connexion/{c.name}", status="started", detail="épingle retirée")
    return _view(c, None)
