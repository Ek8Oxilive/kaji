"""`install.sh` (installation express, jalon J1, ticket #538), essayé avec un FAUX `docker`, un FAUX `curl` et un vrai `git` sur un dépôt temporaire.

Ce qui est vérifié ici : l'enchaînement, les refus, les droits du `.env`, l'absence de fuite de la clé dans la sortie, le choix des fichiers Compose, l'idempotence.
Ce que ces tests ne prouvent PAS : l'installation de Docker (Debian / Ubuntu), le vrai démarrage des conteneurs (essayé à la main, voir `docs/REPRISE.md`).
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

FAKE_DOCKER = r"""#!/bin/sh
echo "docker $*" >> "$SHIM_LOG"
case "$1" in
  info) [ -z "${SHIM_NO_DAEMON:-}" ] && exit 0 || exit 1 ;;
  compose)
    shift
    while [ "${1:-}" = -f ]; do shift 2; done
    case "$1" in
      version) [ -z "${SHIM_NO_COMPOSE:-}" ] && exit 0 || exit 1 ;;
      cp) cp /dev/null "$3"; echo CERT > "$3"; exit 0 ;;
      pull) [ -z "${SHIM_NO_IMAGES:-}" ] && exit 0 || { echo denied >&2; exit 1; } ;;
      up|ps|logs) exit 0 ;;
    esac ;;
esac
exit 0
"""
FAKE_CURL = """#!/bin/sh
echo "curl $*" >> "$SHIM_LOG"
[ -z "${SHIM_UNHEALTHY:-}" ]
"""


@pytest.fixture
def lab(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    # Faux dépôt Kaji : les vrais fichiers Compose et .env.example, dans un vrai dépôt git.
    repo = tmp_path / "depot"
    repo.mkdir()
    for f in ("docker-compose.yml", "docker-compose.tls.yml", ".env.example"):
        shutil.copy(ROOT / f, repo / f)
    git = lambda *a, cwd=repo: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    log = tmp_path / "shim.log"
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "KAJI_INSTALL_TRIES": "1", "KAJI_INSTALL_PAUSE": "0", "PATH": f"{bin_dir}:{os.environ['PATH']}", "SHIM_LOG": str(log), "HOME": str(home)}
    for k in ("SHIM_NO_DAEMON", "SHIM_NO_COMPOSE", "SHIM_UNHEALTHY"):
        env.pop(k, None)
    target = tmp_path / "kaji"

    def run(*args, stdin="", **extra):
        return subprocess.run(["sh", str(ROOT / "install.sh"), "--repo", str(repo), "--dir", str(target), *args], input=stdin, capture_output=True, text=True,
                              env={**env, **extra}, timeout=120)

    def calls():
        return log.read_text().splitlines() if log.exists() else []

    return type("Lab", (), {"run": staticmethod(run), "calls": staticmethod(calls), "target": target, "repo": repo, "git": staticmethod(git), "log": log})


def env_of(target: Path) -> dict:
    return dict(l.split("=", 1) for l in (target / ".env").read_text().splitlines() if "=" in l and not l.startswith("#"))


def test_fresh_local_install_creates_env_with_secrets_and_starts_without_tls(lab):
    r = lab.run("--local", "--yes")
    assert r.returncode == 0, r.stderr + r.stdout
    e = env_of(lab.target)
    assert len(e["KAJI_SECRET_KEY"]) >= 32 and e["KAJI_SECRET_KEY"] != "changeme"
    assert len(e["KAJI_SETUP_TOKEN"]) >= 24
    assert "KAJI_TLS_SITE" not in e
    assert stat.S_IMODE((lab.target / ".env").stat().st_mode) == 0o600
    ups = [c for c in lab.calls() if " up " in c]
    assert ups == ["docker compose -f docker-compose.yml up -d --build"]
    assert "docker-compose.tls.yml" not in " ".join(lab.calls())
    assert not (lab.target / "caddy-root.crt").exists()


def test_the_secret_key_never_appears_in_the_output_but_the_setup_token_does(lab):
    r = lab.run("--local", "--yes")
    e = env_of(lab.target)
    assert e["KAJI_SECRET_KEY"] not in r.stdout + r.stderr
    assert e["KAJI_SETUP_TOKEN"] in r.stdout                       # affiché une fois : il faut le saisir pour créer le compte


def test_address_enables_tls_with_both_compose_files_and_fetches_the_certificate(lab):
    r = lab.run("--address", "192.168.1.50", "--yes")
    assert r.returncode == 0, r.stderr
    assert env_of(lab.target)["KAJI_TLS_SITE"] == "192.168.1.50"
    assert "docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build" in lab.calls()
    assert (lab.target / "caddy-root.crt").read_text().strip() == "CERT"
    assert "https://192.168.1.50" in r.stdout


def test_rerun_keeps_the_env_and_secrets_and_updates_the_code(lab):
    lab.run("--local", "--yes")
    first = (lab.target / ".env").read_text()
    (lab.repo / "NOUVEAU").write_text("x")
    lab.git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    lab.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "maj")
    r = lab.run("--yes")
    assert r.returncode == 0, r.stderr
    assert (lab.target / ".env").read_text() == first             # jamais réécrit
    assert (lab.target / "NOUVEAU").exists()                      # git pull --ff-only
    assert "mis à jour" in r.stdout
    assert env_of(lab.target)["KAJI_SETUP_TOKEN"] not in r.stdout  # pas de jeton affiché pour une mise à jour


def test_rerun_on_a_tls_install_keeps_using_both_compose_files(lab):
    lab.run("--address", "kaji.home", "--yes")
    lab.log.write_text("")
    lab.run("--yes")
    assert "docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build" in lab.calls()


@pytest.mark.parametrize("bad", ["a b", "x;rm -rf /", "$(id)", "kaji.home:8443", "https://x", "-evil", "a/b", "é"])
def test_a_dangerous_address_is_refused_before_anything_is_written(lab, bad):
    r = lab.run("--address", bad, "--yes")
    assert r.returncode != 0 and "adresse invalide" in r.stderr
    assert not lab.target.exists() and lab.calls() == []


def test_address_and_local_are_mutually_exclusive(lab):
    assert lab.run("--address", "1.2.3.4", "--local", "--yes").returncode != 0


def test_a_non_empty_directory_that_is_not_kaji_is_refused_untouched(lab):
    lab.target.mkdir()
    (lab.target / "perso.txt").write_text("à moi")
    r = lab.run("--local", "--yes")
    assert r.returncode != 0 and "n'est pas un dépôt Kaji" in r.stderr
    assert (lab.target / "perso.txt").read_text() == "à moi" and not (lab.target / ".env").exists()


def test_local_modifications_block_the_update(lab):
    lab.run("--local", "--yes")
    (lab.target / "docker-compose.yml").write_text("modifié")
    r = lab.run("--yes")
    assert r.returncode != 0 and "modifications locales" in r.stderr


def test_dry_run_writes_nothing_and_calls_no_docker(lab):
    r = lab.run("--dry-run", "--local", "--yes")
    assert r.returncode == 0 and "simulation" in r.stdout
    assert not lab.target.exists()
    assert [c for c in lab.calls() if " up " in c] == []


def test_missing_docker_with_no_install_flag_stops_with_a_message(lab):
    r = lab.run("--local", "--yes", "--no-docker-install", SHIM_NO_COMPOSE="1")
    assert r.returncode != 0 and "--no-docker-install" in r.stderr
    assert not lab.target.exists()


def test_without_confirmation_docker_is_not_installed(lab):
    r = lab.run("--local", SHIM_NO_COMPOSE="1", stdin="n\n")      # sans --yes : la question reste sans réponse « oui »
    assert r.returncode != 0 and "Docker est nécessaire" in r.stderr
    assert not any(" install " in c or "apt-get" in c for c in lab.calls())


def test_unhealthy_kaji_fails_with_a_hint_and_does_not_claim_success(lab):
    r = lab.run("--local", "--yes", SHIM_UNHEALTHY="1")
    assert r.returncode != 0 and "Kaji est installé" not in r.stdout


def test_unknown_option_is_refused(lab):
    r = lab.run("--bogus")
    assert r.returncode != 0 and "option inconnue" in r.stderr


def test_the_script_never_pipes_the_network_into_a_shell():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "| sh" not in text and "| bash" not in text and "eval " not in text


def test_image_mode_pulls_then_starts_without_building_and_uses_the_override_file(lab):
    (lab.repo / "docker-compose.image.yml").write_text("services: {}\n")
    lab.git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    lab.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "image")
    r = lab.run("--local", "--yes", "--image")
    assert r.returncode == 0, r.stderr
    c = lab.calls()
    assert "docker compose -f docker-compose.yml -f docker-compose.image.yml pull" in c
    assert "docker compose -f docker-compose.yml -f docker-compose.image.yml up -d" in c
    assert not any("--build" in x for x in c)


def test_image_mode_explains_when_no_image_is_published_and_does_not_claim_success(lab):
    (lab.repo / "docker-compose.image.yml").write_text("services: {}\n")
    lab.git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    lab.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "image")
    r = lab.run("--local", "--yes", "--image", SHIM_NO_IMAGES="1")
    assert r.returncode != 0 and "images introuvables" in r.stderr and "Kaji est installé" not in r.stdout
    assert not any(" up " in x for x in lab.calls())


def test_image_flag_without_the_override_file_is_refused_with_a_hint(lab):
    r = lab.run("--local", "--yes", "--image")
    assert r.returncode != 0 and "retire --image" in r.stderr
