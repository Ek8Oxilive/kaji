"""Images de base épinglées par empreinte (jalon J1, ticket #427).

Ce qui dérive en silence : une nouvelle image ajoutée par étiquette seule (reconstruction non reproductible), une empreinte collée sans étiquette (illisible pour qui
met à jour), `latest`, un Dockerfile oublié, le script de mise à jour qui ne reconnaît plus les fichiers, Dependabot qui ne surveille plus les images.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ["backend/Dockerfile", "frontend/Dockerfile", "docker-compose.yml", "docker-compose.tls.yml"]
PINNED = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")


def _external_images() -> list[tuple[str, str]]:
    """(fichier, référence) de chaque image tirée d'un registre : `FROM x [AS y]` (hors étage interne) et `image: x`."""
    found = []
    for rel in FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        stages = set()
        for line in text.splitlines():
            m = re.match(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", line, re.I)
            if m:
                if m.group(1) not in stages:
                    found.append((rel, m.group(1)))
                if m.group(2):
                    stages.add(m.group(2))
            m = re.match(r"^\s*image:\s*(\S+)", line)
            if m:
                found.append((rel, m.group(1)))
    return found


def test_the_guard_sees_the_four_base_images():
    refs = {r.split("@")[0] for _, r in _external_images()}
    assert refs == {"python:3.12-slim", "node:22-alpine", "nginx:1.27-alpine", "caddy:2.8-alpine"}


def test_every_external_image_is_pinned_by_digest_and_keeps_its_tag():
    for rel, ref in _external_images():
        assert PINNED.fullmatch(ref), f"{rel} : {ref} doit être de la forme nom:étiquette@sha256:<64 hexa>"
        assert "latest" not in ref


def test_the_update_script_looks_at_every_file_that_has_a_pinned_image():
    script = (ROOT / "tools" / "image_digests.sh").read_text(encoding="utf-8")
    files = re.search(r'^FILES="([^"]+)"', script, re.M).group(1).split()
    for rel in {f for f, _ in _external_images()}:
        assert rel in files, f"{rel} a une image épinglée que tools/image_digests.sh ne contrôle pas"
    assert (ROOT / "tools" / "image_digests.sh").stat().st_mode & 0o111                  # exécutable


def test_dependabot_watches_the_docker_images():
    cfg = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    for eco, directory in (("docker", "/backend"), ("docker", "/frontend"), ("docker-compose", "/")):
        assert re.search(rf"package-ecosystem: {eco}\n\s+directory: {re.escape(directory)}\n", cfg), (eco, directory)


def test_ci_checks_that_the_caddy_image_can_be_pulled():
    """Le test de fumée ne construit que la pile de base : sans cette étape, une empreinte Caddy fausse ne serait vue qu'à l'installation du HTTPS."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "docker-compose.tls.yml pull tls" in ci


def test_the_docs_no_longer_say_the_images_are_unpinned():
    for rel in ("docs/deploiement.md", "docs/securite.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Images non verrouillées par empreinte" not in text
        assert "désignées par étiquette, non par empreinte" not in text
    assert "docs/images-et-versions.md" in (ROOT / "docs" / "deploiement.md").read_text(encoding="utf-8")
