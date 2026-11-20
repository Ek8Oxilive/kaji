"""Publication des images sur ghcr.io (installation express, ticket #539) : ce qui doit rester vrai du workflow et du fichier Compose « image ».

Ce que ces tests ne prouvent pas : que le workflow tourne (il ne le peut que sur une étiquette ou à la main, après fusion).
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF_PATH = ROOT / ".github" / "workflows" / "publish-images.yml"
WF = yaml.safe_load(WF_PATH.read_text(encoding="utf-8"))
WF_TEXT = WF_PATH.read_text(encoding="utf-8")
OVERRIDE = yaml.safe_load((ROOT / "docker-compose.image.yml").read_text(encoding="utf-8"))
ON = WF.get("on", WF.get(True))                                       # PyYAML lit « on » comme le booléen True


def test_the_workflow_publishes_only_on_a_version_tag_or_by_hand_never_on_a_branch_or_pr():
    assert set(ON) == {"push", "workflow_dispatch"}
    assert ON["push"] == {"tags": ["v*"]}                             # aucune branche, aucune pull_request
    assert "pull_request" not in WF_TEXT.split("jobs:")[0]


def test_the_manual_run_builds_without_publishing_unless_asked():
    assert ON["workflow_dispatch"]["inputs"]["publier"]["default"] is False
    env = WF["jobs"]["images"]["env"]["PUBLISH"]
    assert "startsWith(github.ref, 'refs/tags/v')" in env and "inputs.publier" in env
    assert "if: env.PUBLISH == 'true'" in WF_TEXT                     # connexion au registre seulement pour publier
    assert 'push=""; [ "$PUBLISH" = "true" ] && push="--push"' in WF_TEXT


def test_permissions_are_minimal_and_packages_write_is_only_on_the_publishing_job():
    assert WF["permissions"] == {"contents": "read"}
    job = WF["jobs"]["images"]["permissions"]
    assert job == {"contents": "read", "packages": "write"}           # pas de id-token, pas de contents: write
    assert "secrets.GITHUB_TOKEN" in WF_TEXT and "secrets." not in WF_TEXT.replace("secrets.GITHUB_TOKEN", "")


def test_actions_are_pinned_to_an_exact_version_and_owner_is_lowercased():
    for use in re.findall(r"uses:\s*(\S+)", WF_TEXT):
        assert re.search(r"@v?\d+\.\d+(\.\d+)?$", use) or use.startswith("actions/checkout@v"), use
    assert "tr '[:upper:]' '[:lower:]'" in WF_TEXT                    # ghcr.io exige des minuscules


def test_images_built_are_the_two_compose_services_for_both_architectures():
    assert WF_TEXT.count("linux/amd64,linux/arm64") == 2               # la construction seule ET la publication visent les deux architectures
    assert '"backend:$BACKEND" "frontend:$WEB"' in WF_TEXT
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    assert base["backend"]["build"] == "./backend" and base["web"]["build"] == "./frontend"


def test_the_override_names_match_what_the_workflow_publishes_and_default_to_latest():
    imgs = {k: v["image"] for k, v in OVERRIDE["services"].items()}
    assert imgs == {"backend": "ghcr.io/ek8oxilive/kaji-backend:${KAJI_VERSION:-latest}", "web": "ghcr.io/ek8oxilive/kaji-web:${KAJI_VERSION:-latest}"}
    assert 'echo "BACKEND=ghcr.io/$owner/kaji-backend"' in WF_TEXT and 'echo "WEB=ghcr.io/$owner/kaji-web"' in WF_TEXT


def test_the_override_changes_nothing_else_than_the_two_image_names():
    assert set(OVERRIDE) == {"services"} and all(set(v) == {"image"} for v in OVERRIDE["services"].values())


def test_the_docs_say_the_images_are_not_signed_and_that_the_package_must_be_made_public():
    doc = (ROOT / "docs" / "images-et-versions.md").read_text(encoding="utf-8")
    assert "Pas signées" in doc and "public" in doc and "aucun agent" in doc
    assert "ne sont pas signées" in (ROOT / "docs" / "signature.md").read_text(encoding="utf-8")


def test_install_script_uses_the_override_only_with_image_flag_and_refuses_without_the_file():
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "docker-compose.image.yml" in sh and "retire --image" in sh
