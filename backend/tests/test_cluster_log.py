import httpx
import pytest

from app import clusterlogspec as L
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
SEEN: list[httpx.Request] = []
ST: dict = {}
ROWS = [
    {"uid": "a", "time": 1700000100, "pri": 6, "tag": "pvedaemon", "pid": 12, "node": "enzo", "user": "root@pam", "msg": "starting task UPID:enzo:000"},
    {"uid": "b", "time": 1700000300, "pri": 3, "tag": "pmxcfs", "pid": 5, "node": "enzo2", "msg": "erreur"},
    {"uid": "c", "time": 1700000200, "pri": 4, "tag": "corosync", "node": "enzo", "msg": "ligne1\nligne2\x07fin"},
]


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if p != "/cluster/log" or request.method != "GET":
        return httpx.Response(404, json={"data": None})
    if ST.get("fail"):
        return httpx.Response(500, json={"data": None, "message": SECRET})
    qp = dict(request.url.params)
    if set(qp) - {"max"} or not qp.get("max", "1").isdigit() or int(qp["max"]) < 1:       # schéma : seul « max » (entier >= 1)
        return httpx.Response(400, json={"data": None, "message": "Parameter verification failed."})
    return httpx.Response(200, json={"data": ST.get("rows", ROWS)})


@pytest.fixture
def api(client):
    SEEN.clear(); ST.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def get(c, cid, q=""):
    return c.get(f"/api/connections/{cid}/cluster/log{q}")


def test_log_is_sorted_newest_first_and_shaped(api):
    c, cid = api
    r = get(c, cid)
    assert r.status_code == 200
    e = r.json()["entries"]
    assert [x["time"] for x in e] == [1700000300, 1700000200, 1700000100]
    assert e[2] == {"time": 1700000100, "pri": 6, "tag": "pvedaemon", "node": "enzo", "user": "root@pam", "pid": 12, "msg": "starting task UPID:enzo:000"}
    assert e[0]["user"] is None and e[0]["pri"] == 3


def test_control_characters_are_replaced(api):
    c, cid = api
    msg = next(x["msg"] for x in get(c, cid).json()["entries"] if x["tag"] == "corosync")
    assert msg == "ligne1 ligne2 fin" and "\n" not in msg and "\x07" not in msg


def test_max_is_forwarded_and_bounded(api):
    c, cid = api
    assert get(c, cid, "?max=50").status_code == 200 and SEEN[-1].url.params["max"] == "50"
    assert get(c, cid).status_code == 200 and SEEN[-1].url.params["max"] == "100"
    for bad in ("0", "501", "-1", "abc", ""):
        assert get(c, cid, f"?max={bad}").status_code == 422


def test_hostile_entries_are_neutralised(api):
    c, cid = api
    ST["rows"] = [None, "x", 3, {"time": True, "pri": 99, "tag": 5, "node": ["x"], "msg": "m" * 2000, "pid": -1},
                  {"time": 10, "pri": True, "tag": "t" * 100, "user": "u" * 200, "pid": "1"}]
    e = get(c, cid).json()["entries"]
    assert len(e) == 2
    big = next(x for x in e if len(x["msg"]) > 0)
    assert len(big["msg"]) == 500 and big["pri"] == 6 and big["time"] is None and big["tag"] == "" and big["node"] == "" and big["pid"] is None
    other = next(x for x in e if x["time"] == 10)
    assert len(other["tag"]) == 40 and len(other["user"]) == 80 and other["pri"] == 6 and other["pid"] is None


def test_not_a_list_gives_an_empty_log(api):
    c, cid = api
    for junk in (None, {"a": 1}, "texte", 5):
        ST["rows"] = junk
        assert get(c, cid).json() == {"entries": []}


def test_proxmox_error_does_not_leak(api):
    c, cid = api
    ST["fail"] = True
    r = get(c, cid)
    assert r.status_code >= 400 and SECRET not in r.text


def test_requires_a_kaji_login(client):
    assert client.get("/api/connections/1/cluster/log").status_code == 401


def test_shape_limits():
    assert len(L.shape_log([{"time": i, "pri": 6} for i in range(L.MAX_ENTRIES + 50)])) == L.MAX_ENTRIES
