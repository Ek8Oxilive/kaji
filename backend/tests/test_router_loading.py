import pkgutil

from app import routers
from app.main import app
from app.routers import load_routers


def test_every_router_module_is_loaded():
    names = [m.name for m in pkgutil.iter_modules(routers.__path__)]
    loaded = {id(r) for r in load_routers()}
    import importlib
    for n in names:
        mod = importlib.import_module(f"app.routers.{n}")
        if getattr(mod, "router", None) is not None:
            assert id(mod.router) in loaded, f"routeur non chargé : {n}"


def test_actions_router_comes_last_so_it_cannot_shadow_specific_routes():
    from app.routers import actions
    rs = load_routers()
    assert rs[-1] is actions.router and rs.count(actions.router) == 1


def test_no_specific_route_is_shadowed_by_the_generic_action_route(client):
    """Test de comportement : chaque route POST spécifique sous .../{vmid}/<mot> doit répondre elle-même.

    Si la route générique {action} la masquait, la réponse serait une erreur 422 portant sur le paramètre « action »."""
    client.post("/api/auth/setup", json={"username": "admin", "password": "un-mot-de-passe-solide"})
    specific = []
    for path, ops in app.openapi()["paths"].items():
        parts = path.strip("/").split("/")
        if "post" in ops and "{vmid}" in parts and parts.index("{vmid}") == len(parts) - 2 and parts[-1] != "{action}":
            specific.append(path)
    assert len(specific) >= 5, f"trop peu de routes spécifiques trouvées : {specific}"
    for path in specific:
        url = (path.replace("{conn_id}", "1").replace("{node}", "enzo").replace("{gtype}", "qemu").replace("{vmid}", "115")
                   .replace("{key}", "scsi0").replace("{name}", "abc"))
        r = client.post(url, json={})
        locs = [e["loc"] for e in r.json().get("detail", [])] if r.status_code == 422 and isinstance(r.json().get("detail"), list) else []
        assert ["path", "action"] not in locs, f"{path} est masquée par la route générique {{action}}"


def test_default_order_is_deterministic():
    assert [id(r) for r in load_routers()] == [id(r) for r in load_routers()]
