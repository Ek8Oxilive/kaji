"""Menu « Apparence » (tickets #550 et suivants) : thème, couleur d'accentuation et langue dans un seul menu, placé entre « Compte » et « Déconnexion »."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
MENU = (SRC / "components" / "AppearanceMenu.tsx").read_text(encoding="utf-8")
LAYOUT = (SRC / "components" / "Layout.tsx").read_text(encoding="utf-8")
AUTH = (SRC / "pages" / "AuthScreen.tsx").read_text(encoding="utf-8")
THEME = (SRC / "lib" / "theme.tsx").read_text(encoding="utf-8")
ACCENT = (SRC / "lib" / "accent.ts").read_text(encoding="utf-8")


def test_the_two_always_visible_switchers_are_gone_everywhere():
    assert not (SRC / "components" / "ThemeSwitcher.tsx").exists() and not (SRC / "components" / "LanguageSwitcher.tsx").exists()
    for p in SRC.rglob("*.tsx"):
        t = p.read_text(encoding="utf-8")
        assert "ThemeSwitcher" not in t and "LanguageSwitcher" not in t, p.name


def test_the_menu_sits_between_compte_and_deconnexion_in_the_sidebar_and_the_drawer():
    # `nav` est rendu par la barre latérale ET par le tiroir du petit écran : un seul emplacement pour les deux.
    nav = LAYOUT[LAYOUT.index("const nav = ("):LAYOUT.index("  return (\n    <div className=\"flex min-h-full")]
    assert nav.index('tr("Compte")') < nav.index('<AppearanceMenu variant="sidebar" />') < nav.index('tr("Déconnexion")')
    assert LAYOUT.count("<AppearanceMenu") == 1                             # plus dans l'en-tête de l'écran large ni dans la barre du haut du petit écran
    assert "<header" in LAYOUT and "md:hidden" in LAYOUT                    # la barre du haut du petit écran (menu + logo) reste
    assert "<AppearanceMenu />" in AUTH                                     # l'écran de connexion n'a pas de barre latérale


def test_the_menu_opens_outside_the_scrolling_sidebar_and_stays_in_the_window():
    assert "createPortal(" in MENU and "document.body" in MENU              # la barre latérale défile : un menu dedans serait coupé
    assert 'position: "fixed"' in MENU and "window.innerHeight" in MENU and "window.innerWidth" in MENU
    assert "bottom: window.innerHeight - r.top" in MENU                     # près du bas de l'écran : s'ouvre vers le haut


def test_the_menu_lists_every_theme_accent_and_language_and_closes_properly():
    assert "THEMES.map" in MENU and "LANGS.map" in MENU and "ACCENT_PRESETS.map" in MENU
    assert 'e.key === "Escape"' in MENU and 'document.addEventListener("mousedown", onDown)' in MENU
    assert 'window.addEventListener("resize", close)' in MENU
    assert MENU.count('role="radiogroup"') == 3 and MENU.count('role="radio"') == 4
    assert 'aria-expanded={open}' in MENU and 'aria-haspopup="dialog"' in MENU


def test_choosing_keeps_the_menu_open_so_several_settings_can_be_changed():
    for call in ("setTheme(t.id)", "setAccent(p.hex)", "setAccent(null)", "setAccent(e.target.value)", "setLang(l.id)"):
        line = next(l for l in MENU.splitlines() if call in l)
        assert "setOpen(false)" not in line


def test_every_accent_name_is_translated_and_every_preset_has_a_name():
    ids = re.findall(r'\{ id: "(\w+)", hex: "#[0-9a-f]{6}" \}', ACCENT)
    names = set(re.findall(r"(\w+): \(\) => tr\(", MENU))
    assert ids and set(ids) == names


def test_the_accent_is_chosen_fitted_to_the_applied_theme_stored_and_removable():
    assert 'fitAccent(accent, applied === "light" ? "light" : "dark")' in THEME                # ajustée au thème RÉELLEMENT appliqué (Auto compris)
    assert "removeProperty(\"--accent\")" in THEME and "removeProperty(\"--accentfg\")" in THEME   # « Défaut » rend la couleur du thème
    assert 'ACCENT_KEY = "kaji-accent"' in THEME and "isHex(v)" in THEME                         # une valeur du navigateur est revalidée avant usage
    assert "[theme, accent]" in THEME                                                           # changer de thème recalcule l'accent


def _node_ok():
    node = shutil.which("node")
    if not node:
        return None
    v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    return node if (int(v[0]), int(v[1])) >= (22, 6) else None


def test_the_accent_contrast_script_passes_for_presets_and_arbitrary_colors():
    node = _node_ok()
    if not node:
        pytest.skip("Node 22.6+ absent : le script est aussi lancé par la CI (job frontend, `npm run check:accent`)")
    r = subprocess.run([node, "--experimental-strip-types", "scripts/check-accent.mjs"], cwd=ROOT / "frontend", capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "0 échec" in r.stdout


def test_ci_runs_the_accent_check_and_npm_exposes_it():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "npm run check:accent" in ci
    assert "check-accent.mjs" in (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
