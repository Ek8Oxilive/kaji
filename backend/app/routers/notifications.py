"""Notifications (Datacenter → Notifications) : cibles et règles, en LECTURE SEULE (lot #151, étape 1). Mise en forme en liste blanche : `app/notificationspec.py`.

Droit Proxmox : `Mapping.Audit` (ou `Mapping.Modify`) sur `/mapping/notifications`. Aucun secret n'est renvoyé (mot de passe SMTP, jeton Gotify, valeurs des en-têtes et du corps d'un webhook).
L'écriture (ajouter, modifier, supprimer, tester une cible) vient à l'étape 2.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..notificationspec import TYPES, shape_endpoints, shape_field_values, shape_fields, shape_matchers, shape_targets
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/notifications", tags=["notifications"], dependencies=[Depends(current_user)])
BASE = "/cluster/notifications"


@router.get("/targets")
async def list_targets(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Toutes les cibles (tous types), avec leur origine : `builtin` (par défaut de Proxmox), `user-created` ou `modified-builtin`."""
    return shape_targets(await _px(db, factory, conn_id, "get", f"{BASE}/targets"))


@router.get("/endpoints")
async def list_all_endpoints(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Les cibles de chaque type avec leurs réglages. Un type que Proxmox ne sait pas lire (droits, version) est listé dans `unavailable` : les autres restent affichés."""
    out: dict[str, list] = {}
    unavailable: list[str] = []
    for t in TYPES:
        try:
            out[t] = shape_endpoints(await _px(db, factory, conn_id, "get", f"{BASE}/endpoints/{t}"), t)
        except HTTPException:
            out[t] = []
            unavailable.append(t)
    if len(unavailable) == len(TYPES):
        raise HTTPException(502, "Les cibles de notification sont illisibles (droit Mapping.Audit sur /mapping/notifications ?)")
    return {"endpoints": out, "unavailable": unavailable}


@router.get("/endpoints/{type}")
async def list_endpoints(conn_id: int, type: Literal["sendmail", "gotify", "smtp", "webhook"] = Path(), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory)):
    return shape_endpoints(await _px(db, factory, conn_id, "get", f"{BASE}/endpoints/{type}"), type)


@router.get("/matchers")
async def list_matchers(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Les règles : sur quoi elles portent (champ, gravité, calendrier) et vers quelles cibles elles envoient."""
    return shape_matchers(await _px(db, factory, conn_id, "get", f"{BASE}/matchers"))


@router.get("/matcher-fields")
async def list_matcher_fields(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_fields(await _px(db, factory, conn_id, "get", f"{BASE}/matcher-fields"))


@router.get("/matcher-field-values")
async def list_matcher_field_values(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_field_values(await _px(db, factory, conn_id, "get", f"{BASE}/matcher-field-values"))
