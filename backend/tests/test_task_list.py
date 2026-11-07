import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.proxmox import ProxmoxClient
from app.taskspec import merge_tasks, shape_task, task_state

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}


def upid(node="pve1", typ="qmstart", vmid="100", n="1", user="kaji@pve!kaji"):
    return f"UPID:{node}:0001311{n}:09C0335D:6AEE209A:{typ}:{vmid}:{user}:"


NODES = [{"node": "pve2", "status": "online"}, {"node": "pve1", "status": "online"}, {"node": "off", "status": "offline"},
         {"node": "bad name", "status": "online"}, "illisible", {"status": "online"}]
TASKS = {
    "pve1": [
        {"upid": upid("pve1", "qmstart", "100", "1"), "node": "pve1", "type": "qmstart", "id": "100", "user": "kaji@pve", "tokenid": "kaji",
         "status": "OK", "starttime": 1700000100, "endtime": 1700000110},
        {"upid": upid("pve1", "vzdump", "", "2", "root@pam"), "node": "pve1", "type": "vzdump", "id": "", "user": "root@pam",
         "status": "WARNINGS: 2", "starttime": 1700000300, "endtime": 1700000400},
        {"upid": upid("pve1", "qmstop", "101", "3", "kaji@pve!kaji"), "node": "pve1", "type": "qmstop", "id": "101", "user": "kaji@pve",
         "tokenid": "kaji", "status": "VM quit/powerdown failed - got timeout " + "x" * 400, "starttime": 1700000200, "endtime": 1700000205},
        {"upid": upid("pve1", "qmstart", "102", "4"), "node": "pve1", "type": "qmstart", "id": "102", "user": "kaji@pve", "tokenid": "autre",
         "starttime": 1700000500},                                              # en cours (ni état ni fin), jeton d'un autre nom
    ],
    "pve2": [
        {"upid": upid("pve2", "qmigrate", "103", "5", "root@pam"), "node": "pve2", "type": "qmigrate", "id": 103, "user": "root@pam",
         "status": "OK", "starttime": 1700000250, "endtime": 1700000290},
        {"upid": upid("pve2", "qmstart", "104", "6", "kaji@pve!autre"), "node": "pve2", "type": "qmstart", "id": "104", "user": "kaji@pve",
         "tokenid": "kaji", "status": "OK", "starttime": 1700000400, "endtime": 1700000402},   # jeton « kaji » mais autre utilisateur ? non : même
        {"upid": "n'importe quoi", "node": "pve2", "type": "x"}, {"type": "x"}, "illisible", None,
    ],
}
STATE: dict = {}
SEEN: list[httpx.Request] = []


def _handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    p = request.url.path.removeprefix("/api2/json")
    if p == "/nodes":
        return httpx.Response(200, json={"data": STATE.get("nodes", NODES)})
    if p.startswith("/nodes/") and p.endswith("/tasks"):
        n = p.split("/")[2]
        if n in STATE.get("down", ()):
            return httpx.Response(500, json={"data": None})
        return httpx.Response(200, json={"data": STATE.get("tasks", TASKS).get(n, [])})
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


def get(api, query=""):
    c, cid = api
    return c.get(f"/api/connections/{cid}/tasks{query}")


def task_calls():
    return [r for r in SEEN if r.url.path.endswith("/tasks")]


# ---------- accès et lecture seule ----------------------------------------------------------------------------------

def test_requires_auth(client):
    assert client.get("/api/connections/1/tasks").status_code == 401


def test_only_get_requests_reach_proxmox_and_no_secret_leaks(api):
    r = get(api)
    assert r.status_code == 200 and SECRET not in r.text
    assert SEEN and all(req.method == "GET" for req in SEEN)
    c, cid = api
    assert c.post(f"/api/connections/{cid}/tasks", json={}).status_code in (404, 405)


# ---------- liste ---------------------------------------------------------------------------------------------------

def test_tasks_of_all_online_nodes_are_merged_newest_first(api):
    t = get(api).json()["tasks"]
    assert [x["start"][:19] for x in t] == sorted([x["start"][:19] for x in t], reverse=True)
    assert [x["type"] for x in t] == ["qmstart", "qmstart", "vzdump", "qmigrate", "qmstop", "qmstart"][:len(t)] or len(t) == 6
    assert {x["node"] for x in t} == {"pve1", "pve2"}                  # « off » (hors ligne) et le nom invalide ne sont pas interrogés
    assert {r.url.path for r in task_calls()} == {"/api2/json/nodes/pve1/tasks", "/api2/json/nodes/pve2/tasks"}


def test_states_and_texts(api):
    by = {x["upid"]: x for x in get(api).json()["tasks"]}
    ok, warn, err, run = (by[upid("pve1", "qmstart", "100", "1")], by[upid("pve1", "vzdump", "", "2", "root@pam")],
                          by[upid("pve1", "qmstop", "101", "3", "kaji@pve!kaji")], by[upid("pve1", "qmstart", "102", "4")])
    assert (ok["state"], ok["status_text"], ok["duration"]) == ("ok", None, 10)
    assert (warn["state"], warn["status_text"]) == ("warning", "WARNINGS: 2")
    assert err["state"] == "error" and len(err["status_text"]) == 200   # message libre de Proxmox : borné
    assert (run["state"], run["end"], run["duration"], run["status_text"]) == ("running", None, None, None)


def test_garbage_rows_and_bad_upids_are_ignored(api):
    ids = [x["upid"] for x in get(api).json()["tasks"]]
    assert "n'importe quoi" not in ids and len(ids) == 6


def test_numeric_id_is_returned_as_text(api):
    by = {x["upid"]: x for x in get(api).json()["tasks"]}
    assert by[upid("pve2", "qmigrate", "103", "5", "root@pam")]["id"] == "103"


def test_by_kaji_needs_same_user_and_same_token(api):
    by = {x["upid"]: x for x in get(api).json()["tasks"]}
    assert by[upid("pve1", "qmstart", "100", "1")]["by_kaji"] is True
    assert by[upid("pve1", "qmstart", "102", "4")]["by_kaji"] is False   # même utilisateur, autre jeton
    assert by[upid("pve1", "vzdump", "", "2", "root@pam")]["by_kaji"] is False


def test_limit_keeps_the_newest_overall(api):
    t = get(api, "?limit=2").json()["tasks"]
    assert len(t) == 2 and [x["type"] for x in t] == ["qmstart", "qmstart"]
    assert all(dict(r.url.params)["limit"] == "2" for r in task_calls())


def test_duplicate_upids_across_nodes_are_listed_once(api):
    dup = TASKS["pve1"][0]
    STATE["tasks"] = {"pve1": [dup], "pve2": [dup]}
    assert len(get(api).json()["tasks"]) == 1


# ---------- filtres (transmis à Proxmox, jamais appliqués à la place) -----------------------------------------------

@pytest.mark.parametrize("query,expected", [("?errors=true", {"errors": "1", "source": "all"}), ("?running=true", {"source": "active"}),
                                            ("?vmid=100", {"vmid": "100"}), ("?type=qmstart", {"typefilter": "qmstart"})])
def test_filters_are_sent_to_proxmox(api, query, expected):
    get(api, query)
    for r in task_calls():
        params = dict(r.url.params)
        assert {k: params.get(k) for k in expected} == expected and params["limit"] == "100"


def test_by_default_running_tasks_are_included_with_source_all(api):
    """Sans `source=all`, Proxmox ne renvoie que les tâches archivées : les tâches en cours seraient absentes de la liste."""
    get(api)
    assert all(dict(r.url.params) == {"limit": "100", "source": "all"} for r in task_calls())


def test_single_node(api):
    get(api, "?node=pve2")
    assert {r.url.path for r in task_calls()} == {"/api2/json/nodes/pve2/tasks"}
    assert not [r for r in SEEN if r.url.path == "/api2/json/nodes"]    # pas besoin de lister les nœuds


@pytest.mark.parametrize("query", ["?limit=0", "?limit=501", "?limit=abc", "?vmid=5", "?vmid=abc", "?type=Qm;id", "?type=a b", "?type=" + "x" * 41,
                                   "?node=a b", "?node=../x", "?node=pve1;id", "?errors=peut-etre"])
def test_invalid_parameters_are_refused_and_nothing_is_sent(api, query):
    assert get(api, query).status_code == 422 and not SEEN


# ---------- pannes --------------------------------------------------------------------------------------------------

def test_one_failing_node_does_not_hide_the_others_and_is_reported(api):
    STATE["down"] = {"pve2"}
    r = get(api).json()
    assert {x["node"] for x in r["tasks"]} == {"pve1"}
    assert [f["node"] for f in r["failed"]] == ["pve2"] and r["failed"][0]["reason"]


def test_all_nodes_failing_is_an_error_not_an_empty_list(api):
    STATE["down"] = {"pve1", "pve2"}
    assert get(api).status_code in (502, 504)


def test_no_online_node_is_a_503(api):
    STATE["nodes"] = [{"node": "pve1", "status": "offline"}]
    assert get(api).status_code == 503


def test_unreadable_node_list_is_a_503(api):
    STATE["nodes"] = "illisible"
    assert get(api).status_code == 503


def test_an_answer_that_is_not_a_list_gives_no_tasks_for_that_node(api):
    STATE["tasks"] = {"pve1": "n'importe quoi", "pve2": TASKS["pve2"]}
    r = get(api).json()
    assert {x["node"] for x in r["tasks"]} == {"pve2"} and r["failed"] == []


# ---------- logique pure --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status,ended,state", [("RUNNING", False, "running"), ("running", False, "running"), ("RUNNING", True, "error"), (None, False, "running"), (None, True, "error"), ("OK", True, "ok"), ("WARNINGS: 1", True, "warning"),
                                                ("ok", True, "error"), ("", True, "error"), ("failed", False, "error"), ("WARNINGS", True, "warning")])
def test_task_state(status, ended, state):
    assert task_state(status, ended) == state


def test_a_finished_task_without_a_status_is_never_ok():
    t = shape_task({"upid": upid(), "starttime": 10, "endtime": 20}, "pve1", None, None)
    assert t["state"] == "error"


def test_node_comes_from_the_row_or_falls_back_to_the_queried_node():
    assert shape_task({"upid": upid(), "node": "pveX"}, "pve1", None, None)["node"] == "pveX"
    assert shape_task({"upid": upid()}, "pve1", None, None)["node"] == "pve1"


@pytest.mark.parametrize("bad", ["UPID:x", upid() + "\n", " " + upid(), upid().replace("UPID", "upid"), "", None, 5, upid("pve1;x")])
def test_bad_upids_are_dropped(bad):
    assert shape_task({"upid": bad}, "pve1", None, None) is None


def test_merge_is_stable_and_bounded():
    a = {"upid": "UPID:a", "_sort": 5}
    b = {"upid": "UPID:b", "_sort": 5}
    assert [t["upid"] for t in merge_tasks([[a], [b]], 10)] == ["UPID:b", "UPID:a"]
    assert merge_tasks([[a, b]], 1) == [{"upid": "UPID:b"}]


def test_by_kaji_requires_both_user_and_token_to_match_the_connection():
    mine = shape_task({"upid": upid(), "user": "kaji@pve", "tokenid": "kaji"}, "pve1", "kaji@pve", "kaji")
    other_user = shape_task({"upid": upid(), "user": "autre@pve", "tokenid": "kaji"}, "pve1", "kaji@pve", "kaji")   # même nom de jeton, autre compte
    other_token = shape_task({"upid": upid(), "user": "kaji@pve", "tokenid": "autre"}, "pve1", "kaji@pve", "kaji")
    no_token = shape_task({"upid": upid(), "user": "kaji@pve"}, "pve1", "kaji@pve", "kaji")
    unknown_conn = shape_task({"upid": upid(), "user": "kaji@pve", "tokenid": "kaji"}, "pve1", None, None)
    assert [mine["by_kaji"], other_user["by_kaji"], other_token["by_kaji"], no_token["by_kaji"], unknown_conn["by_kaji"]] == [True, False, False, False, False]


def test_a_task_reported_as_running_by_proxmox_is_running_with_no_status_text():
    t = shape_task({"upid": upid(), "status": "RUNNING", "starttime": 1700000500}, "pve1", None, None)
    assert (t["state"], t["status_text"], t["end"], t["duration"]) == ("running", None, None, None)
