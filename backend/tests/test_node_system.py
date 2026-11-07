import httpx
import pytest

from app import systemspec as S
from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
STATE: dict = {}
SEEN: list[httpx.Request] = []

DATA = {
    "status": {"pveversion": "pve-manager/9.1.9", "current-kernel": {"release": "6.17.2-1-pve", "machine": "x86_64"}, "uptime": 1000, "boot-info": {"mode": "efi"}, "rootfs": {"x": 1}},
    "time": {"timezone": "Europe/Paris", "time": 1700000000, "localtime": 1700003600},
    "dns": {"dns1": "1.1.1.1", "dns2": "9.9.9.9", "search": "lan"},
    "services": [{"name": "pveproxy", "desc": "PVE API Proxy", "state": "running", "active-state": "active", "unit-state": "enabled", "service": "pveproxy"},
                 {"name": "bad name;rm", "state": "running"}, "illisible", {"name": "chrony", "state": "stopped"}],
    "apt/update": [{"Package": "openssl", "OldVersion": "3.0.1", "Version": "3.0.2", "Title": "toolkit", "Origin": "Debian", "Description": "long"}, {"Package": None}],
    "apt/versions": [{"Package": "pve-manager", "OldVersion": "9.1.9"}, {"Package": "bash", "OldVersion": "5"}, {"Package": "ceph-common", "Version": "19"}],
    "apt/repositories": {"files": [{"path": "/etc/apt/sources.list.d/pve.sources", "repositories": [{"Types": ["deb"], "URIs": ["http://x"], "Suites": ["trixie"], "Components": ["pve-no-subscription"], "Enabled": 1}]}],
                         "errors": [], "standard-repos": [{"name": "no-subscription", "status": 1}], "digest": "d"},
    "certificates/info": [{"filename": "pve-ssl.pem", "subject": "CN=x", "issuer": "CN=ca", "notbefore": 1700000000, "notafter": 1800000000, "fingerprint": "AA:BB", "san": ["x"], "pem": "-----BEGIN CERTIFICATE-----SECRETPEM", "public-key-type": "rsa"}],
    "disks/list": [{"devpath": "/dev/sda", "model": "SSD", "type": "ssd", "size": 500, "health": "PASSED", "wearout": 98, "used": "LVM", "gpt": 1, "serial": "SN123"},
                   {"devpath": "sda;rm", "model": "x"}, {"devpath": "/dev/sdb", "wearout": 500}],
    "subscription": {"status": "notfound", "serverid": "SERVERID-SECRET", "key": "KEY-SECRET", "message": "m"},
}


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if STATE.get("down"):
        return httpx.Response(500, json={"data": None})
    if p.endswith("/syslog"):
        if "syslog" in STATE.get("forbid", ()):
            return httpx.Response(403, json={"data": None, "message": "Permission check failed"})
        return httpx.Response(200, json={"data": STATE.get("syslog", [{"n": 1, "t": "ligne un"}, {"n": 2, "t": "ligne deux"}, {"t": "sans numéro"}, "x"])})
    for key, val in DATA.items():
        if p.endswith("/" + key):
            if key in STATE.get("forbid", ()):
                return httpx.Response(403, json={"data": None, "message": "Permission check failed (/nodes/n, Sys.Modify)"})
            return httpx.Response(200, json={"data": val})
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


def test_system_shapes_everything(api):
    c, cid = api
    r = c.get(f"/api/connections/{cid}/nodes/pve1/system")
    assert r.status_code == 200
    d = r.json()
    assert all(v["state"] == "ok" for v in d.values())
    assert d["status"]["data"] == {"pveversion": "pve-manager/9.1.9", "kernel": "6.17.2-1-pve", "uptime": 1000, "boot_mode": "efi"}
    assert d["dns"]["data"] == {"search": "lan", "servers": ["1.1.1.1", "9.9.9.9"]}
    assert [s["name"] for s in d["services"]["data"]] == ["chrony", "pveproxy"]          # nom douteux et ligne illisible écartés
    assert d["updates"]["data"] == [{"package": "openssl", "from": "3.0.1", "to": "3.0.2", "title": "toolkit", "origin": "Debian"}]
    assert d["versions"]["data"]["installed"] == 3 and [k["package"] for k in d["versions"]["data"]["key"]] == ["ceph-common", "pve-manager"]
    assert d["repositories"]["data"]["files"][0]["repositories"][0]["enabled"] is True
    assert d["time"]["data"]["timezone"] == "Europe/Paris"
    assert [x["device"] for x in d["disks"]["data"]] == ["/dev/sda", "/dev/sdb"]
    assert d["disks"]["data"][1]["wearout"] is None                                          # 500 % : absurde


def test_no_secret_or_pem_leaks(api):
    c, cid = api
    body = c.get(f"/api/connections/{cid}/nodes/pve1/system").text
    for leak in ("SECRETPEM", "BEGIN CERTIFICATE", "SERVERID-SECRET", "KEY-SECRET", "SN123", SECRET):
        assert leak not in body


def test_forbidden_section_does_not_break_others(api):
    c, cid = api
    STATE["forbid"] = ("apt/update",)
    d = c.get(f"/api/connections/{cid}/nodes/pve1/system").json()
    assert d["updates"] == {"state": "forbidden", "data": None}
    assert d["dns"]["state"] == "ok"
    assert "Permission check" not in str(d)


def test_all_down_is_502(api):
    c, cid = api
    STATE["down"] = True
    assert c.get(f"/api/connections/{cid}/nodes/pve1/system").status_code == 502


def test_requires_login(api):
    c, cid = api
    c.post("/api/auth/logout")
    assert c.get(f"/api/connections/{cid}/nodes/pve1/system").status_code == 401
    assert c.get(f"/api/connections/{cid}/nodes/pve1/syslog").status_code == 401


def test_only_get_requests_sent(api):
    c, cid = api
    c.get(f"/api/connections/{cid}/nodes/pve1/system")
    c.get(f"/api/connections/{cid}/nodes/pve1/syslog")
    assert SEEN and all(r.method == "GET" for r in SEEN)


def test_node_name_is_validated(api):
    c, cid = api
    for bad in ("a;b", "-x", "a%2Fb", "a.b"):
        assert c.get(f"/api/connections/{cid}/nodes/{bad}/system").status_code in (404, 422)
    assert not SEEN


def test_syslog(api):
    c, cid = api
    r = c.get(f"/api/connections/{cid}/nodes/pve1/syslog?limit=50&since=2026-11-01")
    assert r.status_code == 200 and r.json()["lines"] == [{"n": 1, "text": "ligne un"}, {"n": 2, "text": "ligne deux"}]
    q = SEEN[-1].url.params
    assert q["limit"] == "50" and q["since"] == "2026-11-01"


@pytest.mark.parametrize("qs", ["limit=0", "limit=501", "limit=x", "since=2026-11-01;x", "since=x2026-11-01", "since=2026-11-01x"])
def test_syslog_params_validated(api, qs):
    c, cid = api
    assert c.get(f"/api/connections/{cid}/nodes/pve1/syslog?{qs}").status_code == 422
    assert not SEEN


def test_syslog_forbidden_is_clear(api):
    c, cid = api
    STATE["forbid"] = ("syslog",)
    r = c.get(f"/api/connections/{cid}/nodes/pve1/syslog")
    assert r.status_code == 502 and "Droits insuffisants" in r.json()["detail"]


def test_syslog_is_bounded():
    big = [{"n": i, "t": "x" * 5000} for i in range(1, 900)]
    out = S.shape_syslog(big, 10)
    assert len(out) == 10 and len(out[0]["text"]) == 1000


def test_shapes_tolerate_garbage():
    for f in (S.shape_status, S.shape_time, S.shape_dns, S.shape_services, S.shape_updates, S.shape_versions, S.shape_repositories,
              S.shape_certificates, S.shape_disks, S.shape_subscription):
        for junk in (None, 5, "x", [], {}, [None, 3, "x"], {"files": "x", "errors": 3}):
            f(junk)
