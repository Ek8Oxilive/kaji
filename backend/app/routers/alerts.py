"""Alertes (lot #413) : règles et historique. L'évaluation est dans `app/alerts.py`.

Lecture : tout utilisateur de Kaji. Écriture : **administrateurs seulement** (`app/roles.py`). L'adresse du webhook est en ÉCRITURE SEULE : chiffrée en base, jamais renvoyée
(seulement `has_webhook`), jamais journalisée. Le test d'envoi demande `confirm=true` et n'est possible qu'une fois par minute et par règle.
"""
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import StrictBool
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import alerts as engine
from .. import audit
from ..alertspec import MAX_RULES_PER_CONNECTION, RuleBody, check_rule
from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..db import get_db
from ..isospec import check_url
from ..models import AdminUser, AlertEvent, AlertRule
from .auth import current_user
from .connections import _get_or_404

router = APIRouter(prefix="/api/connections/{conn_id}/alerts", tags=["alerts"])
_LAST_TEST: dict[int, float] = {}
TEST_EVERY = 60


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def _rule_out(r: AlertRule) -> dict:
    return {"id": r.id, "name": r.name, "kind": r.kind, "threshold": r.threshold, "minutes": r.minutes, "enabled": bool(r.enabled), "has_webhook": bool(r.webhook_enc), "created_by": r.created_by}


def _log(db, user, conn_id, action, target, st, detail=None):
    audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target[:200], status=st, detail=detail)


def _refuse(db, user, conn_id, action, target, msg, code):
    _log(db, user, conn_id, action, target, "error", msg)
    raise HTTPException(code, msg)


def _validated(db, user, conn_id, action, body: RuleBody) -> str | None:
    """Vérifie la règle et renvoie l'adresse de webhook chiffrée (ou None) ; refuse sinon."""
    if (msg := check_rule(body)) is not None:
        _refuse(db, user, conn_id, action, body.name, msg, status.HTTP_422_UNPROCESSABLE_CONTENT)
    if body.webhook_url is None:
        return None
    try:
        check_url(body.webhook_url)
    except ValueError as e:
        _refuse(db, user, conn_id, action, body.name, f"Adresse du webhook refusée : {e}", status.HTTP_422_UNPROCESSABLE_CONTENT)
    return encrypt(get_settings().kaji_secret_key, body.webhook_url)


def _rule_or_404(db: Session, conn_id: int, rid: int) -> AlertRule:
    r = db.get(AlertRule, rid)
    if r is None or r.conn_id != conn_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Règle inconnue")
    return r


@router.get("/rules")
def list_rules(conn_id: int, db: Session = Depends(get_db), _u: AdminUser = Depends(current_user)):
    _get_or_404(db, conn_id)
    return [_rule_out(r) for r in db.scalars(select(AlertRule).where(AlertRule.conn_id == conn_id).order_by(AlertRule.id))]


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(body: RuleBody, conn_id: int, db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    _get_or_404(db, conn_id)
    if (db.scalar(select(func.count()).select_from(AlertRule).where(AlertRule.conn_id == conn_id)) or 0) >= MAX_RULES_PER_CONNECTION:
        _refuse(db, user, conn_id, "alert-rule-create", body.name, f"{MAX_RULES_PER_CONNECTION} règles au plus par connexion", status.HTTP_409_CONFLICT)
    enc = _validated(db, user, conn_id, "alert-rule-create", body)
    r = AlertRule(conn_id=conn_id, name=body.name, kind=body.kind, threshold=body.threshold, minutes=body.minutes, enabled=body.enabled, webhook_enc=enc, created_by=user.username)
    db.add(r)
    db.commit()
    _log(db, user, conn_id, "alert-rule-create", r.name, "started", f"#{r.id} {r.kind} seuil {r.threshold} {r.minutes} min{', webhook défini' if enc else ''}")
    return _rule_out(r)


@router.put("/rules/{rid}")
def update_rule(body: RuleBody, conn_id: int, rid: int = Path(ge=1), db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    r = _rule_or_404(db, conn_id, rid)
    enc = _validated(db, user, conn_id, "alert-rule-update", body)
    r.name, r.kind, r.threshold, r.minutes, r.enabled = body.name, body.kind, body.threshold, body.minutes, body.enabled
    if body.clear_webhook:
        r.webhook_enc = None
    elif enc is not None:
        r.webhook_enc = enc
    db.commit()
    _log(db, user, conn_id, "alert-rule-update", r.name, "started", f"#{r.id} {r.kind} seuil {r.threshold} {r.minutes} min{'' if r.enabled else ' (désactivée)'}")
    return _rule_out(r)


@router.delete("/rules/{rid}")
def delete_rule(conn_id: int, rid: int = Path(ge=1), confirm: StrictBool = Query(default=False), db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    r = _rule_or_404(db, conn_id, rid)
    if not confirm:
        _refuse(db, user, conn_id, "alert-rule-delete", r.name, "Suppression : renvoie la requête avec confirm=true", status.HTTP_400_BAD_REQUEST)
    name = r.name
    db.execute(delete(AlertEvent).where(AlertEvent.rule_id == r.id))
    db.delete(r)
    db.commit()
    _log(db, user, conn_id, "alert-rule-delete", name, "started", f"#{rid} supprimée avec son historique")
    return {"deleted": rid}


@router.get("/events")
def list_events(conn_id: int, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), _u: AdminUser = Depends(current_user)):
    """Alertes en cours (`pending`, `firing`) puis historique, plus récentes d'abord."""
    _get_or_404(db, conn_id)
    names = {r.id: r.name for r in db.scalars(select(AlertRule).where(AlertRule.conn_id == conn_id))}
    rows = db.scalars(select(AlertEvent).where(AlertEvent.conn_id == conn_id).order_by(AlertEvent.id.desc()).limit(limit)).all()
    return [{"id": e.id, "rule_id": e.rule_id, "rule": names.get(e.rule_id, "(règle supprimée)"), "subject": e.subject, "status": e.status, "since": _iso(e.since),
             "fired_at": _iso(e.fired_at), "resolved_at": _iso(e.resolved_at), "value": e.value, "detail": e.detail} for e in rows]


@router.post("/rules/{rid}/test")
async def test_rule(conn_id: int, rid: int = Path(ge=1), confirm: StrictBool = Query(default=False), db: Session = Depends(get_db), user: AdminUser = Depends(current_user)):
    """Envoie UN message de test au webhook de la règle (`confirm=true`, une fois par minute et par règle)."""
    r = _rule_or_404(db, conn_id, rid)
    if not confirm:
        _refuse(db, user, conn_id, "alert-test", r.name, "Test d'envoi : renvoie la requête avec confirm=true (un vrai message part)", status.HTTP_400_BAD_REQUEST)
    if not r.webhook_enc:
        _refuse(db, user, conn_id, "alert-test", r.name, "Cette règle n'a pas de webhook", status.HTTP_409_CONFLICT)
    now = time.monotonic()
    if now - _LAST_TEST.get(r.id, -TEST_EVERY) < TEST_EVERY:
        _refuse(db, user, conn_id, "alert-test", r.name, "Un test par minute et par règle : attends un peu", status.HTTP_429_TOO_MANY_REQUESTS)
    _LAST_TEST[r.id] = now
    try:
        url = decrypt(get_settings().kaji_secret_key, r.webhook_enc)
    except Exception:
        _refuse(db, user, conn_id, "alert-test", r.name, "Adresse du webhook illisible : saisis-la à nouveau", status.HTTP_409_CONFLICT)
    ok = await engine.send_webhook(url, f"[Kaji] TEST de la règle « {r.name} » : ceci est un message d'essai", {"rule": r.name, "kind": r.kind, "state": "test"})
    _log(db, user, conn_id, "alert-test", r.name, "started" if ok else "error", "message de test envoyé" if ok else "envoi échoué")
    return {"sent": ok}
