"""Chargement automatique des routeurs : ajouter un fichier `routers/xxx.py` exposant `router` suffit.

L'ordre compte pour FastAPI : la première route qui correspond gagne. `actions` porte la route générique
`POST …/guests/{node}/{type}/{vmid}/{action}`, qui intercepterait toute route plus spécifique de même forme
(on l'a déjà vécu avec `resize` et `snapshots`). Elle déclare donc `ORDER = 90` et passe en dernier ; les
autres modules gardent l'ordre par défaut (50), puis l'ordre alphabétique.
"""
import importlib
import pkgutil

DEFAULT_ORDER = 50


def load_routers():
    found = []
    for info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{info.name}")
        router = getattr(module, "router", None)
        if router is not None:
            found.append((getattr(module, "ORDER", DEFAULT_ORDER), info.name, router))
    return [router for _, _, router in sorted(found, key=lambda f: (f[0], f[1]))]
