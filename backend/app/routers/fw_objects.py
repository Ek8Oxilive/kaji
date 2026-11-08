"""Alias, IPSets (et entrées) et groupes de sécurité du pare-feu : créer, modifier, supprimer. Niveaux datacenter et machine. Verrous : `app/fwobjects.py`."""
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..fwobjects import (NAME, GROUP, AliasCreate, AliasUpdate, EntryBody, GroupCreate, IpsetCreate, Kind, check_entry, is_live, references)
from ..models import AdminUser
from ..networkspec import shape_aliases, shape_ipset_entries, shape_named, shape_options, shape_rules
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/firewall", tags=["firewall-write"], dependencies=[Depends(current_user)])
DIGEST = re.compile(r"^[0-9a-f]{40}$")
NAME_P = Path(pattern=NAME.pattern)
GROUP_P = Path(pattern=GROUP.pattern)


@dataclass
class Scope:
    base: str                 # `/cluster/firewall` ou `/nodes/{node}/{type}/{vmid}/firewall`
    label: str
    cluster: bool


def cluster_scope() -> Scope:
    return Scope("/cluster/firewall", "datacenter", True)


def guest_scope(node: str = Path(pattern=NODE), gtype: Literal["qemu", "lxc"] = Path(), vmid: int = Path(ge=100, le=999999999)) -> Scope:
    return Scope(f"/nodes/{node}/{gtype}/{vmid}/firewall", f"{gtype}/{vmid}@{node}", False)


class Ctx:
    def __init__(self, db, factory, user, conn_id, action, target):
        self.db, self.factory, self.user, self.conn_id, self.action, self.target = db, factory, user, conn_id, action, target

    def log(self, st, detail=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action, target=self.target, status=st, detail=detail)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method, path, /, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise

    def confirmed(self, confirm: bool, typed: str | None = None, expected: str | None = None):
        if not confirm:
            self.refuse("Écriture dans le pare-feu : renvoie la requête avec confirm=true", 400)
        if expected is not None and typed != expected:
            self.refuse("Le nom retapé ne correspond pas : écriture refusée", 400)


async def _enabled(c: Ctx, scope: Scope) -> bool:
    raw = await c.px("get", f"{scope.base}/options")
    return bool(shape_options("cluster" if scope.cluster else "guest", raw).get("enable"))


async def _all_rules(c: Ctx, scope: Scope) -> list[dict]:
    """Règles qui peuvent nommer un objet : celles du niveau ; au datacenter aussi celles des groupes et des nœuds. (Les règles des machines ne sont pas toutes relues : Proxmox tranche.)"""
    rules = shape_rules(await c.px("get", f"{scope.base}/rules"))
    if scope.cluster:
        for g in shape_named(await c.px("get", "/cluster/firewall/groups"), "group"):
            rules += shape_rules(await c.px("get", f"/cluster/firewall/groups/{g['name']}"))
        nodes = await c.px("get", "/nodes")
        for n in (nodes if isinstance(nodes, list) else []):
            if isinstance(n, dict) and isinstance(n.get("node"), str):
                rules += shape_rules(await c.px("get", f"/nodes/{n['node']}/firewall/rules"))
    return rules


async def _live_gate(c: Ctx, scope: Scope, kind: Kind, name: str, acknowledge: bool):
    """Verrou décidé par le serveur : objet utilisé par un pare-feu actif ⇒ `acknowledge_live` exigé."""
    hits = references(await _all_rules(c, scope), kind, name)
    if is_live(kind, name, hits, await _enabled(c, scope)) and not acknowledge:
        why = "ensemble intégré utilisé par Proxmox" if (kind == "ipset" and not hits) else f"règle(s) {', '.join(map(str, hits))} d'un pare-feu ACTIF"
        c.refuse(f"Objet en service ({why}) : une erreur peut couper l'accès. Renvoie la requête avec acknowledge_live=true pour confirmer", status.HTTP_409_CONFLICT)
    return hits


def _routes(prefix: str, dep, with_groups: bool):
    @router.post(f"{prefix}/aliases", status_code=status.HTTP_201_CREATED)
    async def create_alias(body: AliasCreate, conn_id: int, scope: Scope = Depends(dep), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                           user: AdminUser = Depends(current_user)):
        c = Ctx(db, factory, user, conn_id, "fw-alias-create", f"{scope.label}:{body.name}")
        c.confirmed(body.confirm)
        if any(a["name"] == body.name for a in shape_aliases(await c.px("get", f"{scope.base}/aliases"))):
            c.refuse("Cet alias existe déjà", status.HTTP_409_CONFLICT)
        await c.px("post", f"{scope.base}/aliases", name=body.name, cidr=body.cidr, **({"comment": body.comment} if body.comment else {}))
        if not any(a["name"] == body.name and a["cidr"] == body.cidr for a in shape_aliases(await c.px("get", f"{scope.base}/aliases"))):
            c.refuse("Proxmox n'a pas créé l'alias", status.HTTP_502_BAD_GATEWAY)
        c.log("started", f"{body.name} = {body.cidr}")
        return {"created": body.name}

    @router.put(f"{prefix}/aliases/{{name}}")
    async def update_alias(body: AliasUpdate, conn_id: int, name: str = NAME_P, scope: Scope = Depends(dep), db: Session = Depends(get_db),
                           factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
        c = Ctx(db, factory, user, conn_id, "fw-alias-update", f"{scope.label}:{name}")
        c.confirmed(body.confirm, body.type_name, name)
        raw = await c.px("get", f"{scope.base}/aliases")
        cur = next((a for a in shape_aliases(raw) if a["name"] == name), None)
        if cur is None:
            c.refuse("Alias inconnu", status.HTTP_404_NOT_FOUND)
        if cur["cidr"] == body.cidr and (cur["comment"] or None) == (body.comment or None):
            c.refuse("Aucune modification", 422)
        await _live_gate(c, scope, "alias", name, body.acknowledge_live)
        digest = next((r.get("digest") for r in raw if isinstance(r, dict) and r.get("name") == name and isinstance(r.get("digest"), str) and DIGEST.fullmatch(r["digest"])), None)
        await c.px("put", f"{scope.base}/aliases/{name}", cidr=body.cidr, **({"comment": body.comment} if body.comment else {}), **({"digest": digest} if digest else {}))
        if not any(a["name"] == name and a["cidr"] == body.cidr for a in shape_aliases(await c.px("get", f"{scope.base}/aliases"))):
            c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
        c.log("started", f"{cur['cidr']} -> {body.cidr}")
        return {"updated": name}

    @router.delete(f"{prefix}/aliases/{{name}}")
    async def delete_alias(conn_id: int, name: str = NAME_P, confirm: bool = Query(default=False), typed: str = Query(default="", max_length=70),
                           scope: Scope = Depends(dep), db: Session = Depends(get_db),
                           factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
        c = Ctx(db, factory, user, conn_id, "fw-alias-delete", f"{scope.label}:{name}")
        c.confirmed(confirm, typed, name)
        if not any(a["name"] == name for a in shape_aliases(await c.px("get", f"{scope.base}/aliases"))):
            c.refuse("Alias inconnu", status.HTTP_404_NOT_FOUND)
        hits = references(await _all_rules(c, scope), "alias", name)
        if hits:                                                      # supprimer un alias nommé par une règle la casserait : jamais, même confirmé
            c.refuse(f"Alias utilisé par la ou les règles {', '.join(map(str, hits))} : retire-le d'abord de ces règles", status.HTTP_409_CONFLICT)
        await c.px("delete", f"{scope.base}/aliases/{name}")
        if any(a["name"] == name for a in shape_aliases(await c.px("get", f"{scope.base}/aliases"))):
            c.refuse("Proxmox n'a pas supprimé l'alias", status.HTTP_502_BAD_GATEWAY)
        c.log("started", "supprimé")
        return {"deleted": name}

    @router.post(f"{prefix}/ipsets", status_code=status.HTTP_201_CREATED)
    async def create_ipset(body: IpsetCreate, conn_id: int, scope: Scope = Depends(dep), db: Session = Depends(get_db),
                           factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
        c = Ctx(db, factory, user, conn_id, "fw-ipset-create", f"{scope.label}:{body.name}")
        c.confirmed(body.confirm)
        if any(s["name"] == body.name for s in shape_named(await c.px("get", f"{scope.base}/ipset"), "name")):
            c.refuse("Cet IPSet existe déjà", status.HTTP_409_CONFLICT)
        await c.px("post", f"{scope.base}/ipset", name=body.name, **({"comment": body.comment} if body.comment else {}))
        if not any(s["name"] == body.name for s in shape_named(await c.px("get", f"{scope.base}/ipset"), "name")):
            c.refuse("Proxmox n'a pas créé l'IPSet", status.HTTP_502_BAD_GATEWAY)
        c.log("started", "créé (vide)")
        return {"created": body.name}

    @router.delete(f"{prefix}/ipsets/{{name}}")
    async def delete_ipset(conn_id: int, name: str = NAME_P, confirm: bool = Query(default=False), typed: str = Query(default="", max_length=70),
                           acknowledge_live: bool = Query(default=False), delete_members: bool = Query(default=False), scope: Scope = Depends(dep),
                           db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
        c = Ctx(db, factory, user, conn_id, "fw-ipset-delete", f"{scope.label}:{name}")
        c.confirmed(confirm, typed, name)
        if not any(s["name"] == name for s in shape_named(await c.px("get", f"{scope.base}/ipset"), "name")):
            c.refuse("IPSet inconnu", status.HTTP_404_NOT_FOUND)
        hits = references(await _all_rules(c, scope), "ipset", name)
        if hits:
            c.refuse(f"IPSet utilisé par la ou les règles {', '.join(map(str, hits))} : retire-le d'abord de ces règles", status.HTTP_409_CONFLICT)
        await _live_gate(c, scope, "ipset", name, acknowledge_live)          # `management` et `blacklist` : verrou même sans règle
        members = shape_ipset_entries(await c.px("get", f"{scope.base}/ipset/{name}"))
        if members and not delete_members:
            c.refuse(f"IPSet non vide ({len(members)} entrée(s)) : renvoie la requête avec delete_members=true pour le supprimer avec ses entrées", status.HTTP_409_CONFLICT)
        await c.px("delete", f"{scope.base}/ipset/{name}", **({"force": 1} if members else {}))
        if any(s["name"] == name for s in shape_named(await c.px("get", f"{scope.base}/ipset"), "name")):
            c.refuse("Proxmox n'a pas supprimé l'IPSet", status.HTTP_502_BAD_GATEWAY)
        c.log("started", f"supprimé ({len(members)} entrée(s))")
        return {"deleted": name, "members_deleted": len(members)}

    @router.post(f"{prefix}/ipsets/{{name}}/entries", status_code=status.HTTP_201_CREATED)
    async def add_entry(body: EntryBody, conn_id: int, name: str = NAME_P, scope: Scope = Depends(dep), db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
        c = Ctx(db, factory, user, conn_id, "fw-ipset-entry-add", f"{scope.label}:{name}")
        c.confirmed(body.confirm)
        if not any(s["name"] == name for s in shape_named(await c.px("get", f"{scope.base}/ipset"), "name")):
            c.refuse("IPSet inconnu", status.HTTP_404_NOT_FOUND)
        if any(e["cidr"] == body.cidr for e in shape_ipset_entries(await c.px("get", f"{scope.base}/ipset/{name}"))):
            c.refuse("Cette entrée existe déjà", status.HTTP_409_CONFLICT)
        await _live_gate(c, scope, "ipset", name, body.acknowledge_live)
        await c.px("post", f"{scope.base}/ipset/{name}", cidr=body.cidr, **({"comment": body.comment} if body.comment else {}), **({"nomatch": 1} if body.nomatch else {}))
        if not any(e["cidr"] == body.cidr for e in shape_ipset_entries(await c.px("get", f"{scope.base}/ipset/{name}"))):
            c.refuse("Proxmox n'a pas ajouté l'entrée", status.HTTP_502_BAD_GATEWAY)
        c.log("started", f"+ {body.cidr}" + (" (nomatch)" if body.nomatch else ""))
        return {"added": body.cidr, "ipset": name}

    @router.delete(f"{prefix}/ipsets/{{name}}/entries")
    async def remove_entry(conn_id: int, cidr: str = Query(max_length=70), name: str = NAME_P, confirm: bool = Query(default=False), typed: str = Query(default="", max_length=70),
                           acknowledge_live: bool = Query(default=False), scope: Scope = Depends(dep), db: Session = Depends(get_db),
                           factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
        c = Ctx(db, factory, user, conn_id, "fw-ipset-entry-remove", f"{scope.label}:{name}")
        try:
            check_entry(cidr)
        except ValueError as e:
            c.refuse(str(e), 422)
        c.confirmed(confirm, typed, cidr)
        if not any(e["cidr"] == cidr for e in shape_ipset_entries(await c.px("get", f"{scope.base}/ipset/{name}"))):
            c.refuse("Entrée inconnue", status.HTTP_404_NOT_FOUND)
        await _live_gate(c, scope, "ipset", name, acknowledge_live)
        await c.px("delete", f"{scope.base}/ipset/{name}/{quote(cidr, safe='')}")
        if any(e["cidr"] == cidr for e in shape_ipset_entries(await c.px("get", f"{scope.base}/ipset/{name}"))):
            c.refuse("Proxmox n'a pas retiré l'entrée", status.HTTP_502_BAD_GATEWAY)
        c.log("started", f"- {cidr}")
        return {"removed": cidr, "ipset": name}

    if with_groups:
        @router.post(f"{prefix}/groups", status_code=status.HTTP_201_CREATED)
        async def create_group(body: GroupCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
            c = Ctx(db, factory, user, conn_id, "fw-group-create", f"datacenter:{body.name}")
            c.confirmed(body.confirm)
            if any(g["name"] == body.name for g in shape_named(await c.px("get", "/cluster/firewall/groups"), "group")):
                c.refuse("Ce groupe existe déjà", status.HTTP_409_CONFLICT)
            await c.px("post", "/cluster/firewall/groups", group=body.name, **({"comment": body.comment} if body.comment else {}))
            if not any(g["name"] == body.name for g in shape_named(await c.px("get", "/cluster/firewall/groups"), "group")):
                c.refuse("Proxmox n'a pas créé le groupe", status.HTTP_502_BAD_GATEWAY)
            c.log("started", "créé (sans règle)")
            return {"created": body.name}

        @router.delete(f"{prefix}/groups/{{name}}")
        async def delete_group(conn_id: int, name: str = GROUP_P, confirm: bool = Query(default=False), typed: str = Query(default="", max_length=70),
                               db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
            c = Ctx(db, factory, user, conn_id, "fw-group-delete", f"datacenter:{name}")
            c.confirmed(confirm, typed, name)
            if not any(g["name"] == name for g in shape_named(await c.px("get", "/cluster/firewall/groups"), "group")):
                c.refuse("Groupe inconnu", status.HTTP_404_NOT_FOUND)
            hits = references(await _all_rules(c, cluster_scope()), "group", name)
            if hits:
                c.refuse(f"Groupe utilisé par la ou les règles {', '.join(map(str, hits))} : retire-le d'abord de ces règles", status.HTTP_409_CONFLICT)
            if shape_rules(await c.px("get", f"/cluster/firewall/groups/{name}")):
                c.refuse("Groupe non vide : supprime d'abord ses règles", status.HTTP_409_CONFLICT)
            await c.px("delete", f"/cluster/firewall/groups/{name}")
            if any(g["name"] == name for g in shape_named(await c.px("get", "/cluster/firewall/groups"), "group")):
                c.refuse("Proxmox n'a pas supprimé le groupe", status.HTTP_502_BAD_GATEWAY)
            c.log("started", "supprimé")
            return {"deleted": name}


_routes("/cluster", cluster_scope, with_groups=True)
_routes("/guests/{node}/{gtype}/{vmid}", guest_scope, with_groups=False)
