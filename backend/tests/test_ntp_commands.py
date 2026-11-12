import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str]] = []
GOOD = {"name": "mes-serveurs", "sources": [{"host": "0.fr.pool.ntp.org", "kind": "pool"}]}


def _handler(request: httpx.Request) -> httpx.Response:
    CALLS.append((request.method, request.url.path))
    return httpx.Response(200, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    CALLS.clear()
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, node="enzo"):
    return f"/api/connections/{cid}/nodes/{node}/ntp/commands"


def test_generates_source_file_and_commands_without_calling_proxmox(api):
    c, cid = api
    r = c.post(url(cid), json=GOOD)
    assert r.status_code == 200
    d = r.json()
    assert d["file"] == "/etc/chrony/sources.d/mes-serveurs.sources" and d["content"] == "pool 0.fr.pool.ntp.org iburst\n"
    assert d["commands"] == ["grep -E '^sourcedir /etc/chrony/sources.d' /etc/chrony/chrony.conf",
                             "cat > /etc/chrony/sources.d/mes-serveurs.sources <<'KAJI_EOF'\npool 0.fr.pool.ntp.org iburst\nKAJI_EOF",
                             "chronyc reload sources", "chronyc sources -v"]
    assert not CALLS                                            # aucune API NTP chez Proxmox : rien n'est appelé


def test_server_options_and_order(api):
    c, cid = api
    d = c.post(url(cid), json={"name": "x", "sources": [{"host": "Time.Example.ORG", "nts": True}, {"host": "192.168.1.1", "iburst": False},
                                                         {"host": "2001:db8::1"}]}).json()
    assert d["content"] == "server time.example.org iburst nts\nserver 192.168.1.1\nserver 2001:db8::1 iburst\n"


def test_warnings(api):
    c, cid = api
    w = c.post(url(cid), json={"name": "x", "sources": [{"host": "192.168.1.1", "iburst": False, "nts": True}]}).json()["warnings"]
    assert w[0].startswith("la première commande doit afficher la ligne « sourcedir /etc/chrony/sources.d »")
    assert any(x.startswith("NTS") for x in w) and any("sans « iburst »" in x for x in w) and any("réseau local" in x for x in w)
    w = c.post(url(cid), json=GOOD).json()["warnings"]
    assert len(w) == 1


@pytest.mark.parametrize("body", [
    {**GOOD, "name": ""}, {**GOOD, "name": "A"}, {**GOOD, "name": "a;b"}, {**GOOD, "name": "../x"}, {**GOOD, "name": "a\nb"}, {**GOOD, "name": "a" * 61},
    {"name": "x", "sources": []}, {"name": "x"}, {"name": "x", "sources": [{"host": "a.fr"}] * 2},
    {"name": "x", "sources": [{"host": f"h{i}.fr"} for i in range(5)]},
    {"name": "x", "sources": [{"host": "-bad.fr"}]}, {"name": "x", "sources": [{"host": "a.fr iburst\nserver 6.6.6.6"}]},
    {"name": "x", "sources": [{"host": "a.fr;rm"}]}, {"name": "x", "sources": [{"host": "a b.fr"}]}, {"name": "x", "sources": [{"host": ""}]},
    {"name": "x", "sources": [{"host": "a.fr."}]}, {"name": "x", "sources": [{"host": "a..fr"}]}, {"name": "x", "sources": [{"host": "a" * 254}]},
    {"name": "x", "sources": [{"host": "fe80::1%eth0"}]}, {"name": "x", "sources": [{"host": "1.1.1.256"}]}, {"name": "x", "sources": [{"host": "1.1.1.1\n"}]},
    {"name": "x", "sources": [{"host": "$(id).fr"}]}, {"name": "x", "sources": [{"host": "a.fr", "kind": "peer"}]},
    {"name": "x", "sources": [{"host": "a.fr", "kind": "server\nlocal stratum 1"}]}, {"name": "x", "sources": [{"host": "a.fr", "kind": "servers"}]},
    {"name": "x", "sources": [{"host": "a.fr", "kind": "pool x"}]}, {"name": "x", "sources": [{"host": "a.fr", "kind": ""}]},
    {"name": "x", "sources": [{"host": "192.168.1.1", "kind": "pool"}]}, {"name": "x", "sources": [{"host": "2001:db8::1", "kind": "pool"}]},
    {"name": "x", "sources": [{"host": "a.fr", "iburst": "oui"}]}, {"name": "x", "sources": [{"host": "A.fr"}, {"host": "a.FR"}]},
])
def test_validation_refuses_without_any_call(api, body):
    c, cid = api
    assert c.post(url(cid), json=body).status_code == 422
    assert not CALLS


def test_unknown_fields_are_ignored_never_copied(api):
    c, cid = api
    d = c.post(url(cid), json={**GOOD, "extra": "x\nserver 6.6.6.6", "sources": [{"host": "a.fr", "maxpoll": 3, "key": "x"}]}).json()
    assert d["content"] == "server a.fr iburst\n"


def test_no_line_can_close_the_heredoc_early(api):
    c, cid = api
    d = c.post(url(cid), json={"name": "kaji-eof", "sources": [{"host": "kaji-eof.example.org"}]}).json()
    assert d["commands"][1].split("\n").count("KAJI_EOF") == 1


def test_requires_login_and_node_validated(api):
    c, cid = api
    assert c.post(url(cid, node="a;b"), json=GOOD).status_code == 422
    c.post("/api/auth/logout")
    assert c.post(url(cid), json=GOOD).status_code == 401
    assert not CALLS


def test_no_secret_in_answer(api):
    c, cid = api
    assert SECRET not in c.post(url(cid), json=GOOD).text
