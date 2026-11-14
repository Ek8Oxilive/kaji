"""`tools/backup.sh` et `tools/restore.sh` (jalon J1, ticket #429), essayés avec un FAUX `docker`.

Il n'y a pas de Docker sur le poste de rédaction : le faux `docker` (script `sh` ci-dessous) transforme `docker compose exec|run … python -m app.admin_cli …` en l'exécution
des VRAIES commandes Python sur une vraie base SQLite, et note chaque appel dans un journal. Ce qui est vérifié : l'enchaînement des scripts, leurs refus, leurs codes de
sortie, les droits des fichiers, la confirmation « RESTAURER », le choix des fichiers Compose. **Ce qui ne l'est PAS** : le vrai Docker (volume, utilisateur du conteneur,
`compose run` / `--wait`) : seul un essai sur une machine avec Docker le prouve (ticket #429, jalon J1).
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.backup import key_fingerprint, verify
from tests.test_backup_restore import HOOK, KEY, OTHER_KEY, TOKEN, make_db, read_back

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

FAKE_DOCKER = r"""#!/bin/sh
echo "docker $* [COMPOSE_FILE=${COMPOSE_FILE:-}]" >> "$SHIM_LOG"
[ "$1" = compose ] || exit 99
shift
while [ "${1:-}" = -f ]; do shift 2; done
cmd=$1; shift
case "$cmd" in
  ps) [ -n "${SHIM_TLS:-}" ] && echo tls; exit 0 ;;
  stop|up) exit 0 ;;
  exec|run)
    while [ "${1#-}" != "$1" ]; do shift; done      # options (-T, --rm, --no-deps)
    shift                                            # nom du service
    [ "$1" = python ] && shift
    if [ -n "${SHIM_BREAK_BACKUP:-}" ] && [ "$3" = backup ]; then echo "pas une base"; exit 0; fi
    cd "$SHIM_BACKEND" && exec "$SHIM_PYTHON" "$@" ;;
esac
exit 98
"""


@pytest.fixture
def lab(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    (tmp_path / "live").mkdir()
    live = make_db(tmp_path / "live" / "kaji.db")
    log = tmp_path / "docker.log"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "SHIM_LOG": str(log), "SHIM_BACKEND": str(BACKEND), "SHIM_PYTHON": sys.executable,
           "DATABASE_URL": f"sqlite:///{live}", "KAJI_SECRET_KEY": KEY, "KAJI_SCHEDULER": "false", "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("COMPOSE_FILE", None)

    def run(script: str, *args: str, stdin: str = "", cwd: Path | None = None, **extra_env):
        return subprocess.run([str(ROOT / "tools" / script), *args], input=stdin, capture_output=True, text=True, env={**env, **extra_env}, timeout=120, cwd=cwd)

    def calls() -> list[str]:
        return log.read_text().splitlines() if log.exists() else []

    return type("Lab", (), {"live": live, "dest": tmp_path / "sauvegardes", "run": staticmethod(run), "calls": staticmethod(calls), "tmp": tmp_path})


# ------------------------------------------------------------------ backup.sh

def test_backup_script_writes_a_private_verified_copy_and_reminds_about_the_key(lab):
    r = lab.run("backup.sh", str(lab.dest))
    assert r.returncode == 0, r.stderr
    files = sorted(lab.dest.iterdir())
    assert len(files) == 1 and files[0].name.startswith("kaji-") and files[0].suffix == ".db"       # aucun « .partiel » ne traîne
    assert files[0].stat().st_mode & 0o777 == 0o600 and lab.dest.stat().st_mode & 0o777 == 0o700
    assert verify(files[0], KEY).ok and read_back(files[0])["token"] == TOKEN
    out = r.stdout + r.stderr
    assert "Résultat : OK" in out and "sauvegarder AUSSI le fichier .env" in out and "KAJI_SECRET_KEY" in out and f"empreinte {key_fingerprint(KEY)}".lower() in out.lower()
    for secret in (TOKEN, HOOK, KEY, "SECRET-WEBHOOK-PATH"):
        assert secret not in out, f"« {secret} » affiché par le script"


def test_backup_script_keeps_nothing_when_the_container_returns_something_else_than_a_database(lab):
    r = lab.run("backup.sh", str(lab.dest), SHIM_BREAK_BACKUP="1")
    assert r.returncode == 1 and "n'est pas une base SQLite" in r.stderr
    assert list(lab.dest.iterdir()) == []


def test_backup_script_fails_loudly_when_the_copy_cannot_be_read_with_the_current_key(lab, monkeypatch):
    c = sqlite3.connect(lab.live)
    from app.crypto import encrypt
    c.execute("UPDATE connections SET token_secret_enc=?", (encrypt(OTHER_KEY, TOKEN),)); c.commit(); c.close()
    r = lab.run("backup.sh", str(lab.dest))
    assert r.returncode == 1 and "n'est PAS exploitable" in r.stderr and "Résultat : ÉCHEC" in r.stdout


# ------------------------------------------------------------------ restore.sh

def _backup_of(lab, suffix: str, key: str = KEY) -> Path:
    other = make_db(lab.tmp / f"autre{suffix}.db", key=key, suffix=suffix)
    return other


def test_restore_script_asks_for_the_word_then_stops_restores_restarts_and_verifies(lab):
    backup = _backup_of(lab, "-sauvegarde")
    r = lab.run("restore.sh", str(backup), stdin="RESTAURER\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Base restaurée" in r.stdout and "Résultat : OK" in r.stdout
    calls = lab.calls()
    order = [next(i for i, c in enumerate(calls) if needle in c) for needle in ("compose stop backend", "admin_cli restore - --yes", "up -d --wait backend", "admin_cli verify")]
    assert order == sorted(order)                                              # arrêt, restauration, redémarrage, contrôle : dans cet ordre
    c = sqlite3.connect(lab.live); names = {x[0] for x in c.execute("SELECT username FROM admin_users")}; c.close()
    assert names == {"alice-sauvegarde", "bob-sauvegarde"}
    assert lab.live.stat().st_mode & 0o777 == 0o600
    assert list(lab.live.parent.glob("kaji.db.avant-restauration-*"))          # l'ancienne base est gardée à côté


def test_restore_script_does_nothing_without_the_confirmation_word(lab):
    before = lab.live.read_bytes()
    r = lab.run("restore.sh", str(_backup_of(lab, "-x")), stdin="oui\n")
    assert r.returncode == 1 and "Annulé" in r.stderr
    assert lab.live.read_bytes() == before and not any("compose stop" in c for c in lab.calls())      # Kaji n'a même pas été arrêté


def test_restore_script_with_yes_skips_the_question(lab):
    r = lab.run("restore.sh", str(_backup_of(lab, "-y")), "--yes")
    assert r.returncode == 0, r.stdout + r.stderr


def test_restore_script_accepts_a_relative_path_given_from_another_folder(lab):
    backup = _backup_of(lab, "-rel")
    r = lab.run("restore.sh", backup.name, "--yes", cwd=backup.parent)           # le script change de dossier : le chemin relatif doit avoir été résolu avant
    assert r.returncode == 0, r.stdout + r.stderr


def test_restore_script_refuses_a_backup_the_current_key_cannot_read_and_restarts_kaji(lab):
    before = lab.live.read_bytes()
    r = lab.run("restore.sh", str(_backup_of(lab, "-z", key=OTHER_KEY)), "--yes")
    assert r.returncode == 1 and "REFUSÉE" in r.stderr and "illisible" in r.stdout
    assert lab.live.read_bytes() == before                                     # la base en place n'a pas bougé
    calls = lab.calls()
    assert any("compose stop backend" in c for c in calls) and calls[-1].startswith("docker compose up -d backend")      # Kaji est relancé avec l'ancienne base
    assert OTHER_KEY not in r.stdout + r.stderr and KEY not in r.stdout + r.stderr


def test_restore_script_refuses_a_file_that_is_not_a_database_before_touching_anything(lab, tmp_path):
    notdb = tmp_path / "texte.db"; notdb.write_text("pas une base de données, juste du texte")
    r = lab.run("restore.sh", str(notdb), "--yes")
    assert r.returncode == 2 and "pas une base SQLite" in r.stderr
    assert lab.calls() == []                                                   # aucun appel à docker
    for args in ((), (str(tmp_path / "absent.db"),)):
        r = lab.run("restore.sh", *args)
        assert r.returncode == 2 and "usage : tools/restore.sh" in r.stderr
    assert lab.calls() == []


# ------------------------------------------------------------------ fichiers Compose

def test_scripts_use_both_compose_files_only_when_the_https_container_is_running(lab):
    lab.run("backup.sh", str(lab.dest / "a"))
    plain = [c for c in lab.calls() if "exec" in c]
    assert plain and all(c.endswith("[COMPOSE_FILE=]") for c in plain)         # pas de HTTPS : fichier de base seul
    lab.run("backup.sh", str(lab.dest / "b"), SHIM_TLS="1")
    tls = [c for c in lab.calls() if "exec" in c][len(plain):]
    assert tls and all(c.endswith("[COMPOSE_FILE=docker-compose.yml:docker-compose.tls.yml]") for c in tls)


def test_an_existing_compose_file_variable_is_left_alone(lab):
    lab.run("backup.sh", str(lab.dest), SHIM_TLS="1", COMPOSE_FILE="mon-compose.yml")
    assert all("[COMPOSE_FILE=mon-compose.yml]" in c for c in lab.calls() if "exec" in c)
