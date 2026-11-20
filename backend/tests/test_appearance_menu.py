"""Menu « Apparence » (ticket #550) : thème et langue dans un seul menu, au lieu de deux sélecteurs toujours affichés."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
MENU = (SRC / "components" / "AppearanceMenu.tsx").read_text(encoding="utf-8")
LAYOUT = (SRC / "components" / "Layout.tsx").read_text(encoding="utf-8")
AUTH = (SRC / "pages" / "AuthScreen.tsx").read_text(encoding="utf-8")


def test_the_two_always_visible_switchers_are_gone_everywhere():
    assert not (SRC / "components" / "ThemeSwitcher.tsx").exists() and not (SRC / "components" / "LanguageSwitcher.tsx").exists()
    for p in SRC.rglob("*.tsx"):
        t = p.read_text(encoding="utf-8")
        assert "ThemeSwitcher" not in t and "LanguageSwitcher" not in t, p.name


def test_the_menu_is_used_on_wide_screens_small_screens_and_the_login_screen():
    assert LAYOUT.count("<AppearanceMenu />") == 2                         # en-tête de l'écran large + barre du haut du petit écran
    assert "<AppearanceMenu />" in AUTH


def test_the_menu_lists_every_theme_and_every_language_and_closes_properly():
    assert "THEMES.map" in MENU and "LANGS.map" in MENU                    # rien n'est écrit en dur : un thème ou une langue ajouté apparaît
    assert 'e.key === "Escape"' in MENU and 'document.addEventListener("mousedown", onDown)' in MENU     # Échap et clic à l'extérieur
    assert MENU.count('role="radiogroup"') == 2 and MENU.count('role="radio"') == 2
    assert 'aria-expanded={open}' in MENU and 'aria-haspopup="dialog"' in MENU


def test_choosing_keeps_the_menu_open_so_both_settings_can_be_changed():
    for call in ("setTheme(t.id)", "setLang(l.id)"):
        line = next(l for l in MENU.splitlines() if call in l)
        assert "setOpen(false)" not in line


def test_the_mobile_drawer_no_longer_holds_a_theme_switcher():
    drawer = LAYOUT[LAYOUT.index('id="menu-tiroir"'):LAYOUT.index("Écran large")]
    assert "Switcher" not in drawer and "AppearanceMenu" not in drawer
