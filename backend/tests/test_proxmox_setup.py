"""`tools/proxmox-setup.sh` (installation express, jalon J1, ticket #540), essayé avec un FAUX `pveum` qui garde l'état (comptes, jetons, droits) dans des fichiers.

Vérifié : ce qui est créé et avec quels droits (jamais Administrator), la séparation de privilèges, l'expiration, le refus de root@pam, l'absence d'écrasement d'un jeton existant,
le retour en arrière si une étape échoue, le secret affiché une fois et jamais passé en argument. **Pas vérifié** : le vrai `pveum` sur un nœud (essai réel : voir `docs/REPRISE.md`).
"""
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECRET = "11111111-2222-3333-4444-555555555555"

FAKE_PVEUM = r"""#!/bin/sh
echo "pveum $*" >> "$SHIM_LOG"
S="$SHIM_STATE"; touch "$S/users" "$S/tokens" "$S/acls"
case "$1 $2" in
  "user list")
    printf '['; sep=""; for u in $(cat "$S/users"); do printf '%s{"userid":"%s","enable":1}' "$sep" "$u"; sep=","; done; printf ']\n' ;;
  "user add") [ -z "${SHIM_FAIL_USER:-}" ] || exit 1; echo "$3" >> "$S/users" ;;
  "user delete") grep -vx "$3" "$S/users" > "$S/u2" || true; mv "$S/u2" "$S/users" ;;
  "user token")
    case "$3" in
      list) printf '['; sep=""; for t in $(grep "^$4!" "$S/tokens" | sed 's/^[^!]*!//'); do printf '%s{"tokenid":"%s","privsep":1}' "$sep" "$t"; sep=","; done; printf ']\n' ;;
      add) [ -z "${SHIM_FAIL_TOKEN:-}" ] || exit 1; echo "$4!$5" >> "$S/tokens"
           printf '{"full-tokenid":"%s!%s","info":{"expire":"1","privsep":"1"},"value":"%s"}\n' "$4" "$5" "11111111-2222-3333-4444-555555555555" ;;
      remove) grep -vx "$4!$5" "$S/tokens" > "$S/t2" || true; mv "$S/t2" "$S/tokens" ;;
    esac ;;
  "acl modify") [ -z "${SHIM_FAIL_ACL:-}" ] || exit 1; echo "$*" >> "$S/acls" ;;
esac
exit 0
"""
FAKE_ID = "#!/bin/sh\n[ \"$1\" = -u ] && echo ${SHIM_UID:-0} || /usr/bin/id \"$@\"\n"


@pytest.fixture
def px(tmp_path):
    b = tmp_path / "bin"; b.mkdir()
    state = tmp_path / "state"; state.mkdir()
    for n, body in (("pveum", FAKE_PVEUM), ("id", FAKE_ID)):
        (b / n).write_text(body); (b / n).chmod(0o755)
    log = tmp_path / "log"
    env = {**os.environ, "PATH": f"{b}:{os.environ['PATH']}", "SHIM_LOG": str(log), "SHIM_STATE": str(state)}

    def run(*args, stdin="", **extra):
        return subprocess.run(["sh", str(ROOT / "tools" / "proxmox-setup.sh"), *args], input=stdin, capture_output=True, text=True, env={**env, **extra}, timeout=30)

    def lines(name):
        p = state / name
        return p.read_text().split() if p.exists() and name != "acls" else (p.read_text().splitlines() if p.exists() else [])

    return type("PX", (), {"run": staticmethod(run), "lines": staticmethod(lines), "log": log})


def calls(px):
    return px.log.read_text().splitlines() if px.log.exists() else []


def test_default_run_creates_user_token_and_read_only_acl_for_both(px):
    r = px.run("--yes")
    assert r.returncode == 0, r.stderr
    assert px.lines("users") == ["kaji@pve"] and px.lines("tokens") == ["kaji@pve!kaji"]
    acls = px.lines("acls")
    assert acls == ["acl modify / --roles PVEAuditor --users kaji@pve --tokens kaji@pve!kaji"]     # le rôle va à l'utilisateur ET au jeton
    add = [c for c in calls(px) if "token add" in c][0]
    assert "--privsep 1" in add
    exp = int(re.search(r"--expire (\d+)", add).group(1))
    assert abs(exp - (time.time() + 365 * 86400)) < 120                                            # expiration obligatoire, ~365 jours


def test_never_administrator_never_root_pam_in_any_command(px):
    px.run("--yes")
    joined = "\n".join(calls(px))
    assert "Administrator" not in joined and "root@pam" not in joined and "Permissions.Modify" not in joined


def test_secret_is_shown_once_with_the_form_values_and_never_passed_as_argument(px):
    r = px.run("--yes")
    assert r.stdout.count(SECRET) == 1
    assert "Utilisateur        : kaji@pve" in r.stdout and "ID du token        : kaji" in r.stdout and "Port               : 8006" in r.stdout
    assert SECRET not in "\n".join(calls(px)) and SECRET not in r.stderr


def test_root_pam_is_refused_before_any_command(px):
    r = px.run("--user", "root@pam", "--yes")
    assert r.returncode != 0 and "jamais root@pam" in r.stderr and calls(px) == []


@pytest.mark.parametrize("args", [("--user", "kaji"), ("--user", "a b@pve"), ("--user", "x;id@pve"), ("--user", "kaji@p-ve"), ("--token", "1abc"), ("--token", "a b"),
                                  ("--token", "$(id)"), ("--days", "0"), ("--days", "99999"), ("--days", "abc"), ("--days", "-5")])
def test_invalid_values_are_refused_before_any_command(px, args):
    r = px.run(*args, "--yes")
    assert r.returncode != 0 and calls(px) == [], r.stderr


def test_an_existing_token_is_never_overwritten(px):
    px.run("--yes")
    before = (px.lines("tokens"), px.lines("acls"))
    r = px.run("--yes")
    assert r.returncode != 0 and "existe déjà" in r.stderr
    assert (px.lines("tokens"), px.lines("acls")) == before and SECRET not in r.stdout


def test_an_existing_user_is_reused_and_not_recreated(px):
    px.run("--yes", "--token", "premier")
    r = px.run("--yes", "--token", "second")
    assert r.returncode == 0, r.stderr
    assert px.lines("users") == ["kaji@pve"] and sorted(px.lines("tokens")) == ["kaji@pve!premier", "kaji@pve!second"]
    assert len([c for c in calls(px) if "user add" in c]) == 1


def test_failure_at_the_acl_step_removes_what_was_just_created(px):
    r = px.run("--yes", SHIM_FAIL_ACL="1")
    assert r.returncode != 0 and "retiré" in r.stderr
    assert px.lines("users") == [] and px.lines("tokens") == [] and SECRET not in r.stdout


def test_failure_at_the_acl_step_keeps_a_user_that_existed_before(px):
    px.run("--yes", "--token", "ancien")
    r = px.run("--yes", "--token", "neuf", SHIM_FAIL_ACL="1")
    assert r.returncode != 0
    assert px.lines("users") == ["kaji@pve"] and px.lines("tokens") == ["kaji@pve!ancien"]       # seul le jeton créé est retiré


def test_failure_at_token_creation_removes_the_new_user(px):
    r = px.run("--yes", SHIM_FAIL_TOKEN="1")
    assert r.returncode != 0 and px.lines("users") == []


def test_without_confirmation_nothing_is_created(px):
    r = px.run(stdin="n\n")
    assert r.returncode != 0 and "annulé" in r.stderr and px.lines("users") == [] and not any("user add" in c for c in calls(px))


def test_dry_run_prints_commands_and_runs_none(px):
    r = px.run("--dry-run")
    assert r.returncode == 0 and "pveum acl modify / --roles PVEAuditor" in r.stdout and calls(px) == []


def test_must_be_root(px):
    r = px.run("--yes", SHIM_UID="1000")
    assert r.returncode != 0 and "root" in r.stderr and calls(px) == []


def test_needs_pveum(px, tmp_path):
    env_path = f"{tmp_path / 'vide'}:/usr/bin:/bin"
    (tmp_path / "vide").mkdir()
    r = subprocess.run(["/bin/sh", str(ROOT / "tools" / "proxmox-setup.sh"), "--yes"], capture_output=True, text=True, env={"PATH": env_path}, timeout=30)
    assert r.returncode != 0 and ("pveum" in r.stderr or "root" in r.stderr)
