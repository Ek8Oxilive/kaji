"""Console web : demande de console (HTTP) et relais WebSocket. Le « Proxmox » est simulé : REST par `MockTransport`, console par un
vrai petit serveur WebSocket local (jouant le rôle de `vncwebsocket`)."""
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import serve

from app import consolespec
from app.consolespec import ConsoleSessions, Target, origin_ok, valid_proxy_reply
from app.db import get_engine
from app.deps import get_client_factory
from app.main import app
from app.models import AuditLog
from app.proxmox import ProxmoxClient
from app.routers import console as console_router

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
TICKET = "PVEVNC:6AEE5C1A::TiCk3t/Secr3t+Value=="
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
ORIGIN = {"origin": "http://testserver"}


class Upstream:
    """Console Proxmox simulée : accepte un WebSocket, joue le protocole de `vnc` ou de `term`, renvoie ce qu'on lui envoie."""

    def __init__(self):
        self.received: list = []
        self.paths: list[str] = []
        self.auth: list[str | None] = []
        self.kind = "vnc"
        self.refuse = False
        self.term_reply = b"OK"
        self.server = serve(self._handle, "127.0.0.1", 0, subprotocols=["binary"], process_request=self._process)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _process(self, conn, request):
        if self.refuse:                                                # refus à la poignée de main, comme Proxmox sans droit
            return conn.respond(403, "refusé\n")

    def _handle(self, conn):
        self.paths.append(conn.request.path)
        self.auth.append(conn.request.headers.get("Authorization"))
        if self.kind == "vnc":
            conn.send(b"RFB 003.008\n")
        else:
            first = conn.recv()
            self.received.append(first)
            if first != "kaji@pve!kaji:" + TICKET + "\n":
                conn.close(1008)
                return
            conn.send(self.term_reply)
        try:
            for m in conn:
                self.received.append(m)
                if m == "fermer":
                    conn.close()
                    return
                conn.send(b"echo:" + (m if isinstance(m, bytes) else m.encode()))
        except Exception:
            pass

    def stop(self):
        self.server.shutdown()


class FakeClient(ProxmoxClient):
    def ws_target(self, path, /, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        return f"ws://127.0.0.1:{UP.port}/api2/json{path}?{q}", {"Authorization": "PVEAPIToken=fake"}, None


UP: Upstream
STATE: dict = {}
CALLS: list[tuple[str, str, dict]] = []


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    CALLS.append((request.method, p, dict(httpx.QueryParams(request.content.decode())) if request.content else {}))
    if p == "/nodes/pve1/status":
        return httpx.Response(200, json={"data": STATE.get("node_status", {"uptime": 1})})
    if p == "/nodes/pve1/termproxy":
        if STATE.get("node_denied"):
            return httpx.Response(403, json={"data": None, "message": "Permission check failed (/nodes/pve1, Sys.Console)"})
        if STATE.get("reply") is not None:
            return httpx.Response(200, json={"data": STATE["reply"]})
        return httpx.Response(200, json={"data": {"port": UP.port, "ticket": TICKET, "user": "kaji@pve!kaji", "upid": "UPID:x"}})
    if p.endswith("/status/current"):
        return httpx.Response(200, json={"data": {"status": STATE.get("status", "running"), "template": STATE.get("template", 0)}})
    if p.endswith("/vncproxy") or p.endswith("/termproxy"):
        if STATE.get("reply") is not None:
            return httpx.Response(200, json={"data": STATE["reply"]})
        return httpx.Response(200, json={"data": {"port": UP.port, "ticket": TICKET, "user": "kaji@pve!kaji", "upid": "UPID:x"}})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    global UP
    UP = Upstream()
    STATE.clear()
    CALLS.clear()
    console_router.SESSIONS = ConsoleSessions()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: FakeClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()
    UP.stop()


def url(cid, node="pve1", gtype="lxc", vmid=105):
    return f"/api/connections/{cid}/guests/{node}/{gtype}/{vmid}/console"


def opened(api, kind="vnc", **kw):
    c, cid = api
    r = c.post(url(cid, **kw), json={"kind": kind})
    assert r.status_code == 201, r.text
    return r.json()


def audit_rows():
    with Session(get_engine()) as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.action.like("console-%")).order_by(AuditLog.id)))


def wait_close(timeout=5.0):
    """Attend que la ligne d'audit de fermeture soit écrite (elle l'est après la fermeture de la connexion : le délai dépend de la
    charge de la machine, une pause fixe rendait les tests fragiles)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        rows = audit_rows()
        if rows and rows[-1].action == "console-close":
            return
        time.sleep(0.05)


# ---------- demande d'une console -----------------------------------------------------------------------------------

def test_open_requires_auth(client):
    assert client.post("/api/connections/1/guests/pve1/lxc/105/console", json={"kind": "vnc"}).status_code == 401


def test_open_vnc_returns_session_and_ticket_but_never_the_api_token(api):
    r = opened(api, "vnc")
    assert set(r) == {"session", "kind", "expires_in", "ticket"} and r["ticket"] == TICKET and r["kind"] == "vnc"
    assert len(r["session"]) >= 30 and r["session"] != TICKET


def test_open_term_never_exposes_the_ticket(api):
    r = opened(api, "term")
    assert set(r) == {"session", "kind", "expires_in"}
    assert TICKET not in str(r)


def test_open_asks_proxmox_with_the_right_calls(api):
    opened(api, "vnc", gtype="qemu", vmid=100)
    opened(api, "term", gtype="lxc", vmid=105)
    posts = [(m, p, f) for m, p, f in CALLS if m == "POST"]
    assert posts == [("POST", "/nodes/pve1/qemu/100/vncproxy", {"websocket": "1"}), ("POST", "/nodes/pve1/lxc/105/termproxy", {})]


@pytest.mark.parametrize("status,template", [("stopped", 0), ("running", 1), ("paused", 0)])
def test_open_refused_when_not_running_or_template(api, status, template):
    c, cid = api
    STATE.update(status=status, template=template)
    assert c.post(url(cid), json={"kind": "vnc"}).status_code == 409
    assert not [x for x in CALLS if x[1].endswith("proxy")]            # rien n'est demandé à Proxmox


def test_term_console_only_for_containers(api):
    c, cid = api
    assert c.post(url(cid, gtype="qemu", vmid=100), json={"kind": "term"}).status_code == 400
    assert not [x for x in CALLS if x[0] == "POST"]


@pytest.mark.parametrize("bad", [{"kind": "spice"}, {"kind": "VNC"}, {"kind": 5}, {"kind": None}])
def test_open_rejects_unknown_kind(api, bad):
    c, cid = api
    assert c.post(url(cid), json=bad).status_code == 422 and not CALLS


@pytest.mark.parametrize("path", ["/nodes/../x", "pve1;id", "a b"])
def test_open_rejects_bad_node(api, path):
    c, cid = api
    assert c.post(f"/api/connections/{cid}/guests/{path}/lxc/105/console", json={"kind": "vnc"}).status_code in (404, 422)
    assert not [x for x in CALLS if x[0] == "POST"]


@pytest.mark.parametrize("reply", [None, "x", {"port": 0, "ticket": "t", "user": "u"}, {"port": 70000, "ticket": "t", "user": "u"},
                                   {"port": 5900, "ticket": "", "user": "u"}, {"port": 5900, "ticket": "t"}, {"port": True, "ticket": "t", "user": "u"},
                                   {"port": 5900, "ticket": "t" * 5000, "user": "u"}])
def test_unusable_proxmox_reply_is_a_502_with_no_session(api, reply):
    c, cid = api
    STATE["reply"] = reply if reply is not None else {}
    assert c.post(url(cid), json={"kind": "vnc"}).status_code == 502
    assert console_router.SESSIONS._pending == {}


def test_open_is_audited_without_ticket_or_secret(api):
    opened(api, "vnc")
    rows = audit_rows()
    assert [(r.action, r.status, r.target) for r in rows] == [("console-open", "started", "lxc/105@pve1 (vnc)")]
    assert TICKET not in str(rows[0].detail) and SECRET not in str(rows[0].detail)


def test_refused_open_is_audited(api):
    c, cid = api
    STATE["status"] = "stopped"
    c.post(url(cid), json={"kind": "vnc"})
    assert [(r.action, r.status) for r in audit_rows()] == [("console-open", "error")]


def test_too_many_pending_requests_are_refused(api):
    c, cid = api
    for _ in range(consolespec.MAX_PENDING):
        opened(api)
    assert c.post(url(cid), json={"kind": "vnc"}).status_code == 429


# ---------- WebSocket : refus avant d'accepter ----------------------------------------------------------------------

def ws_refused(c, session, headers=ORIGIN):
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/console/{session}", headers=headers):
            pass


def test_ws_refuses_without_login(api):
    c, _ = api
    s = opened(api)["session"]
    with TestClient(app) as anon:
        ws_refused(anon, s)
    assert UP.paths == []                                              # Proxmox n'a jamais été contacté


@pytest.mark.parametrize("headers", [{}, {"origin": "http://evil.example"}, {"origin": "http://testserver.evil.example"},
                                     {"origin": "null"}, {"origin": "http://user@testserver"}, {"origin": "ftp://testserver"}])
def test_ws_refuses_bad_or_missing_origin(api, headers):
    c, _ = api
    s = opened(api)["session"]
    ws_refused(c, s, headers)
    assert UP.paths == []
    ok = c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"])      # l'identifiant n'a pas été brûlé
    with ok as ws:
        assert ws.receive_bytes() == b"RFB 003.008\n"


@pytest.mark.parametrize("session", ["", "x", "inconnu" * 6, "a" * 70, "../etc", "abc def" * 5])
def test_ws_refuses_unknown_session_ids(api, session):
    c, _ = api
    ws_refused(c, session)


def test_session_id_is_single_use(api):
    c, _ = api
    s = opened(api)["session"]
    with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        assert ws.receive_bytes() == b"RFB 003.008\n"
    ws_refused(c, s)
    assert len(UP.paths) == 1


def test_session_id_is_bound_to_the_kaji_session(api):
    c, _ = api
    s = opened(api)["session"]
    with TestClient(app) as other:                                     # même compte, autre session
        assert other.post("/api/auth/login", json={"username": "admin", "password": PWD}).status_code == 200
        ws_refused(other, s)
    with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:   # le propriétaire peut encore s'en servir
        assert ws.receive_bytes() == b"RFB 003.008\n"


def test_expired_session_id_is_refused(api, monkeypatch):
    c, _ = api
    s = opened(api)["session"]
    monkeypatch.setattr(consolespec, "SESSION_TTL", 0.0)
    for p in console_router.SESSIONS._pending.values():
        p.expires = 0.0
    ws_refused(c, s)


# ---------- WebSocket : relais --------------------------------------------------------------------------------------

def test_vnc_is_relayed_both_ways_with_the_api_token_upstream(api):
    c, _ = api
    s = opened(api, "vnc")["session"]
    with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        assert ws.accepted_subprotocol == "binary"
        assert ws.receive_bytes() == b"RFB 003.008\n"
        ws.send_bytes(b"\x01\x02clic")
        assert ws.receive_bytes() == b"echo:\x01\x02clic"
    assert UP.received == [b"\x01\x02clic"]
    assert UP.paths == [f"/api2/json/nodes/pve1/lxc/105/vncwebsocket?port={UP.port}&vncticket={TICKET}"]
    assert UP.auth == ["PVEAPIToken=fake"]


def test_term_login_is_done_by_the_server_and_ok_is_swallowed(api):
    c, _ = api
    UP.kind = "term"
    s = opened(api, "term")["session"]
    with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        ws.send_text("0:5:hello")
        assert ws.receive_bytes() == b"echo:0:5:hello"                # le « OK » de connexion n'est pas transmis au navigateur
    assert UP.received[0] == "kaji@pve!kaji:" + TICKET + "\n"            # envoyé par le serveur, pas par le navigateur
    assert UP.received[1] == "0:5:hello"


def test_text_and_binary_frames_keep_their_type(api):
    c, _ = api
    UP.kind = "term"
    s = opened(api, "term")["session"]
    with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        ws.send_text("t")
        ws.send_bytes(b"b")
        assert [ws.receive_bytes(), ws.receive_bytes()] == [b"echo:t", b"echo:b"]
    assert UP.received[1:] == ["t", b"b"]


def test_upstream_refusal_closes_without_leaking_the_ticket(api):
    c, _ = api
    UP.refuse = True
    s = opened(api)["session"]
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
            ws.receive_bytes()
    assert e.value.code in (1011, 1006) and TICKET not in str(e.value.reason)
    rows = audit_rows()
    assert rows[-1].action == "console-close" and rows[-1].status == "error" and TICKET not in str(rows[-1].detail)
    assert console_router.SESSIONS.active(next(iter(console_router.SESSIONS._active), "")) == 0


def test_wrong_term_login_is_refused(api, monkeypatch):
    c, _ = api
    UP.kind = "term"
    STATE["reply"] = {"port": UP.port, "ticket": "autre-ticket", "user": "kaji@pve!kaji"}
    s = opened(api, "term")["session"]
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
            ws.receive_bytes()


def test_proxmox_closing_ends_the_console_and_is_audited(api):
    c, _ = api
    s = opened(api)["session"]
    with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        ws.receive_bytes()
        ws.send_text("fermer")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_bytes()
    wait_close()
    rows = audit_rows()
    assert [r.action for r in rows] == ["console-open", "console-close"]
    assert rows[1].status == "ok" and "proxmox" in rows[1].detail and TICKET not in str(rows[1].detail)


def test_close_is_audited_with_duration_and_no_content(api):
    c, _ = api
    s = opened(api)["session"]
    with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        ws.receive_bytes()
        ws.send_bytes(b"mot-de-passe-tape-dans-la-console")
        ws.receive_bytes()
    for _ in range(50):
        time.sleep(0.1)
        if any(r.action == "console-close" for r in audit_rows()):
            break
    d = audit_rows()[-1].detail
    assert d.startswith("durée ") and "mot-de-passe" not in d and "client" in d


def test_oversized_message_closes_the_console(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(console_router, "MAX_MESSAGE", 100)
    s = opened(api)["session"]
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
            ws.receive_bytes()
            ws.send_bytes(b"x" * 101)
            ws.receive_bytes()
    wait_close()
    assert UP.received == []                                           # le message trop gros n'a jamais été transmis à Proxmox


def test_idle_console_is_closed(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(console_router, "IDLE_TIMEOUT", 0.2)
    monkeypatch.setattr(console_router, "WATCHDOG_EVERY", 0.1)
    s = opened(api)["session"]
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
            ws.receive_bytes()
            ws.receive_bytes()                                         # rien n'arrive : le garde-fou ferme
    wait_close()
    assert "inactivité" in audit_rows()[-1].detail


def test_maximum_duration_closes_the_console(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(console_router, "MAX_DURATION", 0.2)
    monkeypatch.setattr(console_router, "WATCHDOG_EVERY", 0.1)
    s = opened(api)["session"]
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
            ws.receive_bytes()
            ws.receive_bytes()
    wait_close()
    assert "durée maximale" in audit_rows()[-1].detail


def test_concurrent_console_limit(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(consolespec, "MAX_ACTIVE", 1)
    first = opened(api)["session"]
    second = opened(api)["session"]
    with c.websocket_connect(f"/api/console/{first}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        ws.receive_bytes()
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(f"/api/console/{second}", headers=ORIGIN, subprotocols=["binary"]):
                pass
    wait_close()
    third = opened(api)["session"]                                     # la place est libérée à la fermeture
    with c.websocket_connect(f"/api/console/{third}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        assert ws.receive_bytes() == b"RFB 003.008\n"


# ---------- logique pure --------------------------------------------------------------------------------------------

def _t(i=1):
    return Target(i, "pve1", "lxc", 105, "vnc", 5900, "t", "u")


def test_sessions_are_single_use_and_bound():
    s = ConsoleSessions()
    sid = s.create("A", _t())
    assert s.take(sid, "B") is None and s.take(sid, "A") == _t() and s.take(sid, "A") is None


def test_sessions_expire():
    now = [0.0]
    s = ConsoleSessions(clock=lambda: now[0])
    sid = s.create("A", _t())
    now[0] = consolespec.SESSION_TTL + 1
    assert s.take(sid, "A") is None


def test_active_counter_never_goes_negative_and_caps():
    s = ConsoleSessions()
    assert all(s.acquire("A") for _ in range(consolespec.MAX_ACTIVE)) and not s.acquire("A")
    for _ in range(consolespec.MAX_ACTIVE + 3):
        s.release("A")
    assert s.active("A") == 0 and s.acquire("A")


@pytest.mark.parametrize("origin,host,ok", [
    ("http://kaji.lan:8080", "kaji.lan:8080", True), ("https://KAJI.lan", "kaji.lan", True), ("http://kaji.lan", "kaji.lan:80", False),
    (None, "kaji.lan", False), ("", "kaji.lan", False), ("http://kaji.lan", None, False), ("null", "kaji.lan", False),
    ("http://evil.com", "kaji.lan", False), ("http://kaji.lan.evil.com", "kaji.lan", False), ("http://kaji.lan@evil.com", "kaji.lan", False),
    ("http://evil.com@kaji.lan", "kaji.lan", False), ("javascript://kaji.lan", "kaji.lan", False)])
def test_origin_rule(origin, host, ok):
    assert origin_ok(origin, host) is ok


def test_valid_proxy_reply_accepts_string_ports_only_when_digits():
    assert valid_proxy_reply({"port": "5900", "ticket": "t", "user": "u"}, "vnc") == (5900, "t", "u")
    assert valid_proxy_reply({"port": "59 00", "ticket": "t", "user": "u"}, "vnc") is None
    assert valid_proxy_reply({"port": "５９００", "ticket": "t", "user": "u"}, "vnc") is None


def test_term_not_acknowledged_by_proxmox_is_refused(api):
    c, _ = api
    UP.kind, UP.term_reply = "term", b"ERREUR"
    s = opened(api, "term")["session"]
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
            ws.send_text("0:1:a")
            ws.receive_bytes()
    wait_close()
    assert UP.received == [UP.received[0]]                              # seule l'identification est partie : rien de ce que tape l'utilisateur
    assert audit_rows()[-1].status == "error"


# ---------- console d'un nœud ---------------------------------------------------------------------------------------

def node_url(cid, node="pve1"):
    return f"/api/connections/{cid}/nodes/{node}/console"


def node_opened(api):
    c, cid = api
    r = c.post(node_url(cid), json={"confirm": True})
    assert r.status_code == 201, r.text
    return r.json()


def test_node_console_requires_auth(client):
    assert client.post("/api/connections/1/nodes/pve1/console", json={"confirm": True}).status_code == 401


@pytest.mark.parametrize("body", [{}, {"confirm": False}, {"confirm": None}, {"confirm": "oui"}, {"kind": "term"}])
def test_node_console_requires_explicit_confirmation(api, body):
    c, cid = api
    r = c.post(node_url(cid), json=body)
    assert r.status_code in (400, 422)
    assert not [x for x in CALLS if x[1].endswith("termproxy")]         # rien n'est demandé à Proxmox sans confirmation
    if r.status_code == 400:                                           # refus du serveur : audité
        assert audit_rows()[-1].status == "error"


def test_node_console_returns_session_without_ticket(api):
    r = node_opened(api)
    assert set(r) == {"session", "kind", "expires_in"} and r["kind"] == "term" and TICKET not in str(r)
    assert [x for x in CALLS if x[0] == "POST"] == [("POST", "/nodes/pve1/termproxy", {})]


def test_node_console_is_audited_without_ticket(api):
    node_opened(api)
    rows = audit_rows()
    assert [(r.action, r.status, r.target) for r in rows] == [("console-open", "started", "node/pve1 (term)")]
    assert TICKET not in str(rows[0].detail)


def test_node_console_refused_when_node_does_not_answer(api):
    c, cid = api
    STATE["node_status"] = None
    assert c.post(node_url(cid), json={"confirm": True}).status_code == 409
    assert not [x for x in CALLS if x[1].endswith("termproxy")]


def test_node_console_missing_right_is_reported_and_audited(api):
    c, cid = api
    STATE["node_denied"] = True
    r = c.post(node_url(cid), json={"confirm": True})
    assert r.status_code in (403, 502) and SECRET not in r.text and TICKET not in r.text
    assert audit_rows()[-1].status == "error"


@pytest.mark.parametrize("node", ["pve1;id", "a b", "../x"])
def test_node_console_rejects_bad_node_name(api, node):
    c, cid = api
    assert c.post(node_url(cid, node), json={"confirm": True}).status_code in (404, 422)
    assert not [x for x in CALLS if x[0] == "POST"]


def test_node_console_is_relayed_to_the_node_websocket_with_server_side_login(api):
    c, _ = api
    UP.kind = "term"
    s = node_opened(api)["session"]
    with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        ws.send_text("0:1:\n")
        assert ws.receive_bytes() == b"echo:0:1:\n"                      # le « OK » n'est pas transmis
    assert UP.paths == [f"/api2/json/nodes/pve1/vncwebsocket?port={UP.port}&vncticket={TICKET}"]
    assert UP.received[0] == "kaji@pve!kaji:" + TICKET + "\n"           # identification faite par le serveur
    wait_close()
    rows = audit_rows()
    assert [r.action for r in rows] == ["console-open", "console-close"] and rows[1].target == "node/pve1 (term)"
    assert TICKET not in str(rows[1].detail)


def test_node_console_has_shorter_limits_than_machine_consoles(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(console_router, "IDLE_TIMEOUT", 3600.0)         # machines : large
    monkeypatch.setattr(console_router, "NODE_IDLE_TIMEOUT", 0.2)       # nœud : court
    monkeypatch.setattr(console_router, "WATCHDOG_EVERY", 0.1)
    UP.kind = "term"
    s = node_opened(api)["session"]
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
            ws.send_text("0:1:a")
            ws.receive_bytes()
            ws.receive_bytes()                                         # rien n'arrive : le garde-fou du nœud ferme
    wait_close()
    assert "inactivité" in audit_rows()[-1].detail


def test_node_console_maximum_duration_is_the_node_one(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(console_router, "MAX_DURATION", 3600.0)
    monkeypatch.setattr(console_router, "NODE_MAX_DURATION", 0.2)
    monkeypatch.setattr(console_router, "WATCHDOG_EVERY", 0.1)
    UP.kind = "term"
    s = node_opened(api)["session"]
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/console/{s}", headers=ORIGIN, subprotocols=["binary"]) as ws:
            ws.send_text("0:1:a")
            ws.receive_bytes()
            ws.receive_bytes()
    wait_close()
    assert "durée maximale" in audit_rows()[-1].detail


def test_node_and_machine_consoles_share_the_concurrent_limit(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(consolespec, "MAX_ACTIVE", 1)
    first = opened(api)["session"]                                    # console d'une machine
    second = node_opened(api)["session"]                              # puis d'un nœud : même plafond
    with c.websocket_connect(f"/api/console/{first}", headers=ORIGIN, subprotocols=["binary"]) as ws:
        ws.receive_bytes()
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(f"/api/console/{second}", headers=ORIGIN, subprotocols=["binary"]):
                pass
