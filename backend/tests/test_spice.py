"""Console SPICE : fichier `.vv` construit à partir de la réponse (simulée) de Proxmox. Le faux Proxmox est strict : méthode, chemin et paramètres exacts."""
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.deps import get_client_factory
from app.main import app
from app.models import AuditLog
from app.proxmox import ProxmoxClient
from app.spicespec import SpiceError, build_vv, proxy_host

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
TICKET = "PVESPICE:6AEE5C1A:Tick3t/Secr3t+Value=="
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CA = "-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIUAAAA\nAAAA+/==\n-----END CERTIFICATE-----\n"
GOOD = {"type": "spice", "title": "VM 100", "host": "pve1.lab", "tls-port": 61000, "password": TICKET, "proxy": "http://10.0.0.5:3128", "ca": CA,
        "host-subject": "OU=PVE Cluster Node,O=Proxmox Virtual Environment,CN=pve1.lab", "delete-this-file": 1,
        "secure-attention": "Ctrl+Alt+Ins", "release-cursor": "Ctrl+Alt+R", "toggle-fullscreen": "Shift+F11"}
STATE: dict = {}
CALLS: list = []


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    q = dict(request.url.params)
    body = dict(httpx.QueryParams(request.content.decode())) if request.content else {}
    CALLS.append((request.method, p, q, body))
    if p.endswith("/status/current"):
        return httpx.Response(200, json={"data": {"status": STATE.get("status", "running"), "template": STATE.get("template", 0)}})
    if p == "/nodes/pve1/qemu/100/config":
        if q.get("current") != "1":
            return httpx.Response(400, json={"data": None, "message": "current=1 attendu"})
        return httpx.Response(200, json={"data": STATE.get("config", {"vga": "qxl"})})
    if p in ("/nodes/pve1/qemu/100/spiceproxy", "/nodes/pve1/lxc/105/spiceproxy"):
        if request.method != "POST" or set(body) - {"proxy"}:
            return httpx.Response(400, json={"data": None, "message": "paramètre inconnu"})
        if STATE.get("denied"):
            return httpx.Response(403, json={"data": None, "message": "Permission check failed (/vms/100, VM.Console)"})
        return httpx.Response(200, json={"data": STATE.get("reply", GOOD)})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    STATE.clear()
    CALLS.clear()
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, gtype="qemu", vmid=100):
    return f"/api/connections/{cid}/guests/pve1/{gtype}/{vmid}/spice"


def audit_rows():
    with Session(get_engine()) as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.action == "spice-open").order_by(AuditLog.id)))


def posts():
    return [c for c in CALLS if c[0] == "POST"]


def test_vm_gets_a_vv_file(api):
    c, cid = api
    r = c.post(url(cid))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-virt-viewer")
    assert r.headers["content-disposition"] == 'attachment; filename="kaji-qemu-100.vv"' and r.headers["cache-control"] == "no-store"      # posé par le middleware global : le ticket n'est jamais mis en cache
    lines = r.text.splitlines()
    assert lines[0] == "[virt-viewer]" and "type=spice" in lines and "tls-port=61000" in lines and f"password={TICKET}" in lines
    assert "ca=-----BEGIN CERTIFICATE-----\\nMIIBszCCAVmgAwIBAgIUAAAA\\nAAAA+/==\\n-----END CERTIFICATE-----\\n" in lines     # sauts de ligne écrits en `\n`
    assert len([x for x in lines if x.startswith("[")]) == 1                                                                      # une seule section
    assert posts() == [("POST", "/nodes/pve1/qemu/100/spiceproxy", {}, {"proxy": "10.0.0.5"})]                                      # proxy = hôte de la connexion


def test_container_needs_no_display_card(api):
    c, cid = api
    r = c.post(url(cid, "lxc", 105))
    assert r.status_code == 200 and "kaji-lxc-105.vv" in r.headers["content-disposition"]
    assert not [x for x in CALLS if x[1].endswith("/config")]                      # la carte d'affichage ne concerne que les VM


@pytest.mark.parametrize("cfg", [{}, {"vga": "std"}, {"vga": "vmware"}, {"vga": "serial0"}, {"vga": "virtio"}, {"name": "x"}, {"vga": "type=std"}, {"vga": "type=virtio,memory=32"}, {"vga": "memory=32"}, {"vga": "type=nopeqxl"}, {"vga": "clipboard=vnc"}, {"vga": 5}])
def test_vm_without_qxl_is_refused_before_asking_proxmox(api, cfg):
    c, cid = api
    STATE["config"] = cfg
    r = c.post(url(cid))
    assert r.status_code == 409 and "qxl" in r.json()["detail"]
    assert not posts()


@pytest.mark.parametrize("vga", ["qxl", "qxl2", "qxl3", "qxl4", "qxl,memory=64", "type=qxl", "type=qxl2,memory=32", "type=qxl,clipboard=vnc"])      # « type=qxl » est la forme que Kaji écrit (constaté en réel)
def test_every_qxl_variant_is_accepted(api, vga):
    c, cid = api
    STATE["config"] = {"vga": vga}
    assert c.post(url(cid)).status_code == 200


@pytest.mark.parametrize("status,template", [("stopped", 0), ("paused", 0), ("running", 1)])
def test_stopped_paused_or_template_machine_is_refused(api, status, template):
    c, cid = api
    STATE.update(status=status, template=template)
    assert c.post(url(cid)).status_code == 409 and not posts()


def test_proxmox_refusal_is_relayed_without_a_file(api):
    c, cid = api
    STATE["denied"] = True
    r = c.post(url(cid))
    assert r.status_code == 502 and "VM.Console" not in r.text and TICKET not in r.text         # Kaji traduit le refus de Proxmox en message fixe
    assert [x.status for x in audit_rows()] == ["error"]


def test_audit_never_holds_the_ticket_or_the_certificate(api):
    c, cid = api
    c.post(url(cid))
    rows = audit_rows()
    assert [(r.action, r.status, r.target) for r in rows] == [("spice-open", "started", "qemu/100@pve1 (spice)")]
    assert TICKET not in str(rows[0].detail) and "CERTIFICATE" not in str(rows[0].detail)


def test_requires_login(client):
    assert client.post("/api/connections/1/guests/pve1/qemu/100/spice").status_code == 401


@pytest.mark.parametrize("node,vmid", [("pve1;x", 100), ("../x", 100), ("pve1", 99), ("pve1", 0)])
def test_node_and_id_are_validated(api, node, vmid):
    c, cid = api
    assert c.post(f"/api/connections/{cid}/guests/{node}/qemu/{vmid}/spice").status_code in (404, 422) and not CALLS


def test_bad_type_is_refused(api):
    c, cid = api
    assert c.post(f"/api/connections/{cid}/guests/pve1/node/100/spice").status_code == 422 and not CALLS


# --- build_vv : la réponse de Proxmox n'est jamais recopiée telle quelle
def test_unknown_keys_are_dropped():
    out = build_vv({**GOOD, "evil": "x", "[other]": "y", "usb-filter": "-1"})
    assert "evil" not in out and "[other]" not in out and "usb-filter" not in out


@pytest.mark.parametrize("key", ["host", "title", "password", "proxy", "host-subject", "secure-attention", "release-cursor", "toggle-fullscreen"])
@pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\r\n[x]", "x\x00", "é"])
def test_control_characters_and_non_ascii_are_refused(key, bad):
    with pytest.raises(SpiceError):
        build_vv({**GOOD, key: bad})


def test_section_injection_through_the_certificate_is_refused():
    for bad in ["x\n[autre]\nkey=1", "x;y", "x\x00", "x\r\n"]:
        with pytest.raises(SpiceError):
            build_vv({**GOOD, "ca": bad})
    assert "\n[" not in build_vv(GOOD).split("ca=")[1].split("\n")[0]


@pytest.mark.parametrize("missing", ["type", "host", "tls-port", "password"])
def test_incomplete_reply_is_refused(missing):
    d = dict(GOOD); d.pop(missing)
    with pytest.raises(SpiceError):
        build_vv(d)


@pytest.mark.parametrize("port", [0, 65536, -1, "x", "1e3", "12 ", None, True, 70000, ""])
def test_port_is_a_valid_tcp_port(port):
    with pytest.raises(SpiceError):
        build_vv({**GOOD, "tls-port": port})


@pytest.mark.parametrize("reply", [None, [], "texte", 5, {"type": "vnc", "host": "h", "tls-port": 1, "password": "p"}])
def test_non_dict_or_wrong_type_is_refused(reply):
    with pytest.raises(SpiceError):
        build_vv(reply)


@pytest.mark.parametrize("proxy", ["ftp://x:3128", "http://", "javascript:1", "http://a b", "http://x\ny", "//x"])
def test_proxy_must_be_an_http_url(proxy):
    with pytest.raises(SpiceError):
        build_vv({**GOOD, "proxy": proxy})


def test_error_messages_never_contain_the_value():
    with pytest.raises(SpiceError) as e:
        build_vv({**GOOD, "password": TICKET + "\n"})
    assert TICKET not in str(e.value)


def test_hostile_reply_through_the_route_gives_502_and_no_file(api):
    c, cid = api
    STATE["reply"] = {**GOOD, "host": "evil\n[x]"}
    r = c.post(url(cid))
    assert r.status_code == 502 and TICKET not in r.text and "evil" not in r.text
    assert audit_rows()[0].status == "error" and "evil" not in str(audit_rows()[0].detail)


@pytest.mark.parametrize("host,ok", [("10.0.0.5", True), ("pve1.lab", True), ("[fe80::1]", True), ("a b", False), ("a;b", False), ("", False), ("x" * 300, False), ("é.lab", False)])
def test_proxy_host_only_accepts_safe_names(host, ok):
    assert (proxy_host(host) == host) is ok


@pytest.mark.parametrize("key", ["title", "host", "password", "proxy", "type"])
def test_numbers_are_only_accepted_where_they_make_sense(key):
    with pytest.raises(SpiceError):
        build_vv({**GOOD, key: 5})


def test_booleans_are_not_ports_but_flags_may_be_numbers():
    assert "delete-this-file=1" in build_vv({**GOOD, "delete-this-file": True})
    assert "tls-port=61000" in build_vv({**GOOD, "tls-port": "61000"})
