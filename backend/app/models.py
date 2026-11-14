from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
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
    # `admin`, `operator` ou `viewer` (`app/roles.py`) ; les comptes d'avant ce champ sont tous `admin` (migration n° 3)
    role: Mapped[str] = mapped_column(String(16), default="admin", server_default="admin")


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


class AlertRule(Base):
    """Règle d'alerte (lot #413) : un seuil sur les ressources d'une connexion. Nouvelle table : `create_all` la crée. L'adresse du webhook est chiffrée (elle peut porter un jeton)."""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conn_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16))             # cpu, mem, storage, node_offline, task_failed
    threshold: Mapped[int] = mapped_column(Integer, default=0)
    minutes: Mapped[int] = mapped_column(Integer, default=5)  # durée pendant laquelle le seuil doit être dépassé avant l'alerte
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    webhook_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor: Mapped[int] = mapped_column(Integer, default=0)   # task_failed : fin de la dernière tâche déjà vue (epoch)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AlertEvent(Base):
    """État d'une alerte pour un sujet (nœud, stockage…) : pending (seuil dépassé, pas encore assez longtemps), firing, resolved."""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(Integer, index=True)
    conn_id: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(10), index=True)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ScheduledAction(Base):
    """Action planifiée sur une machine (lot #411) : une action de la liste blanche, des jours de semaine, une heure dans un fuseau. Nouvelle table : `create_all` la crée."""

    __tablename__ = "scheduled_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conn_id: Mapped[int] = mapped_column(Integer, index=True)
    node: Mapped[str] = mapped_column(String(63))
    gtype: Mapped[str] = mapped_column(String(8))
    vmid: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    days: Mapped[str] = mapped_column(String(16))             # « 0,1,4 » (0 = lundi)
    time: Mapped[str] = mapped_column(String(5))              # « HH:MM »
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Paris")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_key: Mapped[str | None] = mapped_column(String(16), nullable=True)       # minute locale déjà traitée : jamais rejouée
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)    # ok, skipped, refused, error
    last_detail: Mapped[str | None] = mapped_column(String(200), nullable=True)


class UserToken(Base):
    """Jeton Proxmox PERSONNEL d'un utilisateur de Kaji pour une connexion (lot #440, option A du cadrage). Le secret est chiffré avec la clé SÉPARÉE
    `KAJI_TOKEN_KEY` (`app/tokenkey.py`), jamais avec `KAJI_SECRET_KEY` ; il n'est jamais renvoyé par l'API ni journalisé."""

    __tablename__ = "user_tokens"
    __table_args__ = (UniqueConstraint("user_id", "conn_id", name="uq_user_tokens_user_conn"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)            # AdminUser.id
    conn_id: Mapped[int] = mapped_column(Integer, index=True)            # Connection.id
    pve_user: Mapped[str] = mapped_column(String(100))                   # « alice@pve »
    token_id: Mapped[str] = mapped_column(String(100))
    secret_enc: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))        # plus tôt de : date donnée, expiration lue chez Proxmox, durée maximale
    privsep: Mapped[bool] = mapped_column(Boolean, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)       # vrai si Proxmox a confirmé les privilèges séparés ET l'expiration (relus avec le jeton lui-même)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    refused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)      # Proxmox a répondu 401 : jeton expiré ou révoqué chez lui


class LoginFailure(Base):
    """Un échec de connexion (ou de jeton de première configuration, de mot de passe…) par clé, pour le limiteur PERSISTANT (lot #446) : un redémarrage ne remet plus le compteur à zéro.
    Ne contient JAMAIS de mot de passe ni d'identifiant saisi : seulement la clé (adresse IP, éventuellement préfixée) et l'heure."""

    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
