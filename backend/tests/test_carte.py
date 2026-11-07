"""La carte du projet (`docs/CARTE.md`) est générée par `tools/carte.py` : elle ne doit jamais être périmée."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _build() -> str:
    spec = importlib.util.spec_from_file_location("carte", ROOT / "tools" / "carte.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build()


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def test_project_map_is_up_to_date():
    current = _norm((ROOT / "docs" / "CARTE.md").read_text(encoding="utf-8"))
    expected = _norm(_build())
    assert current == expected, "docs/CARTE.md est périmée : lance `python3 tools/carte.py > docs/CARTE.md` puis recommite"


def test_every_module_appears_in_the_map():
    carte = (ROOT / "docs" / "CARTE.md").read_text(encoding="utf-8")
    for f in list((ROOT / "backend" / "app").glob("*.py")) + list((ROOT / "backend" / "app" / "routers").glob("*.py")):
        if f.name != "__init__.py":
            assert f.relative_to(ROOT).as_posix() in carte, f"{f.name} absent de la carte"
