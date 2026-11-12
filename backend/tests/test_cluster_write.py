"""Cluster en écriture (M10-2) : faux Proxmox STRICT (méthode, paramètres, formats et types exacts du schéma officiel, 400/500 sinon)."""
import re
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
ROOT_PW = "Tr3s-Secret-Root-Pw!"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
PHRASE = "COUPURE POSSIBLE"
FP = ":".join(["AB"] * 32)
UPID = "UPID:solo:00001234:0000ABCD:67000000:clustercreate:root@pam:"
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}
LINK = re.compile(r"^address=[0-9a-f.:]+(,priority=[0-9]{1,3})?$")
CREATE_KEYS = {"clustername", "nodeid", "votes"}
JOIN_KEYS = {"hostname", "fingerprint", "password", "nodeid", "votes", "force"}


def fresh(clustered=False, nodes=(("enzo", True, True), ("enzo2", True, False)), quorate=True):
    """`nodes` : (nom, en ligne, local). Isolé : un seul nœud `solo`."""
    ST.clear()
    ST.update(clustered=clustered, quorate=quorate, fail=False, noapply=False, upid=UPID, guests=[], ha=[], hide_ha=False,
              nodes=[{"name": n, "online": on, "local": loc} for n, on, loc in nodes], unreadable_ha=False)
    if not clustered:
        ST["nodes"] = [{"name": "solo", "online": True, "local": True}]
    ST["guests"] = []


def bad(msg, code=400):
    return httpx.Response(code, json={"data": None, "message": msg})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    m = request.method
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    query = dict(request.url.params)
    if m == "GET":
        if p == "/cluster/status":
            rows = [{"type": "node", "name": n["name"], "nodeid": i + 1, **({} if n["online"] is None else {"online": int(n["online"])}), "ip": f"10.0.0.{i + 1}", "local": int(n["local"])}
                    for i, n in enumerate(ST["nodes"])]
            if ST["clustered"]:
                rows.insert(0, {"type": "cluster", "name": "lab", "quorate": int(ST["quorate"]), "nodes": len(rows), "version": 3, "id": "cluster"})
            return httpx.Response(200, json={"data": rows})
        if p == "/cluster/resources":
            assert query == {"type": "vm"}
            return httpx.Response(200, json={"data": [{**g, "id": f"{g['type']}/{g['vmid']}"} for g in ST["guests"]]})
        if p == "/cluster/config/nodes":
            if not ST["clustered"]:
                return bad("no corosync.conf", 500)
            return httpx.Response(200, json={"data": [{"name": n["name"], "nodeid": str(i + 1), "quorum_votes": "1", "ring0_addr": f"10.0.0.{i + 1}"} for i, n in enumerate(ST["nodes"])]})
        if p == "/cluster/ha/resources":
            if ST["unreadable_ha"]:
                return bad("Permission check failed", 403)
            return httpx.Response(200, json={"data": [{"sid": s, "state": "started"} for s in ST["ha"]]})
        return bad("route inconnue du faux Proxmox", 501)
    if ST["fail"]:
        return httpx.Response(403, json={"data": None, "message": SECRET + ROOT_PW})
    CALLS.append((m, p, {**body, **({"__query": query} if query else {})}))
    if p == "/cluster/config" and m == "POST":
        links = {k for k in body if re.fullmatch(r"link[0-7]", k)}
        if set(body) - CREATE_KEYS - links or "clustername" not in body:
            return bad(f"paramètres refusés {sorted(set(body) - CREATE_KEYS - links)}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{0,14}", body["clustername"]):
            return bad("clustername invalide")
        if any(not LINK.fullmatch(body[k]) for k in links) or any(k in body and not body[k].isdigit() for k in ("nodeid", "votes")):
            return bad("format de lien / entier invalide")
        if ST["clustered"]:
            return bad("this node is already part of a cluster", 500)
        if ST["noapply"]:
            return httpx.Response(200, json={"data": None})
        ST["clustered"] = True
        return httpx.Response(200, json={"data": ST["upid"]})
    if p == "/cluster/config/join" and m == "POST":
        links = {k for k in body if re.fullmatch(r"link[0-7]", k)}
        if {"hostname", "fingerprint", "password"} - set(body) or set(body) - JOIN_KEYS - links:
            return bad(f"paramètres refusés {sorted(set(body) - JOIN_KEYS - links)}")
        if not re.fullmatch(r"([A-Fa-f0-9]{2}:){31}[A-Fa-f0-9]{2}", body["fingerprint"]):
            return bad("fingerprint invalide")
        if any(not re.fullmatch(r"address=[0-9a-f.:]+", body[k]) for k in links):     # `priority` est ignoré à l'ajout d'un nœud : Kaji ne l'envoie pas
            return bad("format de lien invalide")
        if ST["clustered"]:
            return bad("this node is already part of a cluster", 500)
        return httpx.Response(200, json={"data": ST["upid"]})
    dm = re.fullmatch(r"/cluster/config/nodes/([A-Za-z0-9\-]+)", p)
    if dm and m == "DELETE":
        if body or query:
            return bad("aucun paramètre attendu")
        names = [n["name"] for n in ST["nodes"]]
        if dm.group(1) not in names:
            return bad("node not found", 500)
        if not ST["noapply"]:
            ST["nodes"] = [n for n in ST["nodes"] if n["name"] != dm.group(1)]
        return httpx.Response(200, json={"data": None})
    return bad("route inconnue du faux Proxmox", 501)


@pytest.fixture
def api(client, monkeypatch):
    CALLS.clear()
    fresh()
    monkeypatch.setattr("app.routers.cluster_write.get_settings", lambda: SimpleNamespace(protected_vmids={116}))
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, p):
    return f"/api/connections/{cid}/cluster/{p}"


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


def writes():
    return [x for x in CALLS if x[0] != "GET"]


def create(c, cid, **kw):
    return c.post(url(cid, "create"), json={"clustername": "lab", "confirm": True, **kw})


def join(c, cid, **kw):
    return c.post(url(cid, "join"), json={"hostname": "10.0.0.50", "fingerprint": FP, "password": ROOT_PW, "confirm": True, "acknowledge_cut_access": True, "type_name": PHRASE, **kw})


def remove(c, cid, node="enzo2", **kw):
    q = {"confirm": "true", "name": node, **kw}
    return c.delete(url(cid, f"nodes/{node}"), params=q)


# ---------------------------------------------------------------- créer
def test_create_sends_exactly_the_documented_parameters(api):
    c, cid = api
    r = create(c, cid, links=[{"link": 0, "address": "192.168.1.10", "priority": 5}, {"link": 1, "address": "10.0.0.7"}], nodeid=1, votes=2)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": "lab", "node": "solo", "upid": UPID, "locks": {"blockers": [], "cut": [], "live": []}}
    assert writes() == [("POST", "/cluster/config", {"clustername": "lab", "link0": "address=192.168.1.10,priority=5", "link1": "address=10.0.0.7", "nodeid": "1", "votes": "2"})]


def test_create_minimal(api):
    c, cid = api
    assert create(c, cid).status_code == 200
    assert writes() == [("POST", "/cluster/config", {"clustername": "lab"})]


def test_create_needs_confirm_and_dry_run_writes_nothing(api):
    c, cid = api
    r = c.post(url(cid, "create"), json={"clustername": "lab"})
    assert r.status_code == 400 and not writes()
    r = c.post(url(cid, "create"), json={"clustername": "lab", "dry_run": True, "links": [{"link": 0, "address": "10.0.0.7"}]})
    assert r.status_code == 200 and r.json()["dry_run"] is True and r.json()["params"] == {"clustername": "lab", "link0": "address=10.0.0.7"} and not writes()


def test_create_is_refused_on_a_node_already_in_a_cluster_even_confirmed(api):
    c, cid = api
    fresh(clustered=True)
    r = create(c, cid)
    assert r.status_code == 409 and "lab" in r.json()["detail"] and not writes()
    assert audit_pairs(c)[-1] == ("cluster-create", "error")
    d = c.post(url(cid, "create"), json={"clustername": "x", "dry_run": True}).json()                 # l'aperçu dit pourquoi, sans refuser
    assert d["locks"]["blockers"]


@pytest.mark.parametrize("name", ["", "a" * 16, "-lab", "lab_x", "lab.x", "lab x", "lab\n", "Café"])
def test_create_cluster_name_is_validated(api, name):
    c, cid = api
    assert create(c, cid, clustername=name).status_code == 422 and not writes()


@pytest.mark.parametrize("links", [[{"link": 8, "address": "10.0.0.7"}], [{"link": -1, "address": "10.0.0.7"}], [{"link": 0, "address": "127.0.0.1"}],
                                   [{"link": 0, "address": "0.0.0.0"}], [{"link": 0, "address": "169.254.1.1"}], [{"link": 0, "address": "224.0.0.1"}],
                                   [{"link": 0, "address": "::1"}], [{"link": 0, "address": "pve.example.org"}], [{"link": 0, "address": "10.0.0.7,priority=1"}],
                                   [{"link": 0, "address": "10.0.0.7", "priority": 256}], [{"link": 0, "address": "10.0.0.7", "priority": -1}],
                                   [{"link": 0, "address": "10.0.0.7"}, {"link": 0, "address": "10.0.0.8"}], [{"link": 0, "address": "10.0.0.7"}, {"link": 1, "address": "10.0.0.7"}],
                                   [{"link": 0, "address": "10.0.0.7"}] * 9, [{"link": "0", "address": "10.0.0.7"}]])
def test_create_links_are_validated(api, links):
    c, cid = api
    assert create(c, cid, links=links).status_code == 422 and not writes()


@pytest.mark.parametrize("extra", [{"nodeid": 0}, {"nodeid": 10001}, {"votes": 0}, {"votes": 11}, {"nodeid": "1"}, {"votes": True}, {"confirm": "yes"}])
def test_create_numbers_are_bounded_and_strict(api, extra):
    c, cid = api
    assert create(c, cid, **extra).status_code == 422 and not writes()


def test_create_ipv6_link_is_accepted_and_normalised(api):
    c, cid = api
    assert create(c, cid, links=[{"link": 0, "address": "FD00:0:0:0:0:0:0:5"}]).status_code == 200
    assert writes()[0][2]["link0"] == "address=fd00::5"


def test_create_ignores_unknown_fields(api):
    c, cid = api
    assert create(c, cid, force=1, nodeid=2, voteX=9, delete="all").status_code == 200
    assert writes()[0][2] == {"clustername": "lab", "nodeid": "2"}


def test_create_drops_a_reply_that_is_not_an_upid(api):
    c, cid = api
    ST["upid"] = "<script>x</script>"
    r = create(c, cid)
    assert r.status_code == 200 and r.json()["upid"] is None


# ---------------------------------------------------------------- joindre
def test_join_sends_the_documented_parameters_and_the_password_only_there(api):
    c, cid = api
    r = join(c, cid, links=[{"link": 0, "address": "10.0.0.9", "priority": 7}], nodeid=3, votes=1)
    assert r.status_code == 200, r.text
    assert writes() == [("POST", "/cluster/config/join", {"hostname": "10.0.0.50", "fingerprint": FP, "password": ROOT_PW, "link0": "address=10.0.0.9", "nodeid": "3", "votes": "1"})]
    j = r.json()
    assert j == {"joining": "solo", "via": "10.0.0.50", "upid": UPID, "locks": j["locks"]} and ROOT_PW not in r.text and SECRET not in r.text


def test_join_never_leaks_the_password_anywhere(api):
    c, cid = api
    for body in (dict(dry_run=True), dict(), dict(type_name=None)):                           # aperçu, succès, refus de verrou
        r = join(c, cid, **body)
        assert ROOT_PW not in r.text
    assert join(c, cid, password="x" * 129).status_code == 422                                   # refus de validation : la valeur n'est pas renvoyée
    ST["fail"] = True
    r = join(c, cid)
    assert r.status_code in (502, 403) and ROOT_PW not in r.text and SECRET not in r.text
    assert ROOT_PW not in c.get("/api/audit").text and SECRET not in c.get("/api/audit").text
    detail = " ".join(a.get("detail") or "" for a in c.get("/api/audit").json())
    assert "défini" in detail


def test_join_dry_run_shows_the_lock_and_hides_the_password(api):
    c, cid = api
    r = c.post(url(cid, "join"), json={"hostname": "10.0.0.50", "fingerprint": FP, "password": ROOT_PW, "dry_run": True})
    j = r.json()
    assert r.status_code == 200 and j["dry_run"] and j["phrase"] == PHRASE and j["locks"]["cut"] and j["params"]["password"].startswith("défini") and not writes()
    assert ROOT_PW not in r.text


def test_join_needs_confirm_and_the_phrase(api):
    c, cid = api
    base = {"hostname": "10.0.0.50", "fingerprint": FP, "password": ROOT_PW}
    assert c.post(url(cid, "join"), json={**base, "acknowledge_cut_access": True, "type_name": PHRASE}).status_code == 400
    for extra in ({}, {"acknowledge_cut_access": True}, {"type_name": PHRASE}, {"acknowledge_cut_access": True, "type_name": "coupure possible"},
                  {"acknowledge_cut_access": True, "type_name": PHRASE + " "}):
        r = c.post(url(cid, "join"), json={**base, "confirm": True, **extra})
        assert r.status_code == 409 and PHRASE in r.json()["detail"], extra
    assert not writes()


def test_join_is_refused_when_the_node_hosts_machines_even_with_every_unlock(api):
    c, cid = api
    ST["guests"] = [{"vmid": 100, "type": "qemu", "node": "solo", "name": "web", "status": "running", "template": 0}]
    r = join(c, cid, acknowledge_guests=True)
    assert r.status_code == 409 and "machine" in r.json()["detail"] and not writes()
    assert audit_pairs(c)[-1] == ("cluster-join", "error")


def test_join_is_refused_on_a_node_already_in_a_cluster(api):
    c, cid = api
    fresh(clustered=True)
    r = join(c, cid)
    assert r.status_code == 409 and not writes()


@pytest.mark.parametrize("host", ["solo", "SOLO", "10.0.0.1"])
def test_join_refuses_to_contact_itself(api, host):
    c, cid = api
    assert join(c, cid, hostname=host).status_code == 409 and not writes()


@pytest.mark.parametrize("host", ["localhost", "a.localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "::1", "224.0.0.1", "", "a b", "x" * 254, "10.0.0.1/24", "http://10.0.0.5"])
def test_join_hostname_is_validated(api, host):
    c, cid = api
    assert join(c, cid, hostname=host).status_code == 422 and not writes()


@pytest.mark.parametrize("fp", ["", FP.lower().replace(":", ""), FP[:-3], FP + ":AB", "ZZ" + FP[2:], FP + "\n"])
def test_join_fingerprint_is_validated(api, fp):
    c, cid = api
    assert join(c, cid, fingerprint=fp).status_code == 422 and not writes()


@pytest.mark.parametrize("pw", ["", "a\nb", "a\x00b", "x" * 129, None, 12345])
def test_join_password_is_validated(api, pw):
    c, cid = api
    r = join(c, cid, password=pw)
    assert r.status_code == 422 and not writes()


def test_join_lowercase_fingerprint_is_accepted(api):
    c, cid = api
    assert join(c, cid, fingerprint=FP.lower()).status_code == 200


# ---------------------------------------------------------------- retirer
def test_remove_below_three_nodes_needs_the_phrase(api):
    c, cid = api
    fresh(clustered=True, nodes=(("enzo", True, True), ("enzo2", False, False)))
    r = remove(c, cid)
    assert r.status_code == 409 and PHRASE in r.json()["detail"] and not writes()
    r = remove(c, cid, acknowledge_cut_access="true", type_name="nope")
    assert r.status_code == 409 and not writes()
    r = remove(c, cid, acknowledge_cut_access="true", type_name=PHRASE)
    assert r.status_code == 200 and writes() == [("DELETE", "/cluster/config/nodes/enzo2", {})]
    assert [n["name"] for n in ST["nodes"]] == ["enzo"]


def test_remove_from_a_three_node_cluster_still_needs_the_phrase(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", True, False), ("c", False, False)))
    r = remove(c, cid, "c")
    assert r.status_code == 409 and PHRASE in r.json()["detail"] and "2 nœud" in r.json()["detail"] and not writes()
    assert remove(c, cid, "c", acknowledge_cut_access="true", type_name=PHRASE).status_code == 200


def test_remove_a_node_whose_state_is_unknown_is_refused(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", True, False), ("c", True, False), ("d", None, False)))
    r = remove(c, cid, "d", acknowledge_guests="true", acknowledge_cut_access="true", type_name=PHRASE)
    assert r.status_code == 409 and "inconnu" in r.json()["detail"] and not writes()


def test_remove_from_a_four_node_cluster_needs_no_phrase(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", True, False), ("c", True, False), ("d", False, False)))
    r = remove(c, cid, "d")
    assert r.status_code == 200 and r.json()["locks"]["cut"] == [] and writes() == [("DELETE", "/cluster/config/nodes/d", {})]


def test_remove_needs_confirm_and_the_retyped_name(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", True, False), ("c", True, False), ("d", False, False)))
    assert c.delete(url(cid, "nodes/d"), params={"name": "d"}).status_code == 400
    assert c.delete(url(cid, "nodes/d"), params={"confirm": "true"}).status_code == 400
    assert c.delete(url(cid, "nodes/d"), params={"confirm": "true", "name": "D"}).status_code == 400
    assert c.delete(url(cid, "nodes/d"), params={"confirm": "true", "name": "c"}).status_code == 400
    assert not writes()


def test_remove_an_online_node_is_refused_even_with_every_unlock(api):
    c, cid = api
    fresh(clustered=True)
    r = remove(c, cid, "enzo2", acknowledge_cut_access="true", type_name=PHRASE, acknowledge_guests="true")
    assert r.status_code == 409 and "EN LIGNE" in r.json()["detail"] and not writes()
    assert audit_pairs(c)[-1] == ("cluster-remove-node", "error")


def test_remove_the_node_kaji_is_connected_to_is_refused(api):
    c, cid = api
    fresh(clustered=True, nodes=(("enzo", False, True), ("enzo2", True, False)))
    r = remove(c, cid, "enzo", acknowledge_cut_access="true", type_name=PHRASE)
    assert r.status_code == 409 and "connecté" in r.json()["detail"] and not writes()


def test_remove_without_quorum_is_refused(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", False, False), ("c", False, False)), quorate=False)
    r = remove(c, cid, "b", acknowledge_cut_access="true", type_name=PHRASE)
    assert r.status_code == 409 and "quorum" in r.json()["detail"] and not writes()


def test_remove_unknown_node_and_isolated_node(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", False, False)))
    assert remove(c, cid, "zzz").status_code == 404
    fresh()
    assert remove(c, cid, "solo").status_code == 409
    assert not writes()


def test_remove_node_with_machines_needs_the_acknowledgement(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", True, False), ("c", True, False), ("d", False, False)))
    ST["guests"] = [{"vmid": 100, "type": "qemu", "node": "d", "name": "web", "status": "stopped", "template": 0}, {"vmid": 101, "type": "lxc", "node": "a", "name": "ct", "status": "running", "template": 0}]
    ST["ha"] = ["vm:100", "ct:101"]
    r = remove(c, cid, "d")
    assert r.status_code == 409 and "100" in r.json()["detail"] and "acknowledge_guests" in r.json()["detail"] and not writes()
    r = remove(c, cid, "d", acknowledge_guests="true")
    assert r.status_code == 200 and r.json()["guests"] == [100] and r.json()["ha_resources"] == ["vm:100"]
    assert writes() == [("DELETE", "/cluster/config/nodes/d", {})]


def test_remove_node_that_holds_a_protected_machine_is_refused_even_with_every_unlock(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", True, False), ("c", True, False), ("d", False, False)))
    ST["guests"] = [{"vmid": 116, "type": "lxc", "node": "d", "name": "kaji-ct", "status": "stopped", "template": 0}]
    r = remove(c, cid, "d", acknowledge_guests="true", acknowledge_cut_access="true", type_name=PHRASE)
    assert r.status_code == 403 and "116" in r.json()["detail"] and not writes()
    d = c.delete(url(cid, "nodes/d"), params={"dry_run": "true"})                                  # même l'aperçu refuse : rien à montrer qui puisse partir
    assert d.status_code == 403


def test_remove_dry_run_writes_nothing_and_needs_no_name(api):
    c, cid = api
    fresh(clustered=True, nodes=(("enzo", True, True), ("enzo2", False, False)))
    r = c.delete(url(cid, "nodes/enzo2"), params={"dry_run": "true"})
    j = r.json()
    assert r.status_code == 200 and j["dry_run"] and j["phrase"] == PHRASE and j["locks"]["blockers"] == [] and not writes()
    fresh(clustered=True)
    j = c.delete(url(cid, "nodes/enzo2"), params={"dry_run": "true"}).json()
    assert j["locks"]["blockers"] and not writes()                                                 # l'aperçu montre le refus sans lever d'erreur


def test_remove_that_proxmox_did_not_apply_is_reported(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", True, False), ("c", True, False), ("d", False, False)))
    ST["noapply"] = True
    r = remove(c, cid, "d")
    assert r.status_code == 502 and audit_pairs(c)[-1] == ("cluster-remove-node", "error")


def test_remove_survives_an_unreadable_ha(api):
    c, cid = api
    fresh(clustered=True, nodes=(("a", True, True), ("b", True, False), ("c", True, False), ("d", False, False)))
    ST["unreadable_ha"] = True
    r = remove(c, cid, "d")
    assert r.status_code == 200 and r.json()["ha_resources"] == []
    assert ("cluster-remove-node", "error") not in audit_pairs(c)                                   # la lecture HA ratée n'est pas une erreur de l'écriture


@pytest.mark.parametrize("node", ["a b", "-x", "a_b", "x" * 64, "a.b"])
def test_remove_node_name_is_validated(api, node):
    c, cid = api
    assert c.delete(url(cid, f"nodes/{node}"), params={"confirm": "true", "name": node}).status_code in (404, 422) and not writes()


# ---------------------------------------------------------------- audit, secrets, accès
def test_every_write_and_refusal_is_audited_without_secret(api):
    c, cid = api
    assert create(c, cid).status_code == 200
    fresh()
    assert join(c, cid, type_name=None).status_code == 409
    assert join(c, cid).status_code == 200
    fresh(clustered=True, nodes=(("enzo", True, True), ("enzo2", False, False)))
    assert remove(c, cid, acknowledge_cut_access="true", type_name=PHRASE).status_code == 200
    pairs = audit_pairs(c)
    assert ("cluster-create", "started") in pairs and ("cluster-join", "error") in pairs and ("cluster-join", "started") in pairs and ("cluster-remove-node", "started") in pairs
    text = c.get("/api/audit").text
    assert SECRET not in text and ROOT_PW not in text and FP not in text


def test_proxmox_failure_gives_a_fixed_message_without_the_reply(api):
    c, cid = api
    ST["fail"] = True
    for r in (create(c, cid), remove(c, cid)):
        assert r.status_code in (403, 404, 409, 502) and SECRET not in r.text and ROOT_PW not in r.text
    r = c.post(url(cid, "create"), json={"clustername": "lab", "confirm": True})
    assert SECRET not in r.text and SECRET not in c.get("/api/audit").text


def test_every_route_needs_a_session(client):
    for m, p in (("post", "create"), ("post", "join"), ("delete", "nodes/enzo2")):
        assert getattr(client, m)(url(1, p)).status_code == 401
