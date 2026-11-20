"""Assistant de première connexion (installation express, ticket #541) : il doit rester aligné sur `tools/proxmox-setup.sh` et ne jamais toucher au secret du jeton."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMP = (ROOT / "frontend" / "src" / "components" / "FirstConnectionGuide.tsx").read_text(encoding="utf-8")
PAGE = (ROOT / "frontend" / "src" / "pages" / "Connections.tsx").read_text(encoding="utf-8")
SCRIPT = (ROOT / "tools" / "proxmox-setup.sh").read_text(encoding="utf-8")


def test_the_downloaded_script_exists_in_the_repo_at_the_advertised_path():
    url = re.search(r'const SCRIPT = "([^"]+)"', COMP).group(1)
    assert url.startswith("https://raw.githubusercontent.com/Ek8Oxilive/kaji/main/")
    assert (ROOT / url.split("/main/")[1]).is_file()


def test_the_commands_shown_are_download_read_then_run_never_a_pipe_into_a_shell():
    assert "| sh" not in COMP and "| bash" not in COMP
    cmds = re.search(r"const COMMANDS = \[(.*?)\];", COMP, re.S).group(1)
    assert cmds.index("curl -fsSL") < cmds.index("less proxmox-setup.sh") < cmds.index("sh proxmox-setup.sh")


def test_prefilled_values_are_the_defaults_of_the_script():
    m = re.search(r'user: "([^"]+)", token_id: "([^"]+)", port: (\d+)', PAGE)
    assert m, "valeurs du pré-remplissage introuvables"
    assert f'PVE_USER="{m.group(1)}"' in SCRIPT and f'TOKEN_ID="{m.group(2)}"' in SCRIPT and m.group(3) == "8006"


def test_the_guide_never_handles_the_token_secret_and_opens_only_when_no_cluster_exists():
    for forbidden in ("token_secret", "<input", "password", "api(", "fetch(", "localStorage"):
        assert forbidden not in COMP, forbidden                       # aucun champ, aucun appel réseau, rien de gardé : il ne fait qu'afficher et pré-remplir
    assert "empty={items?.length === 0}" in PAGE and "<details open={empty}" in COMP
