"""Garde de la traduction de l'interface (français / anglais).

Le texte français du code EST la clé : `tr("Machine {name} démarrée", { name })`. Ce test vérifie, sans lancer le frontend :
1. chaque clé `tr("…")` / `T("…")` du code existe dans `frontend/src/lib/en.json`, avec une valeur non vide ;
2. les variables `{nom}` sont les mêmes dans la clé et dans la traduction ;
3. `en.json` ne garde pas de clé orpheline (texte supprimé du code) ;
4. aucun texte JSX ni attribut de texte (`title=`, `placeholder=`…) n'est resté en français brut, hors `tr(…)`.
Ajouter un texte visible : l'envelopper dans `tr("…")` et ajouter sa traduction dans `en.json`.
"""
import json
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
EN = SRC / "lib" / "en.json"
CALL = re.compile(r"""\b(?:tr|T)\(\s*(?P<q>["'`])(?P<s>(?:(?!(?P=q))[^\\\n]|\\.)*)(?P=q)""")
VAR = re.compile(r"\{(\w+)\}")
LETTER = "A-Za-zÀ-ÿ"


def sources():
    return [p for p in SRC.rglob("*") if p.suffix in (".ts", ".tsx") and p.name != "i18n.ts"]


def code_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for p in sources():
        for m in CALL.finditer(p.read_text(encoding="utf-8")):
            s = m.group("s")
            if m.group("q") == "`" and "${" in s:
                continue                                           # gabarit avec expressions : pas une clé littérale
            try:
                key = json.loads(f'"{s}"') if m.group("q") != "'" else s.replace("\\'", "'")
            except json.JSONDecodeError:
                key = s
            keys.setdefault(key, p.name)
    return keys


def en() -> dict[str, str]:
    return json.loads(EN.read_text(encoding="utf-8"))


def test_every_key_is_translated():
    d = en()
    missing = sorted(k for k in code_keys() if k not in d)
    assert not missing, f"{len(missing)} texte(s) sans traduction dans frontend/src/lib/en.json, par exemple : {missing[:5]}"


def test_translations_are_not_empty_and_keep_their_variables():
    bad = [k for k, v in en().items() if not isinstance(v, str) or not v.strip() or sorted(VAR.findall(k)) != sorted(VAR.findall(v))]
    assert not bad, f"{len(bad)} traduction(s) vide(s) ou aux variables {{…}} différentes, par exemple : {bad[:5]}"


def test_no_orphan_translation():
    used = set(code_keys())
    orphans = sorted(k for k in en() if k not in used)
    assert not orphans, f"{len(orphans)} traduction(s) de textes qui n'existent plus dans le code, par exemple : {orphans[:5]}"


def test_no_raw_french_text_left_in_jsx():
    text = re.compile(rf">\s*[{LETTER}][^<>{{}}=;]{{2,}}</")
    attr = re.compile(rf"""\b(?:placeholder|title|aria-label|alt|label|hint|subtitle|submitLabel|tooltip|help)="[^"]*[{LETTER}][^"]*\"""")
    hits = []
    for p in sources():
        if p.suffix != ".tsx":
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith(("//", "*", "/*")) or "=>" in line:
                continue
            if text.search(line) or attr.search(line):
                hits.append(f"{p.relative_to(SRC)}:{n}")
    assert not hits, f"texte visible non enveloppé dans tr(…) : {hits[:8]}"
