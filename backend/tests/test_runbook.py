"""`docs/runbook.md` (jalon J4, ticket #461) : il doit rester cohérent avec le code, et honnête sur ce qu'il n'a pas prouvé."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
CLI = (ROOT / "backend" / "app" / "admin_cli.py").read_text(encoding="utf-8")


def test_the_runbook_covers_what_the_ticket_asks_for():
    for title in ("## 1. Supervision de Kaji lui-même", "## 3. Rotation des secrets", "## 4. Restauration", "## 6. Incidents", "## 7. Ce qui manque"):
        assert title in RUNBOOK
    for secret in ("KAJI_SECRET_KEY", "KAJI_TOKEN_KEY", "KAJI_SETUP_TOKEN", "Jeton partagé", "Jeton personnel", "Jeton de service"):
        assert secret in RUNBOOK
    assert "Kaji lui-même est peut-être compromis" in RUNBOOK and "Un jeton Proxmox a fuité" in RUNBOOK


def test_every_admin_command_cited_by_the_runbook_exists():
    for cmd in sorted(set(re.findall(r"app\.admin_cli ([a-z-]+)", RUNBOOK))):
        assert f'"{cmd}"' in CLI, f"commande {cmd} citée par le runbook mais absente d'admin_cli"
    assert {"verify", "reset-password", "rotate-secret-key"} <= set(re.findall(r"app\.admin_cli ([a-z-]+)", RUNBOOK))


def test_every_file_and_script_cited_by_the_runbook_exists():
    for rel in sorted(set(re.findall(r"`((?:docs|tools|backend|deploy)/[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.(?:md|sh|py|yml|conf))`", RUNBOOK)) | {"tools/backup.sh", "tools/restore.sh", "tools/image_digests.sh", "SECURITY.md", "CHANGELOG.md"}):
        assert (ROOT / rel).exists(), rel
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    for var in set(re.findall(r"`(KAJI_[A-Z_]+)`", RUNBOOK)):
        assert var in env or var in CLI or var in (ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8").upper(), f"{var} inconnue du code"


def test_the_runbook_is_honest_about_what_was_not_proven():
    assert "jamais rejoué" in RUNBOOK and "#461" in RUNBOOK and "#462" in RUNBOOK
    assert "Rien n'avertit tout seul" in RUNBOOK and "n'expose **pas** de métriques" in RUNBOOK
    assert "jamais avec le vrai Docker" in RUNBOOK


def test_the_secret_key_rotation_steps_keep_both_keys_and_warn_about_sessions():
    assert "KAJI_SECRET_KEY_PREVIOUS" in RUNBOOK and "rotate-secret-key --yes" in RUNBOOK
    assert "Toutes les sessions sont tombées" in RUNBOOK and "tools/backup.sh" in RUNBOOK
