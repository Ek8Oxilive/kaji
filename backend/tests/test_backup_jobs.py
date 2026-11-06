import copy
import re

import httpx
import pytest

from app.deps import get_client_factory
from app.jobspec import (SCHEDULE, JobUpdate, parse_retention, retention_reduced, retention_string, Retention,
                         selection_of, shape_job, shape_jobs)
from app.main import app
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}

J1 = {"id": "backup-aaa", "type": "vzdump", "enabled": 1, "schedule": "02:00", "storage": "local", "mode": "snapshot",
      "compress": "zstd", "vmid": "101,100", "prune-backups": "keep-last=3,keep-daily=7", "node": "pve1",
      "next-run": 1700000000, "notes-template": "{{guestname}}", "repeat-missed": 1}
J2 = {"id": "backup-bbb", "enabled": 0, "schedule": "sat 21:00", "storage": "nfs", "all": 1, "mode": "stop",
      "prune-backups": "keep-all=1", "exclude": "300"}
J3 = {"id": "backup-ccc", "enabled": 1, "schedule": "mon..fri 23:30", "storage": "local", "pool": "prod",
      "mode": "snapshot", "compress": "0"}
JOBS = [J1, J2, J3, {"id": 7}, "illisible", {"schedule": "02:00"}]
CALLS: list[dict] = []
STATE: dict = {}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api2/json")
    form = dict(httpx.QueryParams(request.content.decode()))
    CALLS.append({"method": request.method, "path": path, "form": form})
    if STATE.get("fail") == request.method:
        return httpx.Response(STATE.get("code", 500), json={"data": None})
    if request.method == "GET" and path == "/cluster/backup":
        return httpx.Response(200, json={"data": STATE["jobs"]})
    if request.method in ("POST", "PUT", "DELETE") and path.startswith("/cluster/backup"):
        return httpx.Response(200, json={"data": None})
    return httpx.Response(404, json={"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    STATE.clear()
    STATE["jobs"] = copy.deepcopy(JOBS)
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def writes():
    return [c for c in CALLS if c["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()[::-1]


def base(cid, suffix=""):
    return f"/api/connections/{cid}/backup-jobs{suffix}"


NEW = {"schedule": "02:30", "storage": "local", "selection": {"type": "vmids", "vmids": [101, 100]}}


# ============================== lecture =============================================================================

def test_requires_auth(client):
    assert client.get("/api/connections/1/backup-jobs").status_code == 401
    assert client.post("/api/connections/1/backup-jobs", json=NEW).status_code == 401
    assert client.put("/api/connections/1/backup-jobs/backup-aaa", json={"enabled": False}).status_code == 401
    assert client.delete("/api/connections/1/backup-jobs/backup-aaa?confirm=true").status_code == 401


def test_unknown_connection(api):
    assert api[0].get(base(999)).status_code == 404


def test_list_is_sorted_and_ignores_unreadable_entries(api):
    r = api[0].get(base(api[1])).json()
    assert [j["id"] for j in r] == ["backup-aaa", "backup-bbb", "backup-ccc"]


def test_list_shapes_each_job(api):
    j1, j2, j3 = api[0].get(base(api[1])).json()
    assert j1 == {"id": "backup-aaa", "enabled": True, "schedule": "02:00", "storage": "local", "mode": "snapshot",
                  "compress": "zstd", "node": "pve1", "selection": {"type": "vmids", "vmids": [100, 101]},
                  "retention": {"keep_last": 3, "keep_daily": 7}, "notes": "{{guestname}}",
                  "next_run": "2023-11-14T22:13:20+00:00", "repeat_missed": True}
    assert j2["enabled"] is False and j2["selection"] == {"type": "all"} and j2["retention"] == {"keep_all": True}
    assert j2["mode"] == "stop" and j2["node"] is None and j2["next_run"] is None
    assert j3["selection"] == {"type": "pool", "pool": "prod"} and j3["retention"] is None and j3["compress"] == "none"


def test_list_only_reads(api):
    api[0].get(base(api[1]))
    assert writes() == []


def test_get_one_job_and_unknown_job(api):
    c, cid = api
    assert c.get(base(cid, "/backup-ccc")).json()["selection"] == {"type": "pool", "pool": "prod"}
    assert c.get(base(cid, "/backup-zzz")).status_code == 404


@pytest.mark.parametrize("bad", ["-x", "1abc", "a", "a b", "a;b", "x" * 65, "a.b"])
def test_invalid_job_id_refused_without_call(api, bad):
    c, cid = api
    assert c.get(base(cid, f"/{bad}")).status_code in (404, 405, 422)
    assert c.put(base(cid, f"/{bad}"), json={"enabled": False}).status_code in (404, 405, 422)
    assert c.delete(base(cid, f"/{bad}?confirm=true")).status_code in (404, 405, 422)
    assert CALLS == []


def test_list_proxmox_error_is_502_without_secret(api):
    c, cid = api
    STATE.update(fail="GET", code=500)
    r = c.get(base(cid))
    assert r.status_code == 502 and SECRET not in r.text


# ============================== création ============================================================================

def test_create_sends_exact_whitelisted_params(api):
    c, cid = api
    r = c.post(base(cid), json={**NEW, "mode": "snapshot", "compress": "gzip", "retention": {"keep_all": True},
                                "node": "pve1", "enabled": False, "notes": "{{guestname}} · nuit"})
    assert r.status_code == 201
    jid = r.json()["id"]
    assert re.fullmatch(r"kaji-[0-9a-f]{10}", jid)
    assert len(writes()) == 1 and writes()[0]["method"] == "POST" and writes()[0]["path"] == "/cluster/backup"
    assert writes()[0]["form"] == {"id": jid, "schedule": "02:30", "storage": "local", "vmid": "100,101",
                                   "mode": "snapshot", "compress": "gzip", "enabled": "0",
                                   "prune-backups": "keep-all=1", "node": "pve1",
                                   "notes-template": "{{guestname}} · nuit"}


def test_create_defaults(api):
    c, cid = api
    c.post(base(cid), json=NEW)
    form = writes()[0]["form"]
    form.pop("id")
    assert form == {"schedule": "02:30", "storage": "local", "vmid": "100,101", "mode": "snapshot",
                    "compress": "zstd", "enabled": "1"}


def test_create_ids_are_unique(api):
    c, cid = api
    ids = {c.post(base(cid), json=NEW).json()["id"] for _ in range(5)}
    assert len(ids) == 5


@pytest.mark.parametrize("sel,expected", [
    ({"type": "all"}, {"all": "1"}),
    ({"type": "pool", "pool": "prod"}, {"pool": "prod"}),
    ({"type": "vmids", "vmids": [300, 100, 200]}, {"vmid": "100,200,300"}),
])
def test_create_selection_forms(api, sel, expected):
    c, cid = api
    assert c.post(base(cid), json={**NEW, "selection": sel}).status_code == 201
    form = writes()[0]["form"]
    assert {k: form[k] for k in ("all", "pool", "vmid") if k in form} == expected


def test_create_compression_none_is_zero(api):
    c, cid = api
    c.post(base(cid), json={**NEW, "compress": "none"})
    assert writes()[0]["form"]["compress"] == "0"


def test_create_unknown_fields_are_never_forwarded(api):
    c, cid = api
    extra = {"script": "/x.sh", "mailto": "a@b.c", "bwlimit": 1, "id": "evil", "type": "other", "exclude": "300",
             "remove": 0, "delete": "all", "prune-backups": "keep-last=1", "vmid": "999", "all": 1, "pool": "p",
             "dumpdir": "/tmp", "protected": 1, "comment": "x", "repeat-missed": 1, "notes-template": "x"}
    assert c.post(base(cid), json={**NEW, **extra}).status_code == 201
    form = writes()[0]["form"]
    assert set(form) == {"id", "schedule", "storage", "vmid", "mode", "compress", "enabled"}
    assert form["id"].startswith("kaji-") and form["vmid"] == "100,101"


BAD_SCHEDULES = ["", "*:0/5", "* * * * *", "*-*-* *:*:*", "daily", "hourly", "02:00:00", "2:00", "24:00", "02:60",
                 "mon", "mon 2:00", "funday 02:00", "mon-fri 02:00", "mon.fri 02:00", "mon..  02:00", "02:00\n",
                 "02:00 mon", "mon  02:00", " 02:00", "02:00 ", "mon,,tue 02:00", "*-*-01 02:00", "02:00,03:00", 7, None]


@pytest.mark.parametrize("sched", BAD_SCHEDULES)
def test_create_invalid_schedule_refused_and_nothing_called(api, sched):
    c, cid = api
    assert c.post(base(cid), json={**NEW, "schedule": sched}).status_code == 422 and CALLS == []


@pytest.mark.parametrize("sched", ["00:00", "02:30", "23:59", "mon 02:00", "mon,wed,fri 02:00", "mon..fri 02:00",
                                   "sat,sun 21:30", "mon,wed..fri 04:15"])
def test_create_valid_schedules_accepted(api, sched):
    assert api[0].post(base(api[1]), json={**NEW, "schedule": sched}).status_code == 201


@pytest.mark.parametrize("patch", [
    {"storage": "a b"}, {"storage": "-x"}, {"storage": "a;b"}, {"storage": "local\n"}, {"storage": "s" * 41},
    {"storage": ""}, {"storage": None}, {"storage": 7},
    {"node": "-pve"}, {"node": "pve_1"}, {"node": "pve.1"}, {"node": "p" * 64}, {"node": "pve1\n"}, {"node": ""},
    {"mode": "hot"}, {"mode": "STOP"}, {"mode": ""}, {"mode": None},
    {"compress": "xz"}, {"compress": "0"}, {"compress": ""},
    {"notes": "a\nb"}, {"notes": "a\n"}, {"notes": "a\\b"}, {"notes": "n" * 201},
    {"enabled": "maybe"}, {"enabled": None},
    {"selection": None}, {"selection": {}}, {"selection": {"type": "everything"}}, {"selection": "all"},
    {"selection": {"type": "vmids", "vmids": []}}, {"selection": {"type": "vmids"}},
    {"selection": {"type": "vmids", "vmids": [99]}}, {"selection": {"type": "vmids", "vmids": [1000000000]}},
    {"selection": {"type": "vmids", "vmids": [100, 100]}}, {"selection": {"type": "vmids", "vmids": ["a"]}},
    {"selection": {"type": "vmids", "vmids": list(range(100, 201))}},
    {"selection": {"type": "pool"}}, {"selection": {"type": "pool", "pool": "a b"}},
    {"selection": {"type": "pool", "pool": "p\n"}}, {"selection": {"type": "pool", "pool": ""}},
    {"retention": {}}, {"retention": {"keep_last": 0}}, {"retention": {"keep_last": -1}},
    {"retention": {"keep_last": 1000}}, {"retention": {"keep_last": "x"}}, {"retention": {"keep_last": 1.5}},
    {"retention": {"keep_all": False}}, {"retention": {"keep_all": True, "keep_last": 3}},
    {"retention": {"keep_last": 0, "keep_daily": 7}}, {"retention": {"keep_daily": 0}},
    {"retention": {"keep_all": False, "keep_last": None}}, {"retention": "keep-last=3"},
])
def test_create_invalid_body_refused_and_nothing_called(api, patch):
    c, cid = api
    r = c.post(base(cid), json={**NEW, **patch})
    assert r.status_code == 422 and CALLS == [] and SECRET not in r.text


@pytest.mark.parametrize("missing", ["schedule", "storage", "selection"])
def test_create_missing_required_field_refused(api, missing):
    body = {k: v for k, v in NEW.items() if k != missing}
    assert api[0].post(base(api[1]), json=body).status_code == 422 and CALLS == []


def test_create_invalid_value_is_not_echoed(api):
    assert "valeur-saisie-evil" not in api[0].post(base(api[1]), json={**NEW, "schedule": "valeur-saisie-evil"}).text


def test_create_keep_last_zero_alone_is_refused_with_a_clear_message(api):
    r = api[0].post(base(api[1]), json={**NEW, "retention": {"keep_last": 0}})
    assert r.status_code == 422 and CALLS == []


def test_create_stop_mode_needs_confirmation(api):
    c, cid = api
    r = c.post(base(cid), json={**NEW, "mode": "stop"})
    assert r.status_code == 400 and "confirm=true" in r.json()["detail"] and "ARRÊTE" in r.json()["detail"]
    assert CALLS == []
    assert c.post(base(cid), json={**NEW, "mode": "stop", "confirm": True}).status_code == 201
    assert writes()[0]["form"]["mode"] == "stop" and "confirm" not in writes()[0]["form"]


@pytest.mark.parametrize("ret", [{"keep_last": 3}, {"keep_daily": 7, "keep_weekly": 4}, {"keep_yearly": 1}])
def test_create_finite_retention_needs_confirmation(api, ret):
    c, cid = api
    r = c.post(base(cid), json={**NEW, "retention": ret})
    assert r.status_code == 400 and "rétention" in r.json()["detail"] and "première exécution" in r.json()["detail"]
    assert CALLS == []
    assert c.post(base(cid), json={**NEW, "retention": ret, "confirm": True}).status_code == 201
    assert "confirm" not in writes()[0]["form"]


@pytest.mark.parametrize("extra", [{}, {"retention": {"keep_all": True}}])
def test_create_without_finite_retention_needs_no_confirmation(api, extra):
    assert api[0].post(base(api[1]), json={**NEW, **extra}).status_code == 201


def test_create_confirm_values_that_are_not_true_do_not_confirm(api):
    c, cid = api
    for v in (False, None, 0, "false"):
        r = c.post(base(cid), json={**NEW, "mode": "stop", "confirm": v})
        assert r.status_code in (400, 422)
    assert CALLS == []


def test_create_proxmox_error_is_502_audited_without_secret(api):
    c, cid = api
    STATE.update(fail="POST", code=403)
    r = c.post(base(cid), json=NEW)
    assert r.status_code == 502 and SECRET not in r.text
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("backup-job-create", "error")]
    assert SECRET not in c.get("/api/audit").text


def test_create_audit_success_and_refusal_never_contain_notes(api):
    c, cid = api
    c.post(base(cid), json={**NEW, "mode": "stop", "notes": "texte-libre-de-notes"})          # refus
    c.post(base(cid), json={**NEW, "notes": "texte-libre-de-notes", "retention": {"keep_all": True}})
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("backup-job-create", "error"), ("backup-job-create", "started")]
    assert "notes=définies" in log[1]["detail"] and "sélection=machines 100,101" in log[1]["detail"]
    assert "texte-libre-de-notes" not in c.get("/api/audit").text


# ============================== mise à jour =========================================================================

def put(c, cid, jid="backup-aaa", **body):
    return c.put(base(cid, f"/{jid}"), json=body)


def test_update_unknown_job_is_404_and_nothing_written(api):
    c, cid = api
    assert put(c, cid, "backup-zzz", enabled=False).status_code == 404 and writes() == []
    assert [(e["action"], e["status"]) for e in audit(c)] == [("backup-job-update", "error")]


@pytest.mark.parametrize("body", [{}, {"confirm": True}, {"schedule": None}, {"storage": None}, {"selection": None},
                                  {"mode": None}, {"compress": None}, {"retention": None}, {"enabled": None}])
def test_update_empty_or_null_fields_refused(api, body):
    assert api[0].put(base(api[1], "/backup-aaa"), json=body).status_code == 422 and CALLS == []


def test_update_only_provided_fields_are_sent(api):
    c, cid = api
    r = put(c, cid, schedule="03:15")
    assert r.status_code == 200 and r.json() == {"id": "backup-aaa", "updated": ["schedule"]}
    assert writes()[0]["method"] == "PUT" and writes()[0]["path"] == "/cluster/backup/backup-aaa"
    assert writes()[0]["form"] == {"schedule": "03:15"}


def test_update_disable_and_enable(api):
    c, cid = api
    assert put(c, cid, enabled=False).status_code == 200
    assert writes()[-1]["form"] == {"enabled": "0"}
    assert put(c, cid, "backup-ccc", enabled=True).status_code == 200
    assert writes()[-1]["form"] == {"enabled": "1"}


def test_update_unknown_fields_are_never_forwarded(api):
    c, cid = api
    assert put(c, cid, schedule="03:15", id="evil", script="/x", vmid="999", all=1, remove=1, delete="vmid",
               **{"prune-backups": "keep-last=1"}).status_code == 200
    assert writes()[0]["form"] == {"schedule": "03:15"}


def test_update_invalid_values_refused_and_nothing_called(api):
    c, cid = api
    for body in ({"schedule": "*:0/5"}, {"storage": "a b"}, {"node": "-x"}, {"mode": "hot"},
                 {"retention": {"keep_last": 0}}, {"selection": {"type": "pool", "pool": "a b"}}, {"notes": "a\n"}):
        assert c.put(base(cid, "/backup-aaa"), json=body).status_code == 422
    assert CALLS == []


# ---- sélection -------------------------------------------------------------------------------------------------

def test_update_selection_replaces_and_deletes_old_keys(api):
    c, cid = api
    r = put(c, cid, "backup-ccc", selection={"type": "all"})                           # J3 : pool -> all, sans rétention
    assert r.status_code == 200
    assert writes()[0]["form"] == {"all": "1", "delete": "pool"}


def test_update_selection_from_all_deletes_all_and_exclude(api):
    c, cid = api
    assert put(c, cid, "backup-bbb", selection={"type": "pool", "pool": "prod"}).status_code == 200   # keep-all : pas de risque
    assert writes()[0]["form"] == {"pool": "prod", "delete": "all,exclude"}


def test_update_selection_only_deletes_keys_that_exist(api):
    c, cid = api
    put(c, cid, "backup-ccc", selection={"type": "vmids", "vmids": [100]})
    assert writes()[0]["form"] == {"vmid": "100", "delete": "pool"}


def test_update_node_null_removes_node_only_if_present(api):
    c, cid = api
    assert put(c, cid, node=None).status_code == 200
    assert writes()[-1]["form"] == {"delete": "node"}
    assert put(c, cid, "backup-ccc", node=None, schedule="01:00").status_code == 200
    assert writes()[-1]["form"] == {"schedule": "01:00"}


def test_update_notes_null_removes_notes_template(api):
    c, cid = api
    assert put(c, cid, notes=None).status_code == 200
    assert writes()[-1]["form"] == {"delete": "notes-template"}
    assert put(c, cid, notes="{{vmid}}").status_code == 200
    assert writes()[-1]["form"] == {"notes-template": "{{vmid}}"}


# ---- rétention -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("jid,ret", [
    ("backup-aaa", {"keep_last": 2, "keep_daily": 7}),          # valeur diminuée
    ("backup-aaa", {"keep_last": 3}),                           # règle retirée
    ("backup-aaa", {"keep_weekly": 4}),                         # règles remplacées
    ("backup-aaa", {"keep_last": 3, "keep_daily": 6}),          # une règle diminuée
    ("backup-ccc", {"keep_last": 5}),                           # ancien : aucune politique (garde tout) -> finie
    ("backup-bbb", {"keep_last": 5}),                           # ancien : keep-all -> finie
])
def test_update_reducing_retention_needs_confirmation(api, jid, ret):
    c, cid = api
    r = put(c, cid, jid, retention=ret)
    assert r.status_code == 400 and "RÉDUIT" in r.json()["detail"] and "confirm=true" in r.json()["detail"]
    assert writes() == []
    assert put(c, cid, jid, retention=ret, confirm=True).status_code == 200
    assert writes()[0]["form"]["prune-backups"] == retention_string(Retention(**ret))
    assert "confirm" not in writes()[0]["form"]


@pytest.mark.parametrize("ret", [
    {"keep_last": 3, "keep_daily": 7},                          # identique
    {"keep_last": 5, "keep_daily": 7},                          # augmenté
    {"keep_last": 3, "keep_daily": 7, "keep_weekly": 4},        # règle ajoutée
    {"keep_last": 10, "keep_daily": 30, "keep_yearly": 2},
    {"keep_all": True},                                         # garde tout
])
def test_update_not_reducing_retention_needs_no_confirmation(api, ret):
    c, cid = api
    assert put(c, cid, retention=ret).status_code == 200


def test_update_storage_change_with_finite_retention_needs_confirmation(api):
    c, cid = api
    r = put(c, cid, storage="autre")
    assert r.status_code == 400 and "autre stockage" in r.json()["detail"] and writes() == []
    assert put(c, cid, storage="autre", confirm=True).status_code == 200
    assert put(c, cid, storage="local").status_code == 200            # même stockage : rien à confirmer


def test_update_selection_change_with_finite_retention_needs_confirmation(api):
    c, cid = api
    sel = {"type": "vmids", "vmids": [100, 101, 102]}
    assert put(c, cid, selection=sel).status_code == 400 and writes() == []
    assert put(c, cid, selection=sel, confirm=True).status_code == 200
    assert put(c, cid, selection={"type": "vmids", "vmids": [100, 101]}).status_code == 200   # même sélection


def test_update_storage_or_selection_change_without_retention_needs_no_confirmation(api):
    c, cid = api
    assert put(c, cid, "backup-ccc", storage="autre").status_code == 200
    assert put(c, cid, "backup-bbb", storage="autre").status_code == 200     # keep-all : ne supprime rien


# ---- mode stop -------------------------------------------------------------------------------------------------

def test_update_setting_stop_mode_needs_confirmation(api):
    c, cid = api
    r = put(c, cid, "backup-ccc", mode="stop")
    assert r.status_code == 400 and "ARRÊTE" in r.json()["detail"] and writes() == []
    assert put(c, cid, "backup-ccc", mode="stop", confirm=True).status_code == 200


def test_update_enabling_a_stop_job_needs_confirmation(api):
    c, cid = api                                                       # J2 : désactivé, mode stop
    assert put(c, cid, "backup-bbb", enabled=True).status_code == 400 and writes() == []
    assert put(c, cid, "backup-bbb", enabled=True, confirm=True).status_code == 200


def test_update_disabling_or_editing_a_stop_job_needs_no_confirmation(api):
    c, cid = api
    assert put(c, cid, "backup-bbb", enabled=False).status_code == 200
    assert put(c, cid, "backup-bbb", schedule="04:00").status_code == 200      # reste désactivé, mode inchangé


def test_update_enabling_a_non_stop_job_needs_no_confirmation(api):
    STATE["jobs"][2]["enabled"] = 0
    assert put(api[0], api[1], "backup-ccc", enabled=True).status_code == 200


# ---- erreurs et audit ------------------------------------------------------------------------------------------

def test_update_proxmox_error_is_502_audited_without_secret(api):
    c, cid = api
    STATE.update(fail="PUT", code=500)
    r = put(c, cid, schedule="03:15")
    assert r.status_code == 502 and SECRET not in r.text
    assert [(e["action"], e["status"]) for e in audit(c)] == [("backup-job-update", "error")]


def test_update_reading_jobs_error_is_502_and_nothing_written(api):
    c, cid = api
    STATE.update(fail="GET", code=500)
    assert put(c, cid, schedule="03:15").status_code == 502 and writes() == []


def test_update_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    put(c, cid, "backup-zzz", enabled=False)                                         # introuvable
    put(c, cid, retention={"keep_last": 1})                                          # refus : réduction
    put(c, cid, "backup-bbb", enabled=True)                                          # refus : mode stop
    put(c, cid, schedule="03:15", notes="texte-libre-de-notes")                      # succès
    STATE.update(fail="PUT", code=500)
    put(c, cid, schedule="04:00")                                                    # erreur Proxmox
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("backup-job-update", "error")] * 3 + \
        [("backup-job-update", "started"), ("backup-job-update", "error")]
    assert [e["target"] for e in log] == ["backup-zzz", "backup-aaa", "backup-bbb", "backup-aaa", "backup-aaa"]
    assert "RÉDUIT" in log[1]["detail"] and "ARRÊTE" in log[2]["detail"] and "notes=définies" in log[3]["detail"]
    assert "texte-libre-de-notes" not in c.get("/api/audit").text and SECRET not in c.get("/api/audit").text


# ============================== suppression =========================================================================

def delete(c, cid, jid="backup-aaa", query="?confirm=true"):
    return c.delete(base(cid, f"/{jid}{query}"))


def test_delete_without_confirm_refused_and_proxmox_never_called(api):
    c, cid = api
    for q in ("", "?confirm=false", "?confirm=0", "?confirm=non", "?confirm="):
        assert delete(c, cid, query=q).status_code in (400, 422)
    assert CALLS == []


def test_delete_unknown_job_is_404_and_nothing_deleted(api):
    c, cid = api
    assert delete(c, cid, "backup-zzz").status_code == 404 and writes() == []


def test_delete_happy_path_one_exact_call_and_says_backups_are_kept(api):
    c, cid = api
    r = delete(c, cid)
    assert r.status_code == 200 and r.json()["deleted"] == "backup-aaa"
    assert "n'ont pas été supprimées" in r.json()["note"]
    assert len(writes()) == 1 and writes()[0]["method"] == "DELETE" and writes()[0]["path"] == "/cluster/backup/backup-aaa"


def test_delete_proxmox_error_is_502_without_secret(api):
    c, cid = api
    STATE.update(fail="DELETE", code=403)
    r = delete(c, cid)
    assert r.status_code == 502 and SECRET not in r.text


def test_no_mass_deletion_route_exists(api):
    c, cid = api
    assert c.delete(base(cid) + "?confirm=true").status_code in (404, 405) and writes() == []


def test_delete_audit_records_success_every_refusal_and_error(api):
    c, cid = api
    delete(c, cid, query="")                                                         # sans confirm
    delete(c, cid, "backup-zzz")                                                     # introuvable
    delete(c, cid)                                                                   # succès
    STATE.update(fail="DELETE", code=500)
    delete(c, cid, "backup-ccc")                                                     # erreur Proxmox
    log = audit(c)
    assert [(e["action"], e["status"]) for e in log] == [("backup-job-delete", "error")] * 2 + \
        [("backup-job-delete", "started"), ("backup-job-delete", "error")]
    assert "conservées" in log[2]["detail"] and SECRET not in c.get("/api/audit").text


# ============================== unitaire ============================================================================

@pytest.mark.parametrize("raw,expected", [
    ("keep-last=3,keep-daily=7", {"keep-last": 3, "keep-daily": 7}),
    ("keep-all=1", {"keep-all": 1}), ("keep-all=0", None), ("keep-all=0,keep-last=2", {"keep-last": 2}),
    ({"keep-last": 3}, {"keep-last": 3}), ("keep-last=0", None), ("keep-last=abc", None), ("autre=3", None),
    ("", None), (None, None), (7, None), ("keep-last", None), ("keep-last=-2", None),
])
def test_parse_retention(raw, expected):
    assert parse_retention(raw) == expected


@pytest.mark.parametrize("old,new,reduced", [
    (None, {"keep-last": 3}, True), ({"keep-all": 1}, {"keep-last": 3}, True), ({"keep-last": 3}, {"keep-last": 2}, True),
    ({"keep-last": 3, "keep-daily": 7}, {"keep-last": 3}, True), ({"keep-last": 3}, {"keep-daily": 7}, True),
    ({"keep-last": 3}, {"keep-last": 3}, False), ({"keep-last": 3}, {"keep-last": 4}, False),
    ({"keep-last": 3}, {"keep-last": 3, "keep-daily": 1}, False), ({"keep-last": 3}, {"keep-all": 1}, False),
    (None, {"keep-all": 1}, False), ({"keep-all": 1}, {"keep-all": 1}, False),
])
def test_retention_reduced(old, new, reduced):
    assert retention_reduced(old, new) is reduced


def test_schedule_grammar_rejects_newline_at_the_end():
    assert SCHEDULE.fullmatch("02:00") and not SCHEDULE.fullmatch("02:00\n")


def test_selection_of_and_shape_tolerate_unexpected_values():
    assert selection_of({}) == {"type": None}
    assert selection_of({"all": "1"}) == {"type": "all"} and selection_of({"all": "0", "vmid": "100,abc, 7"}) == {"type": "vmids", "vmids": [7, 100]}
    assert shape_job({"id": "x", "enabled": "oui", "schedule": 7, "next-run": 10 ** 15, "prune-backups": 3})["enabled"] is True
    assert shape_job({"id": "x", "next-run": 10 ** 15})["next_run"] is None
    assert shape_job({"id": ""}) is None and shape_job(None) is None and shape_jobs("x") == []


def test_update_model_requires_at_least_one_field():
    with pytest.raises(ValueError):
        JobUpdate()
