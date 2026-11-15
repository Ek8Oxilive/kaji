"""Accès base de la double authentification de la connexion à Kaji (lot #444). Les opérations qui doivent être ATOMIQUES (anti-rejeu d'un code, usage unique d'un code de secours)
sont des `UPDATE … WHERE` dont on lit le nombre de lignes touchées : deux requêtes simultanées avec le même code ne passent pas toutes les deux."""
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from . import crypto, totp
from .models import TotpRecoveryCode, UserTotp


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_enabled(db: Session, user_id: int) -> bool:
    row = db.get(UserTotp, user_id)
    return row is not None and bool(row.confirmed)


def enabled_ids(db: Session) -> set[int]:
    return set(db.scalars(select(UserTotp.user_id).where(UserTotp.confirmed.is_(True))).all())


def remaining_recovery(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user_id, TotpRecoveryCode.used_at.is_(None))) or 0


def start_enrollment(db: Session, secret_key: str, user_id: int) -> str:
    """Génère un secret, le chiffre, et le garde EN ATTENTE (non exigé à la connexion) jusqu'à un premier code valide. Remplace un enrôlement en attente."""
    secret = totp.generate_secret()
    row = db.get(UserTotp, user_id)
    enc = crypto.encrypt(secret_key, secret)
    if row is None:
        db.add(UserTotp(user_id=user_id, secret_enc=enc, confirmed=False, last_step=0))
    else:
        row.secret_enc, row.confirmed, row.last_step = enc, False, 0
    db.commit()
    return secret


def confirm_enrollment(db: Session, secret_key: str, user_id: int, code: str, now: float | None = None) -> list[str] | None:
    """Premier code valide : active le TOTP et renvoie les codes de secours (la SEULE fois où ils sont visibles). `None` si le code est faux ou s'il n'y a rien en attente."""
    row = db.get(UserTotp, user_id)
    if row is None or row.confirmed:
        return None
    step = totp.verify(crypto.decrypt(secret_key, row.secret_enc), code, last_step=0, now=now)
    if step is None:
        return None
    row.confirmed, row.last_step = True, step
    return _replace_recovery(db, secret_key, user_id)


def _replace_recovery(db: Session, secret_key: str, user_id: int) -> list[str]:
    codes = totp.new_recovery_codes()
    db.execute(delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user_id))
    for c in codes:
        db.add(TotpRecoveryCode(user_id=user_id, code_hash=totp.recovery_hash(c)))
    db.commit()
    return codes


def regenerate_recovery(db: Session, secret_key: str, user_id: int) -> list[str]:
    return _replace_recovery(db, secret_key, user_id)


def check(db: Session, secret_key: str, user_id: int, text: str, *, allow_recovery: bool = True, now: float | None = None) -> str | None:
    """`"totp"` (code de l'application), `"recovery"` (code de secours, consommé) ou `None`. Un code TOTP déjà accepté ne l'est jamais une seconde fois."""
    row = db.get(UserTotp, user_id)
    if row is None or not row.confirmed:
        return None
    if totp.looks_like_code(text):
        step = totp.verify(crypto.decrypt(secret_key, row.secret_enc), text, last_step=row.last_step, now=now)
        if step is None:
            return None
        res = db.execute(update(UserTotp).where(UserTotp.user_id == user_id, UserTotp.last_step < step).values(last_step=step))
        db.commit()
        return "totp" if res.rowcount == 1 else None                  # une autre requête a pris ce pas entre-temps : rejeu
    if allow_recovery and totp.looks_like_recovery(text):
        res = db.execute(update(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user_id, TotpRecoveryCode.code_hash == totp.recovery_hash(text),
                                                       TotpRecoveryCode.used_at.is_(None)).values(used_at=_now() if now is None else datetime.fromtimestamp(now, timezone.utc)))
        db.commit()
        return "recovery" if res.rowcount == 1 else None
    return None


def remove(db: Session, user_id: int) -> None:
    db.execute(delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user_id))
    db.execute(delete(UserTotp).where(UserTotp.user_id == user_id))
    db.commit()
