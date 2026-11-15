"""Versions signées (jalon J4, ticket #458) : script de vérification (avec un faux `cosign`) et contrôles statiques du workflow de signature."""
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "verify_release.sh"
WORKFLOW_TEXT = (ROOT / ".github" / "workflows" / "release-sign.yml").read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)

FAKE_COSIGN = """#!/bin/sh
echo "$@" >> "$COSIGN_LOG"
[ -z "${COSIGN_FAIL:-}" ]
"""


@pytest.fixture
def release(tmp_path):
    bin_dir = tmp_path / "bin"; bin_dir.mkdir()
    (bin_dir / "cosign").write_text(FAKE_COSIGN); (bin_dir / "cosign").chmod(0o755)
    d = tmp_path / "dl"; d.mkdir()
    archive = d / "kaji-v1.0.0.tar.gz"; archive.write_bytes(b"contenu de l'archive")
    subprocess.run(["sh", "-c", f"cd {d} && sha256sum kaji-v1.0.0.tar.gz > kaji-v1.0.0.tar.gz.sha256"], check=True)
    (d / "kaji-v1.0.0.tar.gz.sigstore.json").write_text("{}")
    log = tmp_path / "cosign.log"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "COSIGN_LOG": str(log)}

    def run(*args, **extra):
        return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, env={**env, **extra})
    return type("R", (), {"dir": d, "archive": archive, "run": staticmethod(run), "log": log})


def test_an_authentic_release_passes_and_cosign_is_asked_for_the_workflow_identity(release):
    r = release.run(str(release.archive))
    assert r.returncode == 0 and "AUTHENTIQUE" in r.stdout and "Ek8Oxilive/kaji" in r.stdout
    call = release.log.read_text()
    assert f"--bundle {release.dir}/kaji-v1.0.0.tar.gz.sigstore.json" in call
    assert r"^https://github.com/Ek8Oxilive/kaji/\.github/workflows/release-sign\.yml@" in call
    assert "--certificate-oidc-issuer https://token.actions.githubusercontent.com" in call and call.strip().endswith("kaji-v1.0.0.tar.gz")


def test_another_repository_is_checked_against_its_own_identity_with_dots_escaped(release):
    r = release.run(str(release.archive), "autre.org/depot")
    assert r.returncode == 0
    assert r"^https://github.com/autre\.org/depot/\.github/workflows/release-sign\.yml@" in release.log.read_text()


def test_a_modified_archive_is_refused_before_cosign_is_even_called(release):
    release.archive.write_bytes(b"archive modifiee par quelqu'un")
    r = release.run(str(release.archive))
    assert r.returncode == 1 and "somme SHA-256" in r.stderr and "AUTHENTIQUE" not in r.stdout
    assert not release.log.exists()


def test_a_signature_that_cosign_rejects_is_refused(release):
    r = release.run(str(release.archive), COSIGN_FAIL="1")
    assert r.returncode == 1 and "REFUSÉE" in r.stderr and "AUTHENTIQUE" not in r.stdout


def test_missing_files_missing_tool_and_bad_arguments_exit_with_usage_code(release, tmp_path):
    assert release.run().returncode == 2 and release.run(str(tmp_path / "absent.tar.gz")).returncode == 2
    (release.dir / "kaji-v1.0.0.tar.gz.sigstore.json").unlink()
    r = release.run(str(release.archive))
    assert r.returncode == 2 and "sigstore.json" in r.stderr
    (release.dir / "kaji-v1.0.0.tar.gz.sigstore.json").write_text("{}")
    for bad in ("a b", "x;rm -rf /", "a$(id)", "dépôt"):
        assert release.run(str(release.archive), bad).returncode == 2, bad
    no_cosign = subprocess.run([str(SCRIPT), str(release.archive)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert no_cosign.returncode == 2 and "cosign" in no_cosign.stderr
    assert SCRIPT.stat().st_mode & 0o111


def _job():
    return WORKFLOW["jobs"]["sign"]


def test_workflow_signs_keyless_verifies_immediately_and_pins_cosign():
    on = WORKFLOW.get(True) or WORKFLOW["on"]
    assert on["push"]["tags"] == ["v*"] and "workflow_dispatch" in on
    steps = "\n".join((s.get("run") or "") + (s.get("uses") or "") + str(s.get("with") or "") for s in _job()["steps"])
    assert "cosign sign-blob --yes --bundle" in steps and "cosign verify-blob --bundle" in steps and "sha256sum -c" in steps
    assert "git archive --format=tar.gz" in steps and "--prefix=" in steps
    assert re.search(r"sigstore/cosign-installer@v\d+\.\d+\.\d+", steps) and re.search(r"cosign-release': 'v\d+\.\d+\.\d+", steps)           # épinglés, jamais « latest »
    assert 'release-sign\\.yml@' in WORKFLOW_TEXT and "https://token.actions.githubusercontent.com" in WORKFLOW_TEXT and "${GITHUB_REPOSITORY}" in WORKFLOW_TEXT
    assert "latest" not in steps.replace("ubuntu-latest", "")


def test_workflow_permissions_are_minimal_and_identity_token_only_in_the_signing_job():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert _job()["permissions"] == {"contents": "write", "id-token": "write"}


def test_workflow_never_creates_a_release_and_only_attaches_for_tags():
    upload = next(s for s in _job()["steps"] if "release" in (s.get("name") or "").lower())
    assert upload["if"] == "startsWith(github.ref, 'refs/tags/v')"                                    # le déclenchement manuel ne publie rien
    assert "gh release view" in upload["run"] and "release create" not in upload["run"] and "--clobber" in upload["run"]
    artifact = next(s for s in _job()["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert artifact["with"]["path"] == "dist/"                                                          # toujours conservé, tag ou non


def test_the_verification_regex_of_the_script_matches_the_one_of_the_workflow():
    script = SCRIPT.read_text(encoding="utf-8")
    assert r"\.github/workflows/release-sign\.yml@" in script and r"\.github/workflows/release-sign\.yml@" in WORKFLOW_TEXT
    assert "https://token.actions.githubusercontent.com" in script and (ROOT / ".github" / "workflows" / "release-sign.yml").exists()


def test_the_doc_is_honest_about_what_is_not_signed_or_not_run():
    doc = (ROOT / "docs" / "signature.md").read_text(encoding="utf-8")
    for needle in ("L'étiquette Git n'est pas signée", "git tag -s", "ne sont pas signés", "Jamais exécuté sur une vraie étiquette", "pas d'image de Kaji à signer", "Run workflow"):
        assert needle in doc, needle
