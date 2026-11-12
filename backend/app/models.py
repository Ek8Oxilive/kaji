from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Connection(Base):
    """Connexion à un cluster Proxmox. Le token est stocké chiffré."""

    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=8006)
    user: Mapped[str] = mapped_column(String(100))
    token_id: Mapped[str] = mapped_column(String(100))
    token_secret_enc: Mapped[str] = mapped_column(String)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=False)
    # Certificat PUBLIC du serveur Proxmox épinglé (PEM), ou NULL : voir `app/tlspin.py`. Quand il est posé, il est le seul accepté.
    tls_cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @property
    def tls_pinned(self) -> bool:
        return bool(self.tls_cert_pem)

    @property
    def tls_fingerprint(self) -> str | None:
        from .tlspin import fingerprint_of_pem
        return fingerprint_of_pem(self.tls_cert_pem) if self.tls_cert_pem else None


class AdminUser(Base):
    """Compte du dashboard. Mot de passe stocké haché (argon2id)."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """Journal des actions d'écriture. Ne contient jamais de secret."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    username: Mapped[str] = mapped_column(String(64))
    connection_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    target: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))  # started | error
    upid: Mapped[str | None] = mapped_column(String(300), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)


class UserSession(Base):
    """Session ouverte. Un jeton n'est valable que si sa ligne existe ici : la déconnexion la supprime."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
