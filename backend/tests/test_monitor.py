"""Moniteur QEMU en lecture seule (lot #273) : faux Proxmox STRICT. Ce fichier ne prouve rien sur un vrai cluster.

Le faux n'accepte, sur `POST …/qemu/{vmid}/monitor`, que le paramètre `command` : tout autre paramètre répond 400.
"""
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.deps import get_client_factory
from app.main import app
from app.monitorspec import COMMANDS, MAX_OUTPUT, check_command, clean_output
from app.proxmox import ProxmoxClient

PWD = "un-mot-de-passe-solide"
SECRET = "s3cr3t-value-xyz"
BODY = {"name": "lab", "host": "10.0.0.5", "user": "kaji@pve", "token_id": "kaji", "token_secret": SECRET}
CALLS: list[dict] = []
STATE: dict = {}


def _json(code, body):
    return httpx.Response(code, json=body)


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path.removeprefix("/api2/json")
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.content else {}
    CALLS.append({"method": request.method, "path": p, "form": form, "query": dict(request.url.params)})
    if request.method == "GET" and p == "/nodes/enzo/qemu/115/status/current":
        return _json(200, {"data": STATE.get("current", {"status": "running", "qmpstatus": "running"})})
    if request.method == "POST" and p == "/nodes/enzo/qemu/115/monitor":
        if STATE.get("fail"):
            return _json(STATE["fail"], {"data": None})
        if set(form) != {"command"} or request.url.params or form["command"] not in COMMANDS:
            return _json(400, {"data": None})
        return _json(200, {"data": STATE.get("output", "VM status: running\r\n")})
    return _json(404, {"data": None})


@pytest.fixture
def api(client):
    CALLS.clear()
    STATE.clear()
    app.dependency_overrides[get_client_factory] = lambda: (
        lambda **kw: ProxmoxClient(**kw, transport=httpx.MockTransport(_handler)))
    client.post("/api/auth/setup", json={"username": "admin", "password": PWD})
    cid = client.post("/api/connections", json=BODY).json()["id"]
    yield client, cid
    app.dependency_overrides.clear()


def u(cid, vmid=115, node="enzo"):
    return f"/api/connections/{cid}/guests/{node}/qemu/{vmid}/monitor"


def run(c, cid, command, **extra):
    return c.post(u(cid), json={"command": command, **extra})


def writes():
    return [x for x in CALLS if x["method"] != "GET"]


def audit(c):
    return c.get("/api/audit").json()


# ------------------------------------------------------------------ liste blanche (pur)

def test_every_listed_command_is_a_plain_info_command():
    """Chaque entrée est `info <mot>` sans argument ; aucune ne contient un mot d'action ni un caractère de chaînage."""
    assert COMMANDS and all(re.fullmatch(r"info [a-z][a-z-]{0,30}", c) for c in COMMANDS)
    actions = {"quit", "stop", "cont", "reset", "powerdown", "migrate_cancel", "savevm", "loadvm", "delvm", "eject", "change", "screendump", "memsave",
               "pmemsave", "gdbserver", "registers", "tlb", "mem", "mtree", "qtree", "history", "profile", "jit", "trace-events", "qom-tree"}
    assert not [c for c in COMMANDS if c.split(" ", 1)[1] in actions]


@pytest.mark.parametrize("cmd", list(COMMANDS))
def test_check_command_accepts_each_listed_command(cmd):
    assert check_command(cmd) == cmd


@pytest.mark.parametrize("cmd", [
    "", " ", "quit", "stop", "cont", "system_powerdown", "system_reset", "system_wakeup", "drive_del scsi0", "device_del x", "migrate -d tcp:1.2.3.4:1", "savevm x", "loadvm x",
    "human-monitor-command", "object_add x", "info", "info ", "info block x", "info block;quit", "info block\nquit", "info block && quit", "info  block;", "info registers",
    "info mtree", "info qtree", "info mem", "info tlb", "INFO status", "Info status", "info Status", "info/status", "info_status", "info\tstatus;quit", "info status\x00",
    "info " + "a" * 40, "info status " * 3, "help", "info history", "info trace-events", "info qom-tree", "info profile", "info jit",
])
def test_check_command_refuses_everything_else(cmd):
    assert check_command(cmd) is None


def test_check_command_normalizes_spaces_only():
    assert check_command("  info   status ") == "info status"
    assert check_command(None) is None and check_command(5) is None


def test_clean_output_strips_control_characters_and_normalizes_newlines():
    text, truncated = clean_output("a\r\nb\rc\x00\x1b[31m\x7fd\te")
    assert text == "a\nb\nc[31md\te" and truncated is False
    assert clean_output(None) == ("", False) and clean_output(["x"]) == ("", False)


def test_clean_output_is_bounded():
    text, truncated = clean_output("x" * (MAX_OUTPUT + 10))
    assert len(text) == MAX_OUTPUT and truncated is True
    assert clean_output("x" * MAX_OUTPUT) == ("x" * MAX_OUTPUT, False)


# ------------------------------------------------------------------ API

def test_requires_auth(client):
    assert client.get("/api/connections/1/guests/enzo/qemu/115/monitor").status_code == 401
    assert client.post("/api/connections/1/guests/enzo/qemu/115/monitor", json={"command": "info status"}).status_code == 401


def test_list_commands_matches_whitelist_and_calls_nothing(api):
    c, cid = api
    r = c.get(u(cid))
    assert r.status_code == 200
    assert {x["command"] for x in r.json()["commands"]} == set(COMMANDS) and all(x["label"] for x in r.json()["commands"])
    assert CALLS == []


def test_runs_listed_command_with_exact_call_audit_and_clean_output(api):
    c, cid = api
    r = run(c, cid, "info status", inconnu=1, confirm=True)
    assert r.status_code == 200 and r.json() == {"command": "info status", "output": "VM status: running\n", "truncated": False}
    assert [(w["path"], w["form"]) for w in writes()] == [("/nodes/enzo/qemu/115/monitor", {"command": "info status"})]    # rien d'autre transmis
    last = audit(c)[0]
    assert (last["action"], last["status"], last["target"], last["detail"]) == ("qemu-monitor", "started", "qemu/115@enzo", "info status")


def test_output_is_never_in_the_audit(api):
    c, cid = api
    STATE["output"] = f"secret {SECRET}"
    assert run(c, cid, "info block").status_code == 200
    assert SECRET not in c.get("/api/audit").text


def test_command_is_normalized_before_sending(api):
    c, cid = api
    assert run(c, cid, "  info    version ").status_code == 200 and writes()[0]["form"] == {"command": "info version"}


def test_output_is_truncated_and_flagged(api):
    c, cid = api
    STATE["output"] = "y" * (MAX_OUTPUT + 500)
    j = run(c, cid, "info block").json()
    assert len(j["output"]) == MAX_OUTPUT and j["truncated"] is True


@pytest.mark.parametrize("cmd", ["quit", "system_powerdown", "drive_del scsi0", "info block;quit", "info registers", "", "info", "migrate -d tcp:x:1", "human-monitor-command"])
def test_command_outside_whitelist_is_422_audited_and_never_reaches_proxmox(api, cmd):
    c, cid = api
    r = run(c, cid, cmd)
    assert r.status_code == 422 and CALLS == [] and SECRET not in r.text
    last = audit(c)[0]
    assert (last["action"], last["status"], last["detail"]) == ("qemu-monitor", "error", "commande hors liste blanche")
    assert cmd == "" or cmd not in last["detail"]                                      # la valeur refusée n'est pas recopiée dans l'audit


def test_missing_or_oversized_command_is_422_without_leak(api):
    c, cid = api
    assert c.post(u(cid), json={}).status_code == 422
    assert c.post(u(cid), json={"command": "x" * 101}).status_code == 422
    assert c.post(u(cid), json={"command": 5}).status_code == 422
    assert CALLS == []


@pytest.mark.parametrize("current", [{"status": "stopped"}, {"status": "stopped", "qmpstatus": "stopped"}, {}, {"status": "paused"}])
def test_vm_must_be_running(api, current):
    c, cid = api
    STATE["current"] = current
    r = run(c, cid, "info status")
    assert r.status_code == 409 and writes() == []
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("qemu-monitor", "error")


@pytest.mark.parametrize("current", [None, ["running"], "running"])
def test_unreadable_state_is_502_and_nothing_written(api, current):
    c, cid = api
    STATE["current"] = current
    assert run(c, cid, "info status").status_code == 502 and writes() == []


def test_paused_vm_still_answers(api):
    """Une VM suspendue est `running` + `qmpstatus: paused` chez Proxmox : le moniteur répond."""
    c, cid = api
    STATE["current"] = {"status": "running", "qmpstatus": "paused"}
    assert run(c, cid, "info status").status_code == 200


@pytest.mark.parametrize("code", [403, 500])
def test_proxmox_error_is_translated_audited_without_leak(api, code):
    c, cid = api
    STATE["fail"] = code
    r = run(c, cid, "info status")
    assert r.status_code == 502 and SECRET not in r.text and "10.0.0.5" not in r.text
    assert (audit(c)[0]["action"], audit(c)[0]["status"]) == ("qemu-monitor", "error") and SECRET not in c.get("/api/audit").text


def test_invalid_path_params_are_refused_without_call(api):
    c, cid = api
    assert c.post(u(cid, vmid=99), json={"command": "info status"}).status_code == 422
    assert c.post(u(cid, node="-bad"), json={"command": "info status"}).status_code == 422
    assert CALLS == []


def test_lxc_has_no_monitor(api):
    c, cid = api
    r = c.post(f"/api/connections/{cid}/guests/enzo/lxc/115/monitor", json={"command": "info status"})
    assert r.status_code == 422 and CALLS == []          # tombe sur la route générique `{action}` : « monitor » n'est pas une action
