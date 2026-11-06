import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuditLog

_PURGE_EVERY = 6 * 3600
_last_purge = float("-inf")


def purge_old(db: Session, days: int) -> int:
    """Supprime les entrées plus anciennes que `days` jours (0 = tout conserver). Renvoie le nombre supprimé."""
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    n = db.execute(delete(AuditLog).where(AuditLog.ts < cutoff)).rowcount
    db.commit()
    return n or 0


def record(db: Session, *, username: str, connection_id: int | None, action: str, target: str,
           status: str, upid: str | None = None, detail: str | None = None) -> None:
    global _last_purge
    db.add(AuditLog(username=username, connection_id=connection_id, action=action, target=target,
                    status=status, upid=upid, detail=(detail or None) and detail[:500]))
    db.commit()
    if time.monotonic() - _last_purge > _PURGE_EVERY:      # purge paresseuse, au plus toutes les 6 h
        _last_purge = time.monotonic()
        purge_old(db, get_settings().kaji_audit_retention_days)
