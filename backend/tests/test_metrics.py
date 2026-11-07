import math

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.metricspec import GUEST_FIELDS, MAX_POINTS, NODE_FIELDS, shape_points, step_seconds
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}

NODE_ROWS = [
    {"time": 1700000120, "cpu": 0.5, "iowait": 0.01, "loadavg": 1.5, "memused": 8e9, "memtotal": 16e9, "swapused": 1e8, "swaptotal": 8e9, "netin": 100.5, "netout": 200.5,
     "roottotal": 1e11, "pressurecpusome": 0.9, "arcsize": 5, "inconnu": "x"},
    {"time": 1700000060, "cpu": 0.25, "memused": 7e9, "memtotal": 16e9, "netin": 50, "netout": 60},       # plus ancien, placé après : doit être trié
    {"time": 1700000180, "cpu": None, "memused": "abc", "netin": None, "netout": -5},             # trou et valeurs absurdes
    {"time": 1700000120, "cpu": 0.99},                                                                      # doublon de date : le dernier gagne
    {"cpu": 0.5}, {"time": "x"}, {"time": -1, "cpu": 1}, {"time": 99999999999999, "cpu": 1}, "illisible", None, 5,
]
GUEST_ROWS = [
    {"time": 1700000060, "cpu": 0.1, "maxcpu": 2, "mem": 1e9, "maxmem": 2e9, "netin": 10, "netout": 20, "diskread": 30, "diskwrite": 40, "disk": 5, "pressurecpusome": 1},
    {"time": 1700000120},                                                                                     # machine arrêtée : aucune mesure
]
STATE: dict = {}
SEEN: list[httpx.Request] = []


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if STATE.get("fail"):
        return httpx.Response(500, json={"data": None})
    if p.endswith("/rrddata"):
        return httpx.Response(200, json={"data": STATE.get("rows", GUEST_ROWS if "/qemu/" in p or "/lxc/" in p else NODE_ROWS)})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    STATE.clear()
    SEEN.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def node(api, q="", n="pve1"):
    c, cid = api
    return c.get(f"/api/connections/{cid}/nodes/{n}/metrics{q}")


def guest(api, q="", n="pve1", t="qemu", v=100):
    c, cid = api
    return c.get(f"/api/connections/{cid}/guests/{n}/{t}/{v}/metrics{q}")


# ---------- accès, lecture seule ------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/connections/1/nodes/pve1/metrics", "/api/connections/1/guests/pve1/qemu/100/metrics"])
def test_requires_auth(client, path):
    assert client.get(path).status_code == 401


def test_read_only_and_no_secret_leak(api):
    for r in (node(api), guest(api)):
        assert r.status_code == 200 and SECRET not in r.text
    assert SEEN and all(req.method == "GET" for req in SEEN)
    c, cid = api
    assert c.post(f"/api/connections/{cid}/nodes/pve1/metrics", json={}).status_code in (404, 405)


# ---------- nœud ----------------------------------------------------------------------------------------------------

def test_node_points_are_whitelisted_sorted_and_deduplicated(api):
    r = node(api).json()
    assert [p["t"] for p in r["points"]] == [1700000060, 1700000120, 1700000180]
    assert set(r["points"][0]) == {"t", "cpu", "iowait", "load", "mem_used", "mem_total", "swap_used", "swap_total", "net_in", "net_out"}   # liste blanche explicite
    assert r["points"][1]["cpu"] == 0.99                                  # le dernier doublon gagne
    assert r["step"] == 60 and r["timeframe"] == "hour"


def test_absurd_values_become_null_never_zero(api):
    p = node(api).json()["points"][2]
    assert (p["cpu"], p["mem_used"], p["net_in"], p["net_out"]) == (None, None, None, None)


def test_node_values_are_passed_through_unchanged(api):
    p = node(api).json()["points"][0]
    assert (p["cpu"], p["mem_used"], p["mem_total"], p["net_in"]) == (0.25, 7e9, 16e9, 50.0)
    assert p["iowait"] is None and p["load"] is None                      # absents : null, pas 0


def test_node_asks_proxmox_for_the_timeframe_and_average(api):
    node(api, "?timeframe=week")
    req = [r for r in SEEN if r.url.path.endswith("/rrddata")][0]
    assert req.url.path == "/api2/json/nodes/pve1/rrddata" and dict(req.url.params) == {"timeframe": "week", "cf": "AVERAGE"}


def test_default_timeframe_is_hour(api):
    node(api)
    assert dict([r for r in SEEN if r.url.path.endswith("/rrddata")][0].url.params)["timeframe"] == "hour"


# ---------- machine -------------------------------------------------------------------------------------------------

def test_guest_fields_and_stopped_period_is_a_gap(api):
    r = guest(api).json()
    assert set(r["points"][0]) == {"t", "cpu", "cpus", "mem_used", "mem_total", "net_in", "net_out", "disk_read", "disk_write"}
    assert (r["points"][0]["cpu"], r["points"][0]["cpus"], r["points"][0]["disk_write"]) == (0.1, 2.0, 40.0)
    assert all(v is None for k, v in r["points"][1].items() if k != "t")  # arrêtée : un trou, pas des zéros


@pytest.mark.parametrize("gtype", ["qemu", "lxc"])
def test_guest_path(api, gtype):
    guest(api, t=gtype, v=105)
    assert [r.url.path for r in SEEN if r.url.path.endswith("/rrddata")] == [f"/api2/json/nodes/pve1/{gtype}/105/rrddata"]


# ---------- paramètres hostiles -------------------------------------------------------------------------------------

@pytest.mark.parametrize("q", ["?timeframe=hours", "?timeframe=HOUR", "?timeframe=", "?timeframe=hour;id", "?timeframe=../x"])
def test_invalid_timeframe_is_refused_and_nothing_is_sent(api, q):
    assert node(api, q).status_code == 422 and guest(api, q).status_code == 422 and not SEEN


@pytest.mark.parametrize("n", ["a b", "../x", "pve1;id"])
def test_invalid_node_is_refused(api, n):
    assert node(api, n=n).status_code in (404, 422) and guest(api, n=n).status_code in (404, 422) and not SEEN


@pytest.mark.parametrize("t,v", [("spice", 100), ("qemu", 5), ("qemu", 1000000000), ("lxc", "abc")])
def test_invalid_guest_is_refused(api, t, v):
    assert guest(api, t=t, v=v).status_code in (404, 422) and not SEEN


def test_proxmox_error_is_translated_not_an_empty_chart(api):
    STATE["fail"] = True
    assert node(api).status_code in (502, 504) and guest(api).status_code in (502, 504)


def test_an_answer_that_is_not_a_list_gives_no_points(api):
    STATE["rows"] = "n'importe quoi"
    r = node(api).json()
    assert r["points"] == [] and r["step"] is None


# ---------- logique pure --------------------------------------------------------------------------------------------

def test_downsampling_keeps_the_bound_the_order_and_the_gaps():
    rows = [{"time": 1_000_000 + i * 60, "cpu": (None if 100 <= i < 400 else i / 3000)} for i in range(3000)]
    pts = shape_points(rows, {"cpu": "cpu"}, max_points=300)
    assert len(pts) == 300 and [p["t"] for p in pts] == sorted(p["t"] for p in pts)
    assert any(p["cpu"] is None for p in pts)                              # le trou est conservé
    assert all(p["cpu"] is None or 0 <= p["cpu"] <= 1 for p in pts)


def test_downsampling_averages_each_slice():
    rows = [{"time": 1000 + i, "cpu": float(i)} for i in range(10)]
    assert [p["cpu"] for p in shape_points(rows, {"cpu": "cpu"}, max_points=5)] == [0.5, 2.5, 4.5, 6.5, 8.5]


def test_downsampling_ignores_missing_values_inside_a_slice():
    rows = [{"time": 1000, "cpu": 2.0}, {"time": 1001, "cpu": None}, {"time": 1002, "cpu": 4.0}, {"time": 1003}]
    assert shape_points(rows, {"cpu": "cpu"}, max_points=2)[0]["cpu"] == 2.0 and shape_points(rows, {"cpu": "cpu"}, max_points=1)[0]["cpu"] == 3.0


def test_default_bound_applies():
    rows = [{"time": 1000 + i, "cpu": 0.1} for i in range(MAX_POINTS * 3)]
    assert len(shape_points(rows, {"cpu": "cpu"})) == MAX_POINTS


@pytest.mark.parametrize("v", [True, False, "1", None, [1], {"a": 1}, -0.0001, math.inf, -math.inf, math.nan])
def test_non_numeric_negative_and_non_finite_values_are_dropped(v):
    assert shape_points([{"time": 1000, "cpu": v}], {"cpu": "cpu"})[0]["cpu"] is None


def test_zero_is_a_real_value_not_a_gap():
    assert shape_points([{"time": 1000, "cpu": 0}, {"time": 1001, "cpu": 0.0}], {"cpu": "cpu"})[0]["cpu"] == 0.0


def test_step_is_the_median_gap():
    assert step_seconds([{"t": 0}, {"t": 60}, {"t": 120}, {"t": 600}]) == 60
    assert step_seconds([{"t": 0}]) is None and step_seconds([]) is None
