#!/usr/bin/env python3
"""Produit la base d'exemple d'une version de Kaji avec le VRAI code de cette version (test de mise à jour, jalon J3, ticket #456).

    backend/.venv/bin/python tools/snapshot_db.py <référence git> <fichier de sortie.db>
    backend/.venv/bin/python tools/snapshot_db.py v1.0.0-rc1 backend/tests/fixtures/db/kaji-v1.0.0-rc1.db

À lancer **à chaque publication d'une version** (docs/images-et-versions.md) : la CI migre chaque base de `backend/tests/fixtures/db/` vers le code courant. Le code de la référence
est extrait dans un worktree temporaire (retiré ensuite) et exécuté avec les dépendances du Python qui lance ce script. Les données sont fictives, la clé est celle des tests.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_KEY = "cle-de-test-publique-pour-les-bases-d-exemple-0123456789"
PASSWORD = "mot-de-passe-de-test-12"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    ref, out = argv[0], Path(argv[1]).resolve()
    if out.exists():
        print(f"{out} existe déjà : supprime-le d'abord (une base d'exemple publiée ne se réécrit pas en silence).", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "src"
        subprocess.run(["git", "worktree", "add", "--detach", str(tree), ref], cwd=ROOT, check=True, capture_output=True)
        try:
            env = {**os.environ, "DATABASE_URL": f"sqlite:///{out}", "KAJI_SECRET_KEY": FIXTURE_KEY, "KAJI_SCHEDULER": "false", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": str(tree / "backend")}
            out.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "snapshot_db_populate.py"), FIXTURE_KEY, PASSWORD], cwd=tree / "backend", env=env, capture_output=True, text=True)
            if r.returncode != 0:
                print(r.stdout + r.stderr, file=sys.stderr)
                out.unlink(missing_ok=True)
                return 1
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, capture_output=True)
    out.chmod(0o600)
    sha = subprocess.run(["git", "rev-parse", "--short", ref], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    print(f"{out.name} : base d'exemple produite par le code de {ref} ({sha}), clé de test publique, données fictives.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
