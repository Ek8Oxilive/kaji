#!/usr/bin/env python3
"""Génère `docs/CARTE.md` : la carte du projet (un fichier par ligne, avec son rôle et ses routes), pour retrouver vite où est quoi sans tout lire.

Usage : `python3 tools/carte.py > docs/CARTE.md`. Les rôles viennent des docstrings (Python) et des premiers commentaires `/** … */` (TypeScript) :
une phrase d'un fichier mal décrite doit être corrigée dans le fichier, pas ici.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX = 62


def clip(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s if len(s) <= MAX else s[: MAX - 1].rstrip() + "…"


def py_doc(p: Path) -> str:
    try:
        d = ast.get_docstring(ast.parse(p.read_text(encoding="utf-8")))
    except SyntaxError:
        d = None
    return clip(d.split("\n\n")[0]) if d else ""


ROUTE = re.compile(r'@router\.(get|post|put|delete|patch)\(\s*(?:f)?(?:"([^"]*)"|([A-Z_]+)(?:\s*\+\s*"([^"]*)")?)')
CONST = re.compile(r'^([A-Z_]+)\s*=\s*"([^"]+)"', re.M)


def routes(p: Path) -> str:
    src = p.read_text(encoding="utf-8")
    prefix = ""
    m = re.search(r'APIRouter\([^)]*prefix="([^"]*)"', src)
    if m:
        prefix = m.group(1).replace("/api/connections/{conn_id}", "")
    consts = dict(CONST.findall(src))
    out = []
    for verb, path, name, tail in ROUTE.findall(src):
        path = path or (consts.get(name, name) + (tail or ""))                  # chemin donné par une constante du fichier
        path = path.replace("{conn_id}", "").replace("/api/connections", "").replace("/{conn_id}", "")
        out.append(f"{verb.upper()} {prefix}{path}")
    return "; ".join(out[:4]) + (f" (+{len(out) - 4})" if len(out) > 4 else "")


def ts_doc(p: Path) -> str:
    m = re.search(r"/\*\*(.*?)\*/", p.read_text(encoding="utf-8"), re.S)
    return clip(re.sub(r"\n\s*\*", " ", m.group(1))) if m else ""


def section(title: str, files: list[Path], base: Path, doc, extra=None) -> list[str]:
    lines = [f"\n## {title}"]
    for f in sorted(files):
        if f.name == "__init__.py":
            continue
        d = doc(f)
        e = extra(f) if extra else ""
        lines.append(f"- `{f.relative_to(base)}` — {d}" + (f" — {e}" if e else ""))
    return lines


def main() -> None:
    out = ["# Carte du projet (générée : `python3 tools/carte.py > docs/CARTE.md`)", "",
           "Trouver où est quelque chose : `grep -i mot docs/CARTE.md`. Règles : un test par module (`backend/tests/test_<module>.py`) ; "
           "un doc d'API par fonction (`docs/api/<fonction>.md`) ; types front par domaine (`frontend/src/lib/types/<domaine>.ts`). "
           "Pour modifier une route : lire son routeur et son `*spec.py` (validation), pas plus."]
    app = ROOT / "backend/app"
    out += section("Backend : modules (validation, règles pures, client Proxmox)", [f for f in app.glob("*.py")], ROOT, py_doc)
    out += section("Backend : routeurs (auto-chargés, un fichier = une fonction)", list((app / "routers").glob("*.py")), ROOT, py_doc, routes)
    fe = ROOT / "frontend/src"
    out += section("Frontend : pages", list((fe / "pages").glob("*.tsx")), ROOT, ts_doc)
    out += section("Frontend : composants", list((fe / "components").rglob("*.tsx")), ROOT, ts_doc)
    out += section("Frontend : lib", [f for f in (fe / "lib").rglob("*.ts*")], ROOT, ts_doc)
    docs = ROOT / "docs"
    lines = ["\n## Documentation"]
    for f in sorted(docs.glob("*.md")) + sorted((docs / "api").glob("*.md")):
        m = re.search(r"^#\s+(.+)$", f.read_text(encoding="utf-8"), re.M)
        lines.append(f"- `{f.relative_to(ROOT)}` — {clip(m.group(1)) if m else ''}")
    out += lines
    print("\n".join(out))


if __name__ == "__main__":
    main()
