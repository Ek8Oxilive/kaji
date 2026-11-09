"""Réplication en écriture (M8-3) : faux Proxmox STRICT (méthode, paramètres, types, digest ; 400 sinon)."""
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.replwrite import next_job_id

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[tuple[str, str, dict]] = []
ST: dict = {}
POST_KEYS = {"id", "type", "target", "schedule", "rate", "comment", "disable"}
PUT_KEYS = {"schedule", "rate", "comment", "disable", "delete", "digest"}


def fresh(zfs=True):
    ST.clear()
    ST.update(noapply=False, fail=False, digest="d" * 40, jobs={})
    ST["storages"] = [{"storage": "local", "type": "dir"}, {"storage": "local-lvm", "type": "lvmthin"}] + ([{"storage": "tank", "type": "zfspool"}] if zfs else [])
    ST["guests"] = [{"vmid": 100, "type": "qemu", "node": "enzo", "name": "web", "status": "running", "template": 0},
                    {"vmid": 101, "type": "lxc", "node": "enzo2", "name": "ct", "status": "running", "template": 0},
                    {"vmid": 102, "type": "qemu", "node": "enzo", "name": "tpl", "status": "stopped", "template": 1},
                    {"vmid": 116, "type": "lxc", "node": "enzo", "name": "kaji-ct", "status": "running", "template": 0}]
    ST["configs"] = {100: {"name": "web", "scsi0": "tank:vm-100-disk-0,size=8G", "ide2": "local:iso/x.iso,media=cdrom", "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0"},
                     101: {"hostname": "ct", "rootfs": "local-lvm:vm-101-disk-0,size=4G"},
                     116: {"hostname": "kaji-ct", "rootfs": "tank:subvol-116-disk-0,size=4G"}}


def add_job(jid="100-0", **kw):
    guest = int(jid.split("-")[0])
    src = next(g["node"] for g in ST["guests"] if g["vmid"] == guest)
    ST["jobs"][jid] = {"id": jid, "guest": guest, "type": "local", "source": src, "target": "enzo2" if src == "enzo" else "enzo", "schedule": "*/15", **kw}


def bad(msg):
    return httpx.Response(400, json={"data": None, "message": msg})


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    m = request.method
    body = {k: v[0] for k, v in parse_qs(request.content.decode(), keep_blank_values=True).items()}
    query = dict(request.url.params)
    if m == "GET":
        if p == "/cluster/replication":
            return httpx.Response(200, json={"data": [{**j, "digest": ST["digest"]} for j in ST["jobs"].values()]})
        if p == "/cluster/status":
            return httpx.Response(200, json={"data": [{"type": "cluster", "name": "lab", "quorate": 1}, {"type": "node", "name": "enzo", "online": 1}, {"type": "node", "name": "enzo2", "online": 0 if ST.get("offline") else 1}]})
        if p == "/cluster/resources":
            return httpx.Response(200, json={"data": [{**g, "id": f"{g['type']}/{g['vmid']}"} for g in ST["guests"]]})
        if p == "/storage":
            return httpx.Response(200, json={"data": ST["storages"]})
        for g in ST["guests"]:
            if p == f"/nodes/{g['node']}/{g['type']}/{g['vmid']}/config":
                assert query == {"current": "1"}
                return httpx.Response(200, json={"data": ST["configs"].get(g["vmid"], {})})
        return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})
    if ST["fail"]:
        return httpx.Response(403, json={"data": None, "message": SECRET})
    CALLS.append((m, p, {**body, **({"__query": query} if query else {})}))
    if p == "/cluster/replication" and m == "POST":
        if set(body) - POST_KEYS or not {"id", "type", "target"} <= set(body) or body["type"] != "local":
            return bad(f"paramètres refusés {sorted(set(body) - POST_KEYS)}")
        if "disable" in body and body["disable"] not in ("0", "1"):
            return bad("disable doit être 0/1")
        if "rate" in body and float(body["rate"]) < 1:
            return bad("rate < 1")
        if body["id"] in ST["jobs"]:
            return bad("job existant")
        if not ST["noapply"]:
            guest = int(body["id"].split("-")[0])
            src = next(g["node"] for g in ST["guests"] if g["vmid"] == guest)
            if body["target"] == src:
                return bad("la cible ne peut pas être la source")
            j = {"id": body["id"], "guest": guest, "type": "local", "source": src, "target": body["target"]}
            for k in ("schedule", "comment"):
                if k in body:
                    j[k] = body[k]
            if "rate" in body:
                j["rate"] = float(body["rate"])
            if "disable" in body:
                j["disable"] = int(body["disable"])
            ST["jobs"][body["id"]] = j
        return httpx.Response(200, json={"data": None})
    if p.startswith("/cluster/replication/"):
        j = ST["jobs"].get(p.removeprefix("/cluster/replication/"))
        if j is None:
            return httpx.Response(500, json={"data": None, "message": "no such job"})
        if m == "PUT":
            if set(body) - PUT_KEYS:
                return bad(f"paramètres refusés {sorted(set(body) - PUT_KEYS)}")
            if body.get("digest") != ST["digest"]:
                return bad("digest différent")
            dl = [x for x in body.get("delete", "").split(",") if x]
            if set(dl) - {"schedule", "rate", "comment", "disable"}:
                return bad("delete invalide")
            if not ST["noapply"]:
                for k, v in body.items():
                    if k not in ("delete", "digest"):
                        j[k] = float(v) if k == "rate" else int(v) if k == "disable" else v
                for k in dl:
                    j.pop(k, None)
            return httpx.Response(200, json={"data": None})
        if m == "DELETE":
            if body or set(query) != {"keep"} or query["keep"] not in ("0", "1"):
                return bad("keep=0|1 attendu")
            if not ST["noapply"]:
                j["remove_job"] = "local" if query["keep"] == "1" else "full"
            return httpx.Response(200, json={"data": None})
    if m == "POST" and p.endswith("/schedule_now"):
        node, _, rest = p.removeprefix("/nodes/").partition("/replication/")
        jid = rest.removesuffix("/schedule_now")
        if body or jid not in ST["jobs"] or ST["jobs"][jid]["source"] != node:
            return bad("schedule_now : nœud ou job invalide")
        return httpx.Response(200, json={"data": None})
    return httpx.Response(501, json={"data": None, "message": "route inconnue du faux Proxmox"})


@pytest.fixture
def api(client, monkeypatch):
    CALLS.clear()
    fresh()
    monkeypatch.setattr("app.routers.ha_write.get_settings", lambda: SimpleNamespace(protected_vmids={116}))
    app.dependency_overrides[get_client_factory] = lambda: (lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def url(cid, path=""):
    return f"/api/connections/{cid}/replication{path}"


def audit_pairs(c):
    return [(a["action"], a["status"]) for a in c.get("/api/audit").json()]


# ---------------------------------------------------------------- création
def test_next_job_id_picks_the_first_free_index():
    assert next_job_id(100, []) == "100-0"
    assert next_job_id(100, [{"id": "100-0"}, {"id": "100-1"}]) == "100-2"
    assert next_job_id(100, [{"id": "100-1"}, {"id": "101-0"}]) == "100-0"
    assert next_job_id(100, [{"id": f"100-{n}"} for n in range(16)]) is None


def test_create_exact_params_and_readback(api):
    c, cid = api
    r = c.post(url(cid), json={"guest": 100, "target": "enzo2", "schedule": "mon..fri 02:00", "rate": 10, "comment": "nuit", "disable": False, "confirm": True})
    assert r.status_code == 200 and r.json()["created"] == "100-0" and r.json()["locks"]["inert"] is True
    assert CALLS == [("POST", "/cluster/replication", {"id": "100-0", "type": "local", "target": "enzo2", "schedule": "mon..fri 02:00", "rate": "10", "comment": "nuit", "disable": "0"})]
    assert ST["jobs"]["100-0"]["source"] == "enzo"


def test_create_with_minimal_params_sends_only_the_whitelist(api):
    c, cid = api
    assert c.post(url(cid), json={"guest": 100, "target": "enzo2", "confirm": True, "source": "enzo2", "remove_job": "full", "type": "local", "id": "999-9"}).status_code == 200
    assert CALLS[-1][2] == {"id": "100-0", "type": "local", "target": "enzo2"}


def test_no_zfs_blocks_and_dry_run_explains(api):
    c, cid = api
    fresh(zfs=False)
    r = c.post(url(cid), json={"guest": 100, "target": "enzo2", "confirm": True})
    assert r.status_code == 409 and "ZFS" in r.json()["detail"] and not CALLS
    d = c.post(url(cid), json={"guest": 100, "target": "enzo2", "dry_run": True})
    assert d.status_code == 200 and d.json()["blocked"] is True and any("aucun stockage ZFS" in b for b in d.json()["blockers"]) and not CALLS
    assert d.json()["params"] == {"id": "100-0", "type": "local", "target": "enzo2"} and d.json()["from"] == "enzo"


def test_disk_outside_zfs_blocks_but_cdrom_is_ignored(api):
    c, cid = api
    r = c.post(url(cid), json={"guest": 101, "target": "enzo", "confirm": True})
    assert r.status_code == 409 and "rootfs" in r.json()["detail"] and "lvmthin" in r.json()["detail"] and not CALLS
    assert c.post(url(cid), json={"guest": 100, "target": "enzo2", "confirm": True}).status_code == 200            # ide2 est un CD sur « local » : ignoré


def test_disk_on_an_unknown_storage_blocks(api):
    c, cid = api
    ST["configs"][100]["scsi0"] = "ghost:vm-100-disk-0,size=8G"
    r = c.post(url(cid), json={"guest": 100, "target": "enzo2", "confirm": True})
    assert r.status_code == 409 and "inconnu" in r.json()["detail"] and "scsi0" in r.json()["detail"] and not CALLS


def test_offline_target_node_is_refused(api):
    c, cid = api
    ST["offline"] = True
    r = c.post(url(cid), json={"guest": 100, "target": "enzo2", "confirm": True})
    assert r.status_code == 422 and "hors ligne" in r.json()["detail"] and not CALLS


def test_dry_run_without_confirm_writes_nothing(api):
    c, cid = api
    d = c.post(url(cid), json={"guest": 100, "target": "enzo2", "dry_run": True})
    assert d.status_code == 200 and d.json()["blocked"] is False and d.json()["blockers"] == [] and not CALLS and not ST["jobs"]


def test_confirm_is_required_and_strict(api):
    c, cid = api
    assert c.post(url(cid), json={"guest": 100, "target": "enzo2"}).status_code == 400
    assert c.post(url(cid), json={"guest": 100, "target": "enzo2", "confirm": "true"}).status_code == 422
    assert not CALLS


@pytest.mark.parametrize("b", [
    {"schedule": "a;b"}, {"schedule": ""}, {"schedule": "   "}, {"schedule": "x" * 129}, {"schedule": "*/15\n*"}, {"schedule": 15}, {"rate": 0}, {"rate": 0.5}, {"rate": True}, {"rate": "5"},
    {"rate": 2_000_000}, {"comment": "a\nb"}, {"comment": "x" * 501}, {"disable": "1"}, {"disable": 1}, {"guest": 99}, {"guest": "100"}, {"guest": 100.5}, {"target": "a b"}, {"target": ""},
    {"target": "enzo2; rm"},
])
def test_invalid_create_is_refused_without_any_call(api, b):
    c, cid = api
    assert c.post(url(cid), json={"guest": 100, "target": "enzo2", "confirm": True, **b}).status_code == 422 and not CALLS


def test_create_refusals(api):
    c, cid = api
    ok = {"confirm": True}
    assert c.post(url(cid), json={"guest": 999, "target": "enzo2", **ok}).status_code == 404
    assert c.post(url(cid), json={"guest": 102, "target": "enzo2", **ok}).status_code == 422                       # modèle
    assert c.post(url(cid), json={"guest": 100, "target": "enzo", **ok}).status_code == 422                        # cible = nœud de la machine
    assert c.post(url(cid), json={"guest": 100, "target": "ghost", **ok}).status_code == 422
    add_job("100-0")
    assert c.post(url(cid), json={"guest": 100, "target": "enzo2", **ok}).status_code == 409                       # déjà répliquée vers cette cible
    assert not CALLS


def test_protected_machine_cannot_get_a_new_job_even_in_dry_run(api):
    c, cid = api
    r = c.post(url(cid), json={"guest": 116, "target": "enzo2", "confirm": True})
    assert r.status_code == 403 and "protégée" in r.json()["detail"]
    assert c.post(url(cid), json={"guest": 116, "target": "enzo2", "dry_run": True}).status_code == 403
    assert not CALLS


# ---------------------------------------------------------------- modification
def test_update_sends_digest_clear_and_verifies(api):
    c, cid = api
    add_job("100-0", comment="old", rate=5.0)
    r = c.put(url(cid, "/100-0"), json={"schedule": "daily", "disable": True, "clear": ["comment", "rate"], "confirm": True, "acknowledge_live": True})
    assert r.status_code == 200 and r.json()["removed"] == ["comment", "rate"] and sorted(r.json()["changed"]) == ["disable", "schedule"]
    assert CALLS[-1] == ("PUT", "/cluster/replication/100-0", {"schedule": "daily", "disable": "1", "delete": "comment,rate", "digest": "d" * 40})
    assert ST["jobs"]["100-0"]["schedule"] == "daily" and "comment" not in ST["jobs"]["100-0"]


def test_update_locks_and_refusals(api):
    c, cid = api
    add_job("100-0")
    assert c.put(url(cid, "/999-0"), json={"comment": "x", "confirm": True, "acknowledge_live": True}).status_code == 404
    assert c.put(url(cid, "/100-0"), json={"comment": "x", "confirm": True}).status_code == 409                    # effet sur l'existant : acknowledge_live
    for b in ({}, {"clear": []}, {"comment": "x", "clear": ["comment"]}, {"clear": ["target"]}, {"clear": ["id"]}):
        assert c.put(url(cid, "/100-0"), json={"confirm": True, "acknowledge_live": True, **b}).status_code == 422
    assert c.put(url(cid, "/100-0"), json={"comment": "x", "acknowledge_live": True}).status_code == 400
    assert c.put(url(cid, "/100-0"), json={"comment": "x", "dry_run": True}).json()["dry_run"] is True
    assert not CALLS
    c.put(url(cid, "/100-0"), json={"target": "enzo", "source": "enzo", "comment": "x", "confirm": True, "acknowledge_live": True})
    assert set(CALLS[-1][2]) == {"comment", "digest"}                                                                # champs inconnus jamais transmis


def test_job_marked_for_removal_cannot_be_modified_or_run(api):
    c, cid = api
    add_job("100-0", remove_job="full")
    assert c.put(url(cid, "/100-0"), json={"comment": "x", "confirm": True, "acknowledge_live": True}).status_code == 409
    assert c.post(url(cid, "/100-0/now"), json={"confirm": True, "acknowledge_live": True}).status_code == 409
    assert c.delete(url(cid, "/100-0"), params={"confirm": True, "acknowledge_live": True, "type_name": "100-0"}).status_code == 409
    assert not CALLS


# ---------------------------------------------------------------- suppression
def test_delete_requires_the_job_name_unless_keep(api):
    c, cid = api
    add_job("100-0")
    assert c.delete(url(cid, "/100-0"), params={"confirm": True}).status_code == 409                                   # acknowledge_live
    r = c.delete(url(cid, "/100-0"), params={"confirm": True, "acknowledge_live": True})
    assert r.status_code == 400 and "100-0" in r.json()["detail"] and not CALLS
    assert c.delete(url(cid, "/100-0"), params={"confirm": True, "acknowledge_live": True, "type_name": "100-1"}).status_code == 400
    assert c.delete(url(cid, "/100-0"), params={"acknowledge_live": True, "type_name": "100-0"}).status_code == 400    # confirm obligatoire
    r = c.delete(url(cid, "/100-0"), params={"confirm": True, "acknowledge_live": True, "type_name": "100-0"})
    assert r.status_code == 200 and r.json()["pending_removal"] is True and r.json()["keep"] is False
    assert CALLS == [("DELETE", "/cluster/replication/100-0", {"__query": {"keep": "0"}})] and ST["jobs"]["100-0"]["remove_job"] == "full"
    assert c.delete(url(cid, "/100-0"), params={"confirm": True, "acknowledge_live": True, "type_name": "100-0"}).status_code == 409


def test_delete_with_keep_needs_no_retype_and_sends_keep_one(api):
    c, cid = api
    add_job("100-0")
    r = c.delete(url(cid, "/100-0"), params={"confirm": True, "acknowledge_live": True, "keep": True})
    assert r.status_code == 200 and r.json()["keep"] is True
    assert CALLS == [("DELETE", "/cluster/replication/100-0", {"__query": {"keep": "1"}})] and ST["jobs"]["100-0"]["remove_job"] == "local"


def test_delete_dry_run_and_unknown(api):
    c, cid = api
    add_job("100-0")
    d = c.delete(url(cid, "/100-0"), params={"dry_run": True})
    assert d.status_code == 200 and d.json()["dry_run"] is True and d.json()["retype"] == "100-0" and "DÉTRUITES" in " ".join(d.json()["locks"]["live"]) and not CALLS
    assert c.delete(url(cid, "/100-0"), params={"dry_run": True, "keep": True}).json()["retype"] is None
    assert c.delete(url(cid, "/999-0"), params={"confirm": True, "acknowledge_live": True, "keep": True}).status_code == 404


# ---------------------------------------------------------------- lancer maintenant
def test_run_now_uses_the_source_node(api):
    c, cid = api
    add_job("100-0"); add_job("101-0")
    assert c.post(url(cid, "/100-0/now"), json={"confirm": True}).status_code == 409
    assert c.post(url(cid, "/100-0/now"), json={"confirm": True, "acknowledge_live": True}).status_code == 200
    assert CALLS[-1] == ("POST", "/nodes/enzo/replication/100-0/schedule_now", {})
    assert c.post(url(cid, "/101-0/now"), json={"confirm": True, "acknowledge_live": True}).status_code == 200
    assert CALLS[-1][1] == "/nodes/enzo2/replication/101-0/schedule_now"
    assert c.post(url(cid, "/100-0/now"), json={"dry_run": True}).json()["node"] == "enzo"
    assert c.post(url(cid, "/999-0/now"), json={"confirm": True, "acknowledge_live": True}).status_code == 404


def test_run_now_refused_for_disabled_job_and_protected_machine(api):
    c, cid = api
    add_job("100-0", disable=1); add_job("116-0")
    assert c.post(url(cid, "/100-0/now"), json={"confirm": True, "acknowledge_live": True}).status_code == 409
    r = c.post(url(cid, "/116-0/now"), json={"confirm": True, "acknowledge_live": True})
    assert r.status_code == 403 and "protégée" in r.json()["detail"] and not CALLS


def test_modifying_or_deleting_a_protected_machines_job_stays_possible(api):
    c, cid = api
    add_job("116-0")
    assert c.put(url(cid, "/116-0"), json={"disable": True, "confirm": True, "acknowledge_live": True}).status_code == 200
    assert c.delete(url(cid, "/116-0"), params={"confirm": True, "acknowledge_live": True, "keep": True}).status_code == 200


# ---------------------------------------------------------------- relecture, audit, secrets
@pytest.mark.parametrize("call", [
    lambda c, cid: c.post(url(cid), json={"guest": 100, "target": "enzo2", "confirm": True}),
    lambda c, cid: c.put(url(cid, "/101-0"), json={"comment": "x", "confirm": True, "acknowledge_live": True}),
    lambda c, cid: c.delete(url(cid, "/101-0"), params={"confirm": True, "acknowledge_live": True, "keep": True}),
], ids=["create", "update", "delete"])
def test_unapplied_change_is_a_502_not_a_success(api, call):
    c, cid = api
    add_job("101-0")
    ST["noapply"] = True
    r = call(c, cid)
    assert r.status_code == 502 and "n'a pas" in r.json()["detail"] and audit_pairs(c)[-1][1] == "error"


def test_every_write_and_refusal_is_audited_without_secret(api):
    c, cid = api
    c.post(url(cid), json={"guest": 116, "target": "enzo2", "confirm": True})                                         # refus (protégée)
    c.post(url(cid), json={"guest": 100, "target": "enzo2", "comment": "visible-no", "confirm": True})                # succès
    add_job("101-0")
    c.delete(url(cid, "/101-0"), params={"confirm": True, "acknowledge_live": True})                                  # refus (nom à retaper)
    pairs = audit_pairs(c)
    assert pairs.count(("repl-create", "error")) == 1 and pairs.count(("repl-create", "started")) == 1 and ("repl-delete", "error") in pairs
    text = c.get("/api/audit").text
    assert SECRET not in text and "visible-no" not in " ".join(a.get("detail") or "" for a in c.get("/api/audit").json())


def test_proxmox_error_never_leaks_its_message(api):
    c, cid = api
    add_job("101-0")
    ST["fail"] = True
    r = c.put(url(cid, "/101-0"), json={"comment": "x", "confirm": True, "acknowledge_live": True})
    assert r.status_code == 502 and SECRET not in r.text and SECRET not in c.get("/api/audit").text


def test_routes_require_authentication(client):
    for m, p in (("post", ""), ("put", "/100-0"), ("delete", "/100-0"), ("post", "/100-0/now")):
        assert getattr(client, m)(url(1, p)).status_code == 401
