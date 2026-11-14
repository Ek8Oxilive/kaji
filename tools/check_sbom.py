#!/usr/bin/env python3
"""Contrôle un SBOM CycloneDX de Kaji (jalon J4, ticket #459) : un SBOM vide ou périmé est pire que pas de SBOM.

    tools/check_sbom.py python sbom-python.cdx.json backend/requirements.txt
    tools/check_sbom.py node   sbom-node.cdx.json   frontend/package-lock.json
    tools/check_sbom.py image  sbom-image-….cdx.json python:3.12-slim@sha256:…

Vérifie : JSON CycloneDX valide, composants non vides, chaque composant a un nom et une version ; et surtout que le SBOM **reflète le verrou** : chaque dépendance épinglée (`==` de
`requirements.txt`, entrées non-développement de `package-lock.json`) y figure **avec la même version** ; pour une image, que l'empreinte épinglée figure dans le SBOM (c'est bien CETTE image
qui a été analysée). Code de sortie 0 si tout va bien, 1 sinon (problèmes listés), 2 si l'usage est faux.
"""
import json
import re
import sys
from pathlib import Path


def load(path: str) -> tuple[dict | None, list[str]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, [f"{path} : JSON illisible ({type(e).__name__})"]
    problems = []
    if not isinstance(data, dict) or data.get("bomFormat") != "CycloneDX":
        problems.append("bomFormat n'est pas « CycloneDX »")
    if not isinstance(data, dict) or not isinstance(data.get("specVersion"), str):
        problems.append("specVersion absente")
    comps = data.get("components") if isinstance(data, dict) else None
    if not isinstance(comps, list) or not comps:
        problems.append("aucun composant")
        return data, problems
    for c in comps:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c["name"].strip():
            problems.append("un composant n'a pas de nom")
        elif not isinstance(c.get("version"), str) or not c["version"].strip():
            problems.append(f"{c['name']} : version absente")
    return data, problems


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins_from_requirements(text: str) -> dict[str, str]:
    pins = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([^\s;#]+)", line)
        if m:
            pins[norm(m.group(1))] = m.group(2)
    return pins


def prod_packages_from_lock(text: str) -> dict[str, str]:
    lock = json.loads(text)
    out = {}
    for path, info in (lock.get("packages") or {}).items():
        if not path.startswith("node_modules/") or not isinstance(info, dict) or info.get("dev") or info.get("devOptional"):
            continue
        name = path.split("node_modules/")[-1]
        if isinstance(info.get("version"), str):
            out[name] = info["version"]
    return out


def check(kind: str, sbom_path: str, reference: str) -> list[str]:
    data, problems = load(sbom_path)
    if data is None or any(p == "aucun composant" for p in problems):
        return problems
    have = {}
    for c in data["components"]:
        if isinstance(c, dict) and isinstance(c.get("name"), str):
            key = norm(c["name"]) if kind == "python" else c["name"] if "group" not in c else f"{c['group']}/{c['name']}"
            have.setdefault(key, set()).add(str(c.get("version")))
    if kind == "python":
        wanted = pins_from_requirements(Path(reference).read_text(encoding="utf-8"))
        if not wanted:
            problems.append(f"{reference} : aucune dépendance épinglée trouvée")
        for name, version in sorted(wanted.items()):
            if version not in have.get(name, set()):
                problems.append(f"{name}=={version} épinglé mais absent du SBOM (trouvé : {sorted(have.get(name, [])) or 'rien'})")
    elif kind == "node":
        wanted = prod_packages_from_lock(Path(reference).read_text(encoding="utf-8"))
        if not wanted:
            problems.append(f"{reference} : aucun paquet de production trouvé")
        for name, version in sorted(wanted.items()):
            if version not in have.get(name, set()):
                problems.append(f"{name}@{version} dans le verrou mais absent du SBOM (trouvé : {sorted(have.get(name, [])) or 'rien'})")
    elif kind == "image":
        digest = reference.split("@", 1)[1] if "@" in reference else ""
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            problems.append(f"{reference} : pas d'empreinte épinglée")
        elif digest not in Path(sbom_path).read_text(encoding="utf-8"):
            problems.append(f"l'empreinte {digest[:19]}… n'apparaît pas dans le SBOM : ce n'est peut-être pas cette image qui a été analysée")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("python", "node", "image"):
        print(__doc__)
        return 2
    problems = check(*argv)
    if problems:
        print(f"SBOM REFUSÉ ({argv[0]}) :", *problems, sep="\n  - ")
        return 1
    data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    print(f"SBOM {argv[0]} : {len(data['components'])} composants, conforme à {argv[2] if argv[0] != 'image' else 'l’image épinglée'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
