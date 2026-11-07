from app.main import app


def test_every_parameter_pattern_is_anchored():
    """Pydantic cherche un `pattern` N'IMPORTE OÙ dans la chaîne : sans `^` et `$`, « .mgr » passe le motif d'un nom de pool, car il
    contient « mgr ». Tout motif de chemin ou de requête doit donc être ancré. (Défaut réel trouvé à la relecture d'une mutation.)"""
    unanchored, total = [], 0
    for path, ops in app.openapi()["paths"].items():
        for method, op in ops.items():
            for prm in op.get("parameters", []):
                pat = prm.get("schema", {}).get("pattern")
                if pat is None:
                    continue
                total += 1
                if not (pat.startswith("^") and pat.endswith("$")):
                    unanchored.append(f"{method.upper()} {path} {prm['name']} : {pat}")
    assert total > 20, "le contrôle ne voit plus assez de motifs : le schéma OpenAPI a-t-il changé ?"
    assert not unanchored, "Motifs non ancrés (ajouter ^ et $) :\n" + "\n".join(unanchored)
