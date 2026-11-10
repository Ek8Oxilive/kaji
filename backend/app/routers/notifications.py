"""Notifications (Datacenter → Notifications) en LECTURE SEULE : cibles, points de terminaison par type, règles, champs. Mise en forme et secrets : `app/notificationspec.py`.

Droit Proxmox : `Mapping.Audit` sur `/mapping/notifications`. Une sous-requête qui échoue (droit manquant, type absent) n'empêche pas les autres : son message court est dans `errors`.
"""
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..metricsspec import digest_of
from ..notificationspec import NAME, TARGET_TYPES, shape_endpoint, shape_field_values, shape_fields, shape_matchers, shape_targets
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/notifications", tags=["notifications"], dependencies=[Depends(current_user)])
BASE = "/cluster/notifications"


@router.get("")
async def notifications(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Cibles, points de terminaison (par type), règles et champs de règle. Aucun secret."""
    errors: dict[str, str] = {}

    async def part(name: str, path: str):
        try:
            return await _px(db, factory, conn_id, "get", path)
        except HTTPException as e:
            errors[name] = str(e.detail)[:200]
            return None

    targets = shape_targets(await part("targets", f"{BASE}/targets"))
    endpoints: dict[str, list] = {}
    for typ in TARGET_TYPES:
        raw = await part(f"endpoints/{typ}", f"{BASE}/endpoints/{typ}")
        endpoints[typ] = [e for r in (raw if isinstance(raw, list) else []) if isinstance(r, dict) and (e := shape_endpoint(r, typ))]
        endpoints[typ].sort(key=lambda e: e["name"])
    matchers = shape_matchers(await part("matchers", f"{BASE}/matchers"))
    fields = shape_fields(await part("matcher-fields", f"{BASE}/matcher-fields"))
    used = {t for m in matchers for t in m["targets"]}
    for t in targets:
        t["used_by"] = sorted(m["name"] for m in matchers if t["name"] in m["targets"])
    return {"targets": targets, "endpoints": endpoints, "matchers": matchers, "fields": fields, "errors": errors, "unused_targets": sorted(t["name"] for t in targets if t["name"] not in used)}


@router.get("/field-values")
async def field_values(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Valeurs connues des champs de règle (aide à la saisie)."""
    return shape_field_values(await _px(db, factory, conn_id, "get", f"{BASE}/matcher-field-values"))


@router.get("/targets/{typ}/{name}")
async def target_detail(conn_id: int, typ: str = Path(pattern="^(sendmail|smtp|gotify|webhook)$"), name: str = Path(pattern=NAME.pattern), db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory)):
    """Détail d'une cible pour l'éditer, avec le `digest` de Kaji (à renvoyer avec la modification). Jamais de secret."""
    if not any(t["name"] == name and t["type"] == typ for t in shape_targets(await _px(db, factory, conn_id, "get", f"{BASE}/targets"))):
        raise HTTPException(404, "Cible introuvable")
    raw = await _px(db, factory, conn_id, "get", f"{BASE}/endpoints/{typ}/{name}")
    d = shape_endpoint({**(raw if isinstance(raw, dict) else {}), "name": name}, typ)
    if d is None:
        raise HTTPException(502, "Configuration illisible")
    d["digest"] = digest_of(d)
    return d


@router.get("/matchers/{name}")
async def matcher_detail(conn_id: int, name: str = Path(pattern=NAME.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Détail d'une règle pour l'éditer, avec le `digest` de Kaji."""
    m = next((m for m in shape_matchers(await _px(db, factory, conn_id, "get", f"{BASE}/matchers")) if m["name"] == name), None)
    if m is None:
        raise HTTPException(404, "Règle introuvable")
    return {**m, "digest": digest_of(m)}
