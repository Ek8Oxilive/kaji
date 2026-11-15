"""Export de l'audit vers un fichier JSON (une ligne par événement) et/ou un serveur syslog (lot #445, jalon J2).

Principes :
- L'export s'AJOUTE à la base (qui reste la source, avec sa conservation `KAJI_AUDIT_RETENTION_DAYS`) ; il est désactivé par défaut.
- **Jamais de secret** : les champs libres (`detail`, `target`, `user`) passent par `scrub` avant d'être écrits (défense en profondeur : l'audit ne reçoit déjà aucun secret).
- **Une ligne = un événement** : le JSON échappe les sauts de ligne (une valeur hostile ne fabrique pas de fausse entrée).
- **Une panne de l'export ne casse jamais l'action** : `emit` n'élève jamais d'exception ; une configuration INVALIDE, elle, empêche le démarrage (`check_config`) :
  perdre l'audit en silence serait pire que ne pas démarrer.
- Le syslog part par une file et un fil d'exécution à part : un serveur lent ou injoignable ne bloque jamais une requête.
"""
import json
import logging
import logging.handlers
import os
import re
import threading
import time
from datetime import timezone
from pathlib import Path

from .config import get_settings

log = logging.getLogger("kaji.auditexport")

SYSLOG_URL = re.compile(r"(?P<proto>udp|tcp)://(?P<host>[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:]{2,45}\]):(?P<port>[0-9]{1,5})")
# Valeurs qui ressemblent à un secret, quelle que soit la façon dont elles sont écrites : `password=…`, `token: …`, `Authorization: Bearer …`, jeton Proxmox.
_SECRET_KEYS = r"(?:pass(?:word|wd)?|secret|token|authorization|ticket|csrf(?:preventiontoken)?|api[_-]?key|cookie|bearer|webhook|url)"
_SCRUB = [
    (re.compile(r"PVEAPIToken=\S+", re.I), "PVEAPIToken=***"),
    (re.compile(r"\b[A-Za-z0-9._-]+@[A-Za-z0-9._-]+![A-Za-z0-9._-]+=[0-9a-fA-F-]{16,}", re.I), "***"),                # user@realm!nom=secret
    (re.compile(rf"(?i)\b({_SECRET_KEYS})\b(\s*[=:]\s*)(?:Bearer\s+)?[^\s,;]+"), r"\1\2***"),
]
MAX_FIELD = 500


def scrub(value) -> str:
    """Texte sans valeur secrète apparente, borné."""
    text = "" if value is None else str(value)
    for pattern, repl in _SCRUB:
        text = pattern.sub(repl, text)
    return text[:MAX_FIELD]


def event(row) -> dict:
    """L'événement exporté. Les clés sont stables (voir `docs/api/audit-export.md`)."""
    ts = row.ts
    if ts is not None and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)                       # SQLite rend des dates sans fuseau : ce sont des dates UTC
    return {
        "ts": ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" if ts is not None else None,
        "service": "kaji",
        "id": row.id,
        "user": scrub(row.username),
        "connection_id": row.connection_id,
        "action": scrub(row.action),
        "target": scrub(row.target),
        "status": scrub(row.status),
        "upid": scrub(row.upid) if row.upid else None,
        "detail": scrub(row.detail) if row.detail else None,
    }


def check_config(settings=None) -> list[str]:
    """Erreurs de configuration (liste vide = valide). Appelée au démarrage : une erreur empêche de démarrer."""
    s = settings or get_settings()
    errors: list[str] = []
    if s.kaji_audit_syslog and not SYSLOG_URL.fullmatch(s.kaji_audit_syslog):
        errors.append("KAJI_AUDIT_SYSLOG doit avoir la forme udp://hôte:port ou tcp://hôte:port")
    elif s.kaji_audit_syslog and not 1 <= int(SYSLOG_URL.fullmatch(s.kaji_audit_syslog).group("port")) <= 65535:
        errors.append("KAJI_AUDIT_SYSLOG : le port doit être compris entre 1 et 65535")
    if s.kaji_audit_file:
        p = Path(s.kaji_audit_file)
        if not p.is_absolute() or ".." in p.parts:
            errors.append("KAJI_AUDIT_FILE doit être un chemin absolu, sans « .. »")
        elif p.is_dir():
            errors.append("KAJI_AUDIT_FILE est un dossier")
        else:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8"):
                    pass
            except OSError as exc:
                errors.append(f"KAJI_AUDIT_FILE n'est pas inscriptible ({exc.strerror or exc.__class__.__name__})")
    if not 1 <= s.kaji_audit_file_max_mb <= 1024:
        errors.append("KAJI_AUDIT_FILE_MAX_MB doit être compris entre 1 et 1024")
    if not 0 <= s.kaji_audit_file_backups <= 1000:
        errors.append("KAJI_AUDIT_FILE_BACKUPS doit être compris entre 0 et 1000")
    return errors


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


class _SyslogHandler(logging.Handler):
    """Envoie chaque événement en syslog RFC 5424 (`<134>1 date hôte kaji - AUDIT - {json}`, facility local0, gravité info), en UDP ou en TCP (un message par ligne).

    Se connecte À LA DEMANDE et se reconnecte seul : un serveur éteint au démarrage de Kaji n'empêche pas Kaji de démarrer (le constructeur de `SysLogHandler`
    de la bibliothèque standard, lui, échouerait). Tourne dans le fil du `QueueListener` : une connexion lente ne bloque jamais une requête.
    """
    TIMEOUT = 3.0

    def __init__(self, proto: str, host: str, port: int):
        super().__init__()
        self.proto, self.host, self.port = proto, host, port
        self.sock = None
        import socket
        self.hostname = re.sub(r"[^!-~]", "-", socket.gethostname())[:255] or "-"

    def _connect(self):
        import socket
        kind = socket.SOCK_STREAM if self.proto == "tcp" else socket.SOCK_DGRAM
        sock = socket.socket(socket.AF_INET6 if ":" in self.host else socket.AF_INET, kind)
        sock.settimeout(self.TIMEOUT)
        if self.proto == "tcp":
            sock.connect((self.host, self.port))
        return sock

    def emit(self, record: logging.LogRecord) -> None:
        from datetime import datetime
        stamp = datetime.fromtimestamp(record.created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        message = f"<134>1 {stamp} {self.hostname} kaji - AUDIT - {record.getMessage()}"
        data = (message + ("\n" if self.proto == "tcp" else "")).encode("utf-8")
        try:
            if self.sock is None:
                self.sock = self._connect()
            if self.proto == "tcp":
                self.sock.sendall(data)
            else:
                self.sock.sendto(data, (self.host, self.port))
        except OSError:
            self._drop()                                        # serveur injoignable : cet événement est perdu pour le syslog (il reste dans la base), on réessaiera au suivant
            raise_once()

    def _drop(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def close(self) -> None:
        self._drop()
        super().close()


class _DropWhenFull(logging.handlers.QueueHandler):
    """File pleine (serveur injoignable depuis longtemps) : l'événement est jeté, la requête n'attend jamais."""
    def enqueue(self, record: logging.LogRecord) -> None:
        import queue
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            pass


def raise_once() -> None:
    """Signale l'échec du syslog au plus une fois par minute (journal de Kaji), sans inonder."""
    global _last_error
    if time.monotonic() - _last_error > 60:
        _last_error = time.monotonic()
        log.error("syslog injoignable : des événements ne sont pas envoyés (ils restent dans la base)")


class _Sinks:
    """Les destinations ouvertes pour UNE configuration. Reconstruites si la configuration change (tests, rechargement)."""

    def __init__(self, s):
        self.key = _key(s)
        self.file_logger = None
        self.syslog_queue = None
        self.listener = None
        self.handlers: list[logging.Handler] = []
        if s.kaji_audit_file:
            self.file_logger = logging.Logger(f"kaji.audit.file.{id(self)}")
            handler = logging.handlers.RotatingFileHandler(s.kaji_audit_file, maxBytes=s.kaji_audit_file_max_mb * 1024 * 1024,
                                                           backupCount=s.kaji_audit_file_backups, encoding="utf-8")
            handler.setFormatter(_JsonLineFormatter())
            self.file_logger.addHandler(handler)
            self.handlers.append(handler)
            try:
                os.chmod(s.kaji_audit_file, 0o600)               # l'audit nomme des personnes et des machines : lisible par son seul propriétaire
            except OSError:
                pass
        if s.kaji_audit_syslog:
            m = SYSLOG_URL.fullmatch(s.kaji_audit_syslog)
            import queue
            handler = _SyslogHandler(m.group("proto"), m.group("host").strip("[]"), int(m.group("port")))
            self.handlers.append(handler)
            self.syslog_queue = queue.Queue(maxsize=10000)      # pleine (serveur injoignable) : on jette plutôt que de bloquer
            self.listener = logging.handlers.QueueListener(self.syslog_queue, handler, respect_handler_level=False)
            self.listener.start()
            self.syslog_logger = logging.Logger(f"kaji.audit.syslog.{id(self)}")
            self.syslog_logger.addHandler(_DropWhenFull(self.syslog_queue))

    def close(self) -> None:
        if self.listener is not None:
            self.listener.stop()                                # vide la file avant d'arrêter
            self.listener = None
        for h in self.handlers:
            try:
                h.close()
            except Exception:
                pass


def _key(s) -> tuple:
    return (s.kaji_audit_file, s.kaji_audit_file_max_mb, s.kaji_audit_file_backups, s.kaji_audit_syslog)


_lock = threading.Lock()
_sinks: _Sinks | None = None
_last_error = float("-inf")


def _current() -> _Sinks | None:
    global _sinks
    s = get_settings()
    if not s.kaji_audit_file and not s.kaji_audit_syslog:
        if _sinks is not None:
            with _lock:
                if _sinks is not None:
                    _sinks.close()
                    _sinks = None
        return None
    with _lock:
        if _sinks is None or _sinks.key != _key(s):
            if _sinks is not None:
                _sinks.close()
            _sinks = _Sinks(s)
        return _sinks


def flush() -> None:
    """Vide la file du syslog (arrêt propre, tests)."""
    global _sinks
    with _lock:
        if _sinks is not None:
            _sinks.close()
            _sinks = None


def emit(row) -> None:
    """Écrit un événement sur les destinations configurées. N'élève JAMAIS d'exception (une panne d'export ne casse pas l'action)."""
    global _last_error
    try:
        sinks = _current()
        if sinks is None:
            return
        line = json.dumps(event(row), ensure_ascii=False, separators=(",", ":"))
        if sinks.file_logger is not None:
            sinks.file_logger.info(line)
        if sinks.syslog_queue is not None:
            try:
                sinks.syslog_logger.info(line)
            except Exception:
                pass
    except Exception:
        if time.monotonic() - _last_error > 60:                 # un message par minute au plus : pas d'inondation des journaux
            _last_error = time.monotonic()
            log.error("export de l'audit impossible (l'audit reste dans la base)", exc_info=True)
