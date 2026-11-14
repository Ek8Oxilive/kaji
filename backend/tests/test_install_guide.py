"""Guide « Installer Kaji en lab » (`docs/installation-lab.md`, jalon J1, ticket #425) : il doit rester aligné sur le code.

Ce qui dérive en silence : un droit Proxmox ajouté à `FEATURES` mais absent du guide (l'installateur donne trop peu de droits), une variable de `.env.example`
que le guide n'explique pas, une commande du guide qui cite un fichier ou un module qui n'existe plus, un conseil qui contredit les garde-fous du dépôt
(rôle `Administrator`, option d'administration activée par défaut).
"""
import re
from pathlib import Path

from app.accessspec import FEATURES

ROOT = Path(__file__).resolve().parents[2]
GUIDE = (ROOT / "docs" / "installation-lab.md").read_text(encoding="utf-8")
ENV = (ROOT / ".env.example").read_text(encoding="utf-8")


def _rights_table() -> dict[str, str]:
    """Identifiant de fonction -> texte de la colonne « Droits » du tableau du guide."""
    rows = {}
    for line in GUIDE.splitlines():
        m = re.match(r"^\| `([a-z-]+)` \| [^|]+ \| (.+) \|$", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_every_feature_of_the_access_page_is_in_the_guide_with_its_exact_rights():
    rows = _rights_table()
    assert set(rows) == {f.id for f in FEATURES}                  # ni fonction manquante, ni fonction fantôme
    for f in FEATURES:
        for path, privs in f.needs:
            expected = f"`{path}` : " + ", ".join(f"`{p}`" for p in privs)
            assert expected in rows[f.id], f"{f.id} : « {expected} » absent du guide"


def test_the_guide_labels_match_the_access_page():
    for f in FEATURES:
        assert re.search(rf"^\| `{re.escape(f.id)}` \| {re.escape(f.label)} \|", GUIDE, re.M), f.id


def test_every_variable_of_env_example_is_explained():
    variables = set(re.findall(r"^#?\s*(KAJI_[A-Z_]+)=", ENV, re.M))
    assert {"KAJI_SECRET_KEY", "KAJI_SETUP_TOKEN", "KAJI_ADMIN_USE_KAJI_TOKEN", "KAJI_TLS_SITE"} <= variables     # le motif voit bien les variables commentées
    for v in sorted(variables):
        assert v in GUIDE, f"{v} n'est pas expliquée dans le guide"


def test_the_guide_never_tells_to_give_administrator_to_the_kaji_token():
    """Règle du cadrage : jamais `Administrator` au jeton de Kaji en entreprise ; les commandes du guide n'en contiennent pas."""
    commands = "\n".join(re.findall(r"```bash\n(.*?)```", GUIDE, re.S))
    assert "Administrator" not in commands and "Permissions.Modify" not in commands
    assert "pveum acl modify / --roles PVEAuditor --users 'kaji@pve' --tokens 'kaji@pve!kaji'" in commands
    assert "--privsep 1" in commands                                # jeton à privilèges séparés : lu avec `tokens-ecriture.md`


def test_the_dangerous_admin_option_stays_off_in_the_guide_and_in_the_example():
    assert re.search(r"^# KAJI_ADMIN_USE_KAJI_TOKEN=true", ENV, re.M)                   # commentée dans l'exemple
    assert not re.search(r"^KAJI_ADMIN_USE_KAJI_TOKEN=true", GUIDE, re.M)
    assert "laisse commenté" in GUIDE


def test_the_https_instructions_use_both_compose_files_and_the_real_port():
    assert "docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build" in GUIDE
    assert "8443" not in GUIDE                                      # Caddy écoute sur 443 (`KAJI_TLS_PORT`), pas 8443
    assert '"${KAJI_TLS_BIND:-0.0.0.0}:${KAJI_TLS_PORT:-443}:443"' in (ROOT / "docker-compose.tls.yml").read_text(encoding="utf-8")


def test_the_files_and_commands_cited_by_the_guide_exist():
    for rel in sorted(set(re.findall(r"`((?:docs|deploy|backend)/[A-Za-z0-9_./-]+\.(?:md|py|yml|conf))`", GUIDE))):
        assert (ROOT / rel).exists(), rel
    assert (ROOT / "docker-compose.tls.yml").exists() and (ROOT / "backend" / "app" / "admin_cli.py").exists()
    assert (ROOT / "backend" / "app" / "migrations.py").exists()
    cli = (ROOT / "backend" / "app" / "admin_cli.py").read_text(encoding="utf-8")
    assert "reset-password" in cli and "--user" in cli


def test_the_guide_says_what_it_has_not_proven():
    """Honnêteté : le guide dit qu'il n'a jamais été rejoué par un tiers et que la restauration n'est pas éprouvée (tickets #428 et #429)."""
    assert "#428" in GUIDE and "#429" in GUIDE
    assert "jamais rejoué de zéro" in GUIDE and "Pas encore éprouvé" in GUIDE
