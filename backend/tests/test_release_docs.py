"""`SECURITY.md` et `CHANGELOG.md` (jalon J1, ticket #426) : ils doivent rester cohérents avec le dépôt.

Ce qui dérive en silence : un lien vers un fichier qui n'existe plus, une étiquette de version qui n'a plus de rubrique dans le journal, un « Non publié » qui disparaît
(les prochains changements n'auraient plus où aller), une adresse e-mail ou un secret glissé dans un fichier public.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_security_policy_has_the_sections_a_reporter_needs():
    for title in ("## Signaler une vulnérabilité", "## Versions suivies", "## Ce qui est dans le périmètre", "## Ce qui est hors périmètre"):
        assert title in SECURITY
    assert "Report a vulnerability" in SECURITY                      # canal privé de GitHub
    assert "jamais" in SECURITY and "KAJI_SECRET_KEY" in SECURITY    # consigne : ne pas joindre de secret


def test_security_and_changelog_cite_only_existing_files():
    for text in (SECURITY, CHANGELOG):
        for rel in sorted(set(re.findall(r"`((?:docs|backend|frontend|deploy)/[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.(?:md|yml|py))`", text))):
            assert (ROOT / rel).exists(), rel
        for rel in sorted(set(re.findall(r"`(docker-compose[A-Za-z.-]*\.yml|\.env\.example)`", text))):
            assert (ROOT / rel).exists(), rel
    assert (ROOT / "docs" / "securite.md").exists() and (ROOT / "docs" / "statut-fonctions.md").exists()


def test_no_email_address_and_no_secret_in_these_public_files():
    for text in (SECURITY, CHANGELOG):
        assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text.replace("kaji@pve", ""))
        assert not re.search(r"(?i)(token|secret|password|mot de passe)\s*[:=]\s*[A-Za-z0-9_\-]{16,}", text)


def test_changelog_structure_unreleased_then_versions_newest_first():
    headings = re.findall(r"^## \[([^\]]+)\](?: - (\d{4}-\d{2}-\d{2}))?$", CHANGELOG, re.M)
    assert headings and headings[0] == ("Non publié", "")              # « Non publié » toujours en tête
    versions = [(v, d) for v, d in headings[1:]]
    assert versions and all(re.fullmatch(r"\d+\.\d+\.\d+(-rc\d+)?", v) and d for v, d in versions)
    assert [d for _, d in versions] == sorted((d for _, d in versions), reverse=True)
    for name, _ in headings:                                             # chaque rubrique a son lien en bas
        assert re.search(rf"^\[{re.escape(name)}\]: https://", CHANGELOG, re.M), name


def test_every_git_tag_has_a_changelog_section():
    """Une version étiquetée sans rubrique dans le journal : exactement ce que le ticket veut empêcher (sautée si le dépôt n'a pas d'étiquettes, ex. clone peu profond)."""
    r = subprocess.run(["git", "tag", "-l", "v*"], cwd=ROOT, capture_output=True, text=True)
    tags = [t for t in r.stdout.split() if re.fullmatch(r"v\d+\.\d+\.\d+(-rc\d+)?", t)] if r.returncode == 0 else []
    for t in tags:
        assert f"## [{t[1:]}]" in CHANGELOG, f"{t} n'a pas de rubrique dans CHANGELOG.md"


def test_the_changelog_is_honest_about_the_release_status():
    assert "version candidate" in CHANGELOG and "lab interne non exposé" in CHANGELOG
    assert "Limites connues" in CHANGELOG and "jeton Proxmox partagé" in CHANGELOG
    assert "#427" in CHANGELOG                                           # le défaut « images non épinglées » y est dit
