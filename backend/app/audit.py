from sqlalchemy.orm import Session

from .models import AuditLog


def record(db: Session, *, username: str, connection_id: int | None, action: str, target: str,
           status: str, upid: str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(username=username, connection_id=connection_id, action=action, target=target,
                    status=status, upid=upid, detail=(detail or None) and detail[:500]))
    db.commit()
