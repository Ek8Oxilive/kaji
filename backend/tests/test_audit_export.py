"""Export de l'audit : fichier JSON et syslog (lot #445, jalon J2)."""
import json
import socket
import threading
import time

import pytest
from sqlalchemy.orm import Session

from app import audit, auditexport
from app.config import get_settings
from app.db import get_engine
from app.models import AuditLog

SECRETS = ["hunter2-secret-value", "abcdef0123456789abcdef0123456789", "s3cr3t-token-xyz"]


@pytest.fixture
def export(client, monkeypatch, tmp_path):
    """Configure l'export pour un test ; remet tout à zéro ensuite."""
    def configure(**env):
        for k in ("KAJI_AUDIT_FILE", "KAJI_AUDIT_FILE_MAX_MB", "KAJI_AUDIT_FILE_BACKUPS", "KAJI_AUDIT_SYSLOG"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()
        auditexport.flush()
    yield configure
    auditexport.flush()
    monkeypatch.undo()
    get_settings.cache_clear()


def record(**kw):
    base = dict(username="alice", connection_id=1, action="vm-start", target="qemu/100@enzo", status="started", upid=None, detail="ok")
    base.update(kw)
    with Session(get_engine()) as db:
        audit.record(db, **base)


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


# ---------- désactivé par défaut ----------

def test_export_is_off_by_default_and_writes_nothing(export, tmp_path):
    export()
    record()
    assert list(tmp_path.iterdir()) == []
    assert auditexport._current() is None


# ---------- fichier ----------

def test_file_gets_one_json_line_per_event_with_stable_keys(export, tmp_path):
    f = tmp_path / "audit.jsonl"
    export(KAJI_AUDIT_FILE=f)
    record(action="a1", target="t1", upid="UPID:enzo:0001", detail="d1")
    record(action="a2", status="error", connection_id=None, detail=None)
    auditexport.flush()
    a, b = lines(f)
    assert list(a) == ["ts", "service", "id", "user", "connection_id", "action", "target", "status", "upid", "detail"]
    assert a["service"] == "kaji" and a["user"] == "alice" and a["action"] == "a1" and a["upid"] == "UPID:enzo:0001" and a["detail"] == "d1"
    assert b["status"] == "error" and b["connection_id"] is None and b["upid"] is None and b["detail"] is None
    assert b["id"] == a["id"] + 1
    assert a["ts"].endswith("Z") and len(a["ts"]) == len("2026-11-15T12:00:00.000Z")


def test_the_file_is_readable_by_its_owner_only(export, tmp_path):
    f = tmp_path / "audit.jsonl"
    export(KAJI_AUDIT_FILE=f)
    record()
    assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_the_database_still_holds_every_event(export, tmp_path):
    export(KAJI_AUDIT_FILE=tmp_path / "audit.jsonl")
    record(action="in-db")
    with Session(get_engine()) as db:
        assert db.query(AuditLog).filter_by(action="in-db").count() == 1


def test_file_rotates_by_size_and_keeps_only_the_configured_backups(export, tmp_path):
    f = tmp_path / "audit.jsonl"
    export(KAJI_AUDIT_FILE=f, KAJI_AUDIT_FILE_MAX_MB=1, KAJI_AUDIT_FILE_BACKUPS=2)
    for _ in range(6000):                                            # ~650 octets l'une, soit ~3,9 Mo pour un plafond de 1 Mo : plusieurs rotations
        record(detail="x" * 480)
    auditexport.flush()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "audit.jsonl" in names and "audit.jsonl.1" in names and "audit.jsonl.2" in names and "audit.jsonl.3" not in names


# ---------- secrets et injection ----------

@pytest.mark.parametrize("detail", [
    "password=hunter2-secret-value",
    "PASSWORD: hunter2-secret-value",
    "Authorization: Bearer hunter2-secret-value",
    "token=hunter2-secret-value",
    "PVEAPIToken=kaji@pve!kaji=abcdef0123456789abcdef0123456789",
    "kaji@pve!kaji=abcdef0123456789abcdef0123456789",
    "ticket=hunter2-secret-value, csrf=hunter2-secret-value",
    "webhook=https://hooks.example.com/hunter2-secret-value",
    "api_key: hunter2-secret-value",
    "PVEAPIToken=kaji@pve!kaji=hunter2-secret-value",                 # secret court, ni hexadécimal ni long : seul le motif PVEAPIToken= le retient
])
def test_secret_looking_values_never_reach_the_export(export, tmp_path, detail):
    f = tmp_path / "audit.jsonl"
    export(KAJI_AUDIT_FILE=f)
    record(detail=detail, target=detail, username="bob")
    auditexport.flush()
    text = f.read_text(encoding="utf-8")
    for secret in ("hunter2-secret-value", "abcdef0123456789abcdef0123456789"):
        assert secret not in text, detail


def test_a_newline_in_a_field_cannot_forge_a_second_event(export, tmp_path):
    f = tmp_path / "audit.jsonl"
    export(KAJI_AUDIT_FILE=f)
    record(detail='ok\n{"service":"kaji","user":"root","action":"fake"}', username="eve\nfake", target="t\r\nx")
    auditexport.flush()
    rows = lines(f)
    assert len(rows) == 1 and rows[0]["action"] == "vm-start"
    assert len(f.read_text(encoding="utf-8").splitlines()) == 1


def test_fields_are_bounded(export, tmp_path):
    f = tmp_path / "audit.jsonl"
    export(KAJI_AUDIT_FILE=f)
    ev = auditexport.event(AuditLog(id=1, username="u", action="a", target="t" * 5000, status="s", detail="d" * 5000))
    assert len(ev["target"]) == auditexport.MAX_FIELD and len(ev["detail"]) == auditexport.MAX_FIELD


# ---------- syslog ----------

def test_syslog_udp_receives_a_rfc5424_message_with_the_json(export):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(3)
    export(KAJI_AUDIT_SYSLOG=f"udp://127.0.0.1:{srv.getsockname()[1]}")
    record(action="udp-test", detail="password=hunter2-secret-value")
    auditexport.flush()
    data = srv.recv(65535).decode()
    srv.close()
    assert data.startswith("<134>1 ") and " kaji - AUDIT - " in data
    body = json.loads(data.split(" kaji - AUDIT - ", 1)[1])
    assert body["action"] == "udp-test" and "hunter2-secret-value" not in data


def test_syslog_tcp_sends_one_line_per_event(export):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got = []

    def serve():
        conn, _ = srv.accept()
        conn.settimeout(3)
        buf = b""
        try:
            while buf.count(b"\n") < 2:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except OSError:
            pass
        got.append(buf)
        conn.close()

    t = threading.Thread(target=serve)
    t.start()
    export(KAJI_AUDIT_SYSLOG=f"tcp://127.0.0.1:{srv.getsockname()[1]}")
    record(action="tcp-1")
    record(action="tcp-2")
    auditexport.flush()
    t.join(5)
    srv.close()
    rows = got[0].decode().splitlines()
    assert len(rows) == 2 and all(r.startswith("<134>1 ") for r in rows)
    assert [json.loads(r.split(" kaji - AUDIT - ", 1)[1])["action"] for r in rows] == ["tcp-1", "tcp-2"]


def test_an_unreachable_syslog_never_blocks_nor_breaks_the_action(export):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                                        # plus personne n'écoute sur ce port
    export(KAJI_AUDIT_SYSLOG=f"tcp://127.0.0.1:{port}")
    started = time.monotonic()
    for _ in range(20):
        record(action="down")
    assert time.monotonic() - started < 2                            # la requête n'attend pas le syslog
    auditexport.flush()
    with Session(get_engine()) as db:
        assert db.query(AuditLog).filter_by(action="down").count() == 20


def test_a_failing_export_never_breaks_audit_record(export, tmp_path, monkeypatch):
    export(KAJI_AUDIT_FILE=tmp_path / "audit.jsonl")
    monkeypatch.setattr(auditexport, "event", lambda row: (_ for _ in ()).throw(RuntimeError("boom")))
    record(action="still-recorded")
    with Session(get_engine()) as db:
        assert db.query(AuditLog).filter_by(action="still-recorded").count() == 1


# ---------- configuration invalide ----------

@pytest.mark.parametrize("url", ["", "udp://host", "http://host:514", "udp://host:0", "udp://host:70000", "udp://ho st:514", "tcp://:514", "udp://host:514/x"])
def test_invalid_syslog_urls_are_refused(export, url):
    export(KAJI_AUDIT_SYSLOG=url)
    errors = auditexport.check_config()
    assert (url == "" and errors == []) or any("KAJI_AUDIT_SYSLOG" in e for e in errors)


@pytest.mark.parametrize("url", ["udp://127.0.0.1:514", "tcp://syslog.example.com:6514", "udp://[::1]:514"])
def test_valid_syslog_urls_are_accepted(export, url):
    export(KAJI_AUDIT_SYSLOG=url)
    assert auditexport.check_config() == []


def test_the_file_path_must_be_absolute_without_dotdot_and_writable(export, tmp_path):
    export(KAJI_AUDIT_FILE="relative/audit.jsonl")
    assert any("absolu" in e for e in auditexport.check_config())
    export(KAJI_AUDIT_FILE=f"{tmp_path}/a/../audit.jsonl")
    assert any("absolu" in e for e in auditexport.check_config())
    export(KAJI_AUDIT_FILE=str(tmp_path))
    assert any("dossier" in e for e in auditexport.check_config())
    (tmp_path / "ro").mkdir(mode=0o500)
    export(KAJI_AUDIT_FILE=str(tmp_path / "ro" / "sub" / "audit.jsonl"))
    import os
    if os.geteuid() != 0:                                            # root passe outre les droits : le contrôle n'a alors pas de sens
        assert any("inscriptible" in e for e in auditexport.check_config())


@pytest.mark.parametrize("env,word", [({"KAJI_AUDIT_FILE_MAX_MB": 0}, "MAX_MB"), ({"KAJI_AUDIT_FILE_MAX_MB": 5000}, "MAX_MB"),
                                      ({"KAJI_AUDIT_FILE_BACKUPS": -1}, "BACKUPS"), ({"KAJI_AUDIT_FILE_BACKUPS": 5000}, "BACKUPS")])
def test_size_and_backup_bounds(export, env, word):
    export(**env)
    assert any(word in e for e in auditexport.check_config())


def test_kaji_refuses_to_start_with_an_invalid_export_configuration(export):
    from fastapi.testclient import TestClient

    from app.main import app
    export(KAJI_AUDIT_SYSLOG="not-a-url")
    with pytest.raises(RuntimeError, match="export de l'audit"):
        with TestClient(app):
            pass


# ---------- file pleine et journal de Kaji ----------

def test_a_full_syslog_queue_drops_the_event_without_raising():
    import logging
    import queue
    q = queue.Queue(maxsize=1)
    q.put("occupé")
    handler = auditexport._DropWhenFull(q)
    handler.enqueue(logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None))      # file pleine : ne lève rien, ne bloque pas
    assert q.qsize() == 1


def test_a_failing_export_is_logged_once_per_minute_not_for_every_event(export, tmp_path, monkeypatch, caplog):
    export(KAJI_AUDIT_FILE=tmp_path / "audit.jsonl")
    monkeypatch.setattr(auditexport, "event", lambda row: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(auditexport, "_last_error", float("-inf"))
    with caplog.at_level("ERROR", logger="kaji.auditexport"):
        for _ in range(5):
            record(action="boom")
    assert len([r for r in caplog.records if r.name == "kaji.auditexport"]) == 1
