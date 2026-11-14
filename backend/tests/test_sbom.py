"""SBOM et audit (jalon J4, ticket #459) : le contrôleur `tools/check_sbom.py` refuse un SBOM vide, invalide ou PÉRIMÉ ; le workflow est cohérent avec le dépôt."""
import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_sbom", ROOT / "tools" / "check_sbom.py")
check_sbom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_sbom)
WORKFLOW_TEXT = (ROOT / ".github" / "workflows" / "sbom.yml").read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)
DIGEST = "sha256:" + "ab" * 32


def bom(components, **extra):
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": components, **extra}


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return str(p)


REQS = "fastapi==0.162.2\nuvicorn[standard]==0.54.0\n# commentaire\nPyJWT==2.15.1  # épinglé\nhttpx>=0.28\n"


def test_python_sbom_must_reflect_every_pin_with_the_same_version(tmp_path):
    reqs = write(tmp_path, "requirements.txt", REQS)
    good = write(tmp_path, "ok.json", bom([{"name": "fastapi", "version": "0.162.2"}, {"name": "uvicorn", "version": "0.54.0"}, {"name": "PyJWT", "version": "2.15.1"}, {"name": "starlette", "version": "1.0"}]))
    assert check_sbom.check("python", good, reqs) == []
    stale = write(tmp_path, "stale.json", bom([{"name": "fastapi", "version": "0.161.0"}, {"name": "uvicorn", "version": "0.54.0"}, {"name": "pyjwt", "version": "2.15.1"}]))
    problems = check_sbom.check("python", stale, reqs)
    assert len(problems) == 1 and "fastapi==0.162.2" in problems[0] and "0.161.0" in problems[0]            # version périmée détectée ; PyJWT/pyjwt : nom normalisé
    missing = write(tmp_path, "missing.json", bom([{"name": "fastapi", "version": "0.162.2"}]))
    assert {p.split("==")[0] for p in check_sbom.check("python", missing, reqs)} == {"uvicorn", "pyjwt"}


def test_name_normalisation_matches_pep_503():
    assert check_sbom.norm("Typing_Extensions") == check_sbom.norm("typing-extensions") == "typing-extensions"
    assert check_sbom.pins_from_requirements(REQS) == {"fastapi": "0.162.2", "uvicorn": "0.54.0", "pyjwt": "2.15.1"}      # extras, commentaires et `>=` gérés


LOCK = {"packages": {"": {"name": "kaji"}, "node_modules/react": {"version": "19.2.0"}, "node_modules/@novnc/novnc": {"version": "1.6.0"},
                     "node_modules/vite": {"version": "8.0.0", "dev": True}, "node_modules/@types/react": {"version": "19.0.0", "devOptional": True},
                     "node_modules/a/node_modules/nested": {"version": "2.0.0"}}}


def test_node_sbom_covers_production_packages_only(tmp_path):
    lock = write(tmp_path, "package-lock.json", LOCK)
    assert check_sbom.prod_packages_from_lock(Path(lock).read_text()) == {"react": "19.2.0", "@novnc/novnc": "1.6.0", "nested": "2.0.0"}      # ni développement, ni devOptional, ni la racine
    good = write(tmp_path, "ok.json", bom([{"name": "react", "version": "19.2.0"}, {"name": "novnc", "group": "@novnc", "version": "1.6.0"}, {"name": "nested", "version": "2.0.0"}]))
    assert check_sbom.check("node", good, lock) == []
    stale = write(tmp_path, "stale.json", bom([{"name": "react", "version": "18.0.0"}, {"name": "novnc", "group": "@novnc", "version": "1.6.0"}, {"name": "nested", "version": "2.0.0"}]))
    assert any("react@19.2.0" in p for p in check_sbom.check("node", stale, lock))


def test_image_sbom_needs_a_pinned_reference_and_to_talk_about_that_image(tmp_path):
    ref = f"python:3.12-slim@{DIGEST}"
    ok = write(tmp_path, "ok.json", bom([{"name": "libc6", "version": "2.36"}], metadata={"component": {"name": "docker.io/library/python"}}))
    assert check_sbom.check("image", ok, ref) == []                                                  # l'empreinte de l'INDEX n'a pas à figurer dans le SBOM (cas réel de syft)
    other = write(tmp_path, "other.json", bom([{"name": "libc6", "version": "2.36"}], metadata={"component": {"name": "docker.io/library/nginx"}}))
    assert any("« python »" in p for p in check_sbom.check("image", other, ref))                      # le SBOM d'une autre image est refusé
    assert any("pas d'empreinte" in p for p in check_sbom.check("image", ok, "python:3.12-slim"))
    assert check_sbom.check("image", ok, f"caddy:2.8-alpine@{DIGEST}") != [] and check_sbom.check("image", ok, f"registry.example.org/team/python:3@{DIGEST}") == []


@pytest.mark.parametrize("data,needle", [
    ("pas du json", "illisible"),
    ({"bomFormat": "SPDX", "specVersion": "1.6", "components": [{"name": "a", "version": "1"}]}, "CycloneDX"),
    ({"bomFormat": "CycloneDX", "components": [{"name": "a", "version": "1"}]}, "specVersion"),
    (bom([]), "aucun composant"),
    ({"bomFormat": "CycloneDX", "specVersion": "1.6"}, "aucun composant"),
    (bom([{"name": "a"}]), "version absente"),
    (bom([{"version": "1"}]), "pas de nom"),
    (bom([{"name": "  ", "version": "1"}]), "pas de nom"),
])
def test_invalid_or_empty_sboms_are_refused(tmp_path, data, needle):
    problems = check_sbom.check("python", write(tmp_path, "x.json", data), write(tmp_path, "r.txt", "a==1\n"))
    assert problems and any(needle in p for p in problems), problems


def test_command_line_exit_codes_and_usage(tmp_path, capsys):
    reqs = write(tmp_path, "r.txt", "fastapi==1\n")
    ok = write(tmp_path, "ok.json", bom([{"name": "fastapi", "version": "1"}]))
    ko = write(tmp_path, "ko.json", bom([{"name": "fastapi", "version": "2"}]))
    assert check_sbom.main(["python", ok, reqs]) == 0 and "conforme" in capsys.readouterr().out
    assert check_sbom.main(["python", ko, reqs]) == 1 and "REFUSÉ" in capsys.readouterr().out
    assert check_sbom.main([]) == 2 and check_sbom.main(["autre", ok, reqs]) == 2
    assert (ROOT / "tools" / "check_sbom.py").stat().st_mode & 0o111


def _steps(job):
    return "\n".join((s.get("run") or "") + (s.get("uses") or "") for s in WORKFLOW["jobs"][job]["steps"])


def test_workflow_triggers_cover_tags_pull_requests_schedule_and_manual_runs():
    on = WORKFLOW.get(True) or WORKFLOW["on"]
    assert on["push"]["tags"] == ["v*"] and "workflow_dispatch" in on and on["schedule"]
    paths = on["pull_request"]["paths"]
    for needed in ("backend/requirements.txt", "frontend/package-lock.json", "backend/Dockerfile", "frontend/Dockerfile", "docker-compose.tls.yml", "tools/check_sbom.py"):
        assert needed in paths, needed


def test_workflow_generates_and_checks_the_three_kinds_of_sbom_with_pinned_tools():
    steps = _steps("sbom")
    assert "cyclonedx-py environment" in steps and "pip install -q -r backend/requirements.txt" in steps       # environnement installé, pas le fichier seul
    assert "npm ci" in steps and "npm sbom --sbom-format cyclonedx --omit dev" in steps
    assert "tools/check_sbom.py python" in steps and "tools/check_sbom.py node" in steps and "tools/check_sbom.py image" in steps
    for tool in re.findall(r"(?:cyclonedx-bom|pip-audit)==([\d.]+)", WORKFLOW_TEXT):
        assert re.fullmatch(r"\d+\.\d+\.\d+", tool)
    assert re.search(r"cyclonedx-bom==\d+\.\d+\.\d+", WORKFLOW_TEXT) and re.search(r"anchore/syft:v\d+\.\d+\.\d+", WORKFLOW_TEXT) and ":latest" not in WORKFLOW_TEXT and "@latest" not in WORKFLOW_TEXT


def test_workflow_image_list_uses_the_same_pattern_and_files_as_the_digest_script():
    script = (ROOT / "tools" / "image_digests.sh").read_text(encoding="utf-8")
    pattern = re.search(r"grep -HoE '([^']+)'", script).group(1)
    assert pattern in WORKFLOW_TEXT
    for f in re.search(r'^FILES="([^"]+)"', script, re.M).group(1).split():
        assert f in WORKFLOW_TEXT, f"{f} n'est pas couvert par le SBOM des images"


def test_workflow_permissions_are_minimal_and_write_is_only_for_the_release_upload():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert WORKFLOW["jobs"]["sbom"]["permissions"] == {"contents": "write"} and "permissions" not in WORKFLOW["jobs"]["audit"]
    upload = next(s for s in WORKFLOW["jobs"]["sbom"]["steps"] if "release" in (s.get("name") or "").lower())
    assert upload["if"] == "startsWith(github.ref, 'refs/tags/v')" and "gh release view" in upload["run"] and "release create" not in upload["run"]      # jamais de création de release : geste du propriétaire


def test_audit_job_is_scheduled_only_and_honours_the_exceptions_file():
    assert "schedule" in WORKFLOW["jobs"]["audit"]["if"] and WORKFLOW["jobs"]["sbom"]["if"] == "github.event_name != 'schedule'"
    steps = _steps("audit")
    assert "pip-audit -r backend/requirements.txt" in steps and "npm audit --omit=dev" in steps and "tools/audit-exceptions.txt" in steps and "--ignore-vuln" in steps
    exceptions = (ROOT / "tools" / "audit-exceptions.txt").read_text(encoding="utf-8")
    active = [l for l in exceptions.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert active == [], "une exception d'audit active doit avoir sa justification et sa date de réexamen dans docs/sbom.md ou dans le fichier"


def test_the_doc_is_honest_about_what_was_not_run():
    doc = (ROOT / "docs" / "sbom.md").read_text(encoding="utf-8")
    assert "Jamais essayé en local" in doc and "syft" in doc and "#458" in doc and "n'est pas signé" in doc
