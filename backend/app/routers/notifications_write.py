"""Notifications en ÉCRITURE : cibles (sendmail, SMTP, Gotify, webhook), règles (matchers), test d'envoi. Validation et secrets : `app/notifwrite.py`.

Droits Proxmox : `Mapping.Modify` sur `/mapping/notifications` (plus `Sys.Audit` ou `Sys.Modify` sur `/`). Toute écriture exige `confirm=true` (`dry_run` pour voir sans rien écrire) ;
supprimer exige aussi le nom retapé (`type_name`) ; une cible encore utilisée par une règle, une cible ou une règle intégrée ne se suppriment pas. Les secrets ne sont jamais relus,
journalisés ni renvoyés. **Tester une cible envoie un VRAI message** : `confirm` + nom retapé, au plus une fois par minute et par cible.
"""
import time

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_client_factory
from ..metricsspec import digest_of
from ..models import AdminUser
from ..notificationspec import NAME, shape_endpoint, shape_matchers, shape_targets
from ..notifwrite import SECRET_FIELDS, WIRE, EndpointCreate, EndpointUpdate, Locks, MatcherCreate, MatcherUpdate, build_endpoint, build_matcher
from .auth import current_user
from .cluster import Factory
from .metrics_servers import Ctx

router = APIRouter(prefix="/api/connections/{conn_id}/notifications", tags=["notifications-write"], dependencies=[Depends(current_user)])
BASE = "/cluster/notifications"
TYPE_PATH = "^(sendmail|smtp|gotify|webhook)$"
TEST_INTERVAL = 60.0
_LAST_TEST: dict[tuple[int, str], float] = {}
_clock = time.monotonic                                              # remplaçable par les tests
FROM_WIRE = {"from-address": "from_address", "mailto-user": "mailto_user", "header": "header_names", "secret": "secret_names", "body": "body_set"}
SECRET_WIRE = {WIRE[f] for f in SECRET_FIELDS} | {"body"}            # jamais vérifiés après écriture (non relus, ou encodés)


def _masked(params: dict) -> dict:
    return {k: ("défini" if k in SECRET_WIRE else v) for k, v in params.items()}


def _txt(params: dict, delete: list[str]) -> str:
    return ", ".join(f"{k}={'défini' if k in SECRET_WIRE else v}" for k, v in sorted(params.items())) + (f" ; retiré : {','.join(delete)}" if delete else "")


def _same(after: dict, params: dict) -> bool:
    """Les valeurs NON secrètes relues sont-elles celles qu'on a écrites ? Les secrets ne sont pas relus par Proxmox : non vérifiés."""
    for k, v in params.items():
        if k in SECRET_WIRE:
            continue
        key = FROM_WIRE.get(k, k)
        got = after.get(key)
        if isinstance(v, list):
            if set(got or []) != set(v):
                return False
        elif k == "disable":
            if bool(got) != bool(v):
                return False
        elif k == "comment":
            if (got or "").rstrip("\n") != v.rstrip("\n"):
                return False
        elif got != v:
            return False
    return True


async def _targets(c: Ctx) -> list[dict]:
    return shape_targets(await c.px("get", f"{BASE}/targets"))


async def _matchers(c: Ctx) -> list[dict]:
    return shape_matchers(await c.px("get", f"{BASE}/matchers"))


async def _endpoint(c: Ctx, typ: str, name: str) -> tuple[dict, str | None]:
    raw = await c.px("get", f"{BASE}/endpoints/{typ}/{name}")
    raw = raw if isinstance(raw, dict) else {}
    d = shape_endpoint({**raw, "name": name}, typ)
    if d is None:
        c.refuse("Configuration illisible", status.HTTP_502_BAD_GATEWAY)
    pve = raw.get("digest") if isinstance(raw.get("digest"), str) else None
    d["digest"] = digest_of(d)
    return d, pve


def _need_confirm(c: Ctx, body):
    if not body.dry_run and not body.confirm:
        c.refuse("Écriture : renvoie la requête avec confirm=true (ou dry_run=true pour un aperçu)", status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------- cibles
@router.post("/targets/{typ}", status_code=status.HTTP_201_CREATED)
async def create_target(body: EndpointCreate, conn_id: int, typ: str = Path(pattern=TYPE_PATH), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                        user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "notif-target-create", f"{typ}:{body.name}")
    try:
        params, _ = build_endpoint(typ, body, [], creating=True)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.dry_run:
        return {"dry_run": True, "params": {"name": body.name, **_masked(params)}}
    _need_confirm(c, body)
    if any(t["name"] == body.name for t in await _targets(c)):
        c.refuse("Une cible porte déjà ce nom", status.HTTP_409_CONFLICT)
    await c.px("post", f"{BASE}/endpoints/{typ}", name=body.name, **params)
    if not any(t["name"] == body.name and t["type"] == typ for t in await _targets(c)):
        c.refuse("Proxmox n'a pas appliqué la création", status.HTTP_502_BAD_GATEWAY)
    after, _ = await _endpoint(c, typ, body.name)
    if not _same(after, params):
        c.refuse("Proxmox n'a pas appliqué la création", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"{typ} ; {_txt(params, [])}")
    return after


@router.put("/targets/{typ}/{name}")
async def update_target(body: EndpointUpdate, conn_id: int, typ: str = Path(pattern=TYPE_PATH), name: str = Path(pattern=NAME.pattern), db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "notif-target-update", f"{typ}:{name}")
    if not any(t["name"] == name and t["type"] == typ for t in await _targets(c)):
        c.refuse("Cible introuvable", status.HTTP_404_NOT_FOUND)
    cur, pve_digest = await _endpoint(c, typ, name)
    try:
        params, delete = build_endpoint(typ, body, list(body.clear), creating=False)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.digest is not None and body.digest != cur["digest"]:
        c.refuse("La cible a changé depuis ta lecture (digest périmé) : recharge avant de modifier", status.HTTP_409_CONFLICT)
    if body.dry_run:
        return {"dry_run": True, "params": _masked(params), "remove": delete}
    _need_confirm(c, body)
    send = dict(params)
    if delete:
        send["delete"] = delete
    if pve_digest:
        send["digest"] = pve_digest
    await c.px("put", f"{BASE}/endpoints/{typ}/{name}", **send)
    after, _ = await _endpoint(c, typ, name)
    if not _same(after, params):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, delete))
    return after


@router.delete("/targets/{typ}/{name}")
async def delete_target(conn_id: int, typ: str = Path(pattern=TYPE_PATH), name: str = Path(pattern=NAME.pattern), confirm: bool = Query(default=False),
                        type_name: str | None = Query(default=None, max_length=64), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Supprime une cible. Refusé : cible intégrée (`mail-to-root`), cible encore utilisée par une règle."""
    c = Ctx(db, factory, conn_id, user, "notif-target-delete", f"{typ}:{name}")
    target = next((t for t in await _targets(c) if t["name"] == name and t["type"] == typ), None)
    if target is None:
        c.refuse("Cible introuvable", status.HTTP_404_NOT_FOUND)
    if target["builtin"]:
        c.refuse("Cible intégrée de Proxmox : elle ne peut pas être supprimée", status.HTTP_422_UNPROCESSABLE_ENTITY)
    users = sorted(m["name"] for m in await _matchers(c) if name in m["targets"])
    if users:
        c.refuse(f"Cette cible est utilisée par des règles ({', '.join(users)}) : retire-la d'abord de ces règles", status.HTTP_409_CONFLICT)
    if dry_run:
        return {"dry_run": True, "remove": [name], "retype": name}
    if not confirm:
        c.refuse("Suppression : renvoie la requête avec confirm=true et le nom retapé (type_name)", status.HTTP_400_BAD_REQUEST)
    if type_name != name:
        c.refuse("Le nom retapé ne correspond pas : suppression refusée", status.HTTP_400_BAD_REQUEST)
    await c.px("delete", f"{BASE}/endpoints/{typ}/{name}")
    if any(t["name"] == name for t in await _targets(c)):
        c.refuse("Proxmox n'a pas supprimé la cible", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "cible supprimée")
    return {"deleted": name}


class TestBody(Locks):
    type_name: str | None = None


@router.post("/targets/{name}/test")
async def test_target(body: TestBody, conn_id: int, name: str = Path(pattern=NAME.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                      user: AdminUser = Depends(current_user)):
    """ENVOIE RÉELLEMENT un message de test à la cible. `confirm=true` + nom retapé ; une fois par minute et par cible. `dry_run` : vérifie sans envoyer."""
    c = Ctx(db, factory, conn_id, user, "notif-test", name)
    target = next((t for t in await _targets(c) if t["name"] == name), None)
    if target is None:
        c.refuse("Cible introuvable", status.HTTP_404_NOT_FOUND)
    if target["disable"]:
        c.refuse("Cette cible est désactivée : active-la avant de la tester", status.HTTP_409_CONFLICT)
    if body.dry_run:
        return {"dry_run": True, "target": name, "type": target["type"], "sends_a_real_message": True}
    if not body.confirm:
        c.refuse("Cela envoie un VRAI message : renvoie la requête avec confirm=true et le nom de la cible retapé (type_name)", status.HTTP_400_BAD_REQUEST)
    if body.type_name != name:
        c.refuse("Le nom retapé ne correspond pas : test refusé", status.HTTP_400_BAD_REQUEST)
    key, now = (conn_id, name), _clock()
    wait = TEST_INTERVAL - (now - _LAST_TEST[key]) if key in _LAST_TEST else 0
    if wait > 0:
        c.refuse(f"Cette cible a déjà été testée il y a moins d'une minute : réessaie dans {int(wait) + 1} s", status.HTTP_429_TOO_MANY_REQUESTS)
    _LAST_TEST[key] = now                                           # compté dès l'envoi : un échec ne permet pas de réessayer en boucle
    await c.px("post", f"{BASE}/targets/{name}/test")
    c.log("started", f"message de test envoyé à la cible {target['type']}")
    return {"sent": True, "target": name}


# ---------------------------------------------------------------- règles
async def _check_targets(c: Ctx, wanted: list[str] | None):
    if wanted:
        known = {t["name"] for t in await _targets(c)}
        missing = [t for t in wanted if t not in known]
        if missing:
            c.refuse(f"Cible(s) inconnue(s) : {', '.join(missing)}", status.HTTP_422_UNPROCESSABLE_ENTITY)


def _matcher_same(after: dict, params: dict) -> bool:
    keymap = {"invert-match": "invert", "match-field": "match_field", "match-severity": "match_severity", "match-calendar": "match_calendar", "target": "targets"}
    for k, v in params.items():
        got = after.get(keymap.get(k, k))
        if isinstance(v, list):
            if set(got or []) != set(v):
                return False
        elif k in ("disable", "invert-match"):
            if bool(got) != bool(v):
                return False
        elif k == "comment":
            if (got or "").rstrip("\n") != v.rstrip("\n"):
                return False
        elif got != v:
            return False
    return True


@router.post("/matchers", status_code=status.HTTP_201_CREATED)
async def create_matcher(body: MatcherCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "notif-matcher-create", body.name)
    try:
        params, _ = build_matcher(body, [], creating=True)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.dry_run:
        return {"dry_run": True, "params": {"name": body.name, **params}}
    _need_confirm(c, body)
    if any(m["name"] == body.name for m in await _matchers(c)):
        c.refuse("Une règle porte déjà ce nom", status.HTTP_409_CONFLICT)
    await _check_targets(c, body.target)
    await c.px("post", f"{BASE}/matchers", name=body.name, **params)
    after = next((m for m in await _matchers(c) if m["name"] == body.name), None)
    if after is None or not _matcher_same(after, params):
        c.refuse("Proxmox n'a pas appliqué la création", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, []))
    return after


@router.put("/matchers/{name}")
async def update_matcher(body: MatcherUpdate, conn_id: int, name: str = Path(pattern=NAME.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                         user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "notif-matcher-update", name)
    cur = next((m for m in await _matchers(c) if m["name"] == name), None)
    if cur is None:
        c.refuse("Règle introuvable", status.HTTP_404_NOT_FOUND)
    try:
        params, delete = build_matcher(body, list(body.clear), creating=False)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    raw = await c.px("get", f"{BASE}/matchers/{name}")
    pve_digest = raw.get("digest") if isinstance(raw, dict) and isinstance(raw.get("digest"), str) else None
    kdigest = digest_of({k: v for k, v in cur.items()})
    if body.digest is not None and body.digest != kdigest:
        c.refuse("La règle a changé depuis ta lecture (digest périmé) : recharge avant de modifier", status.HTTP_409_CONFLICT)
    if body.dry_run:
        return {"dry_run": True, "params": params, "remove": delete}
    _need_confirm(c, body)
    await _check_targets(c, body.target)
    send = dict(params)
    if delete:
        send["delete"] = delete
    if pve_digest:
        send["digest"] = pve_digest
    await c.px("put", f"{BASE}/matchers/{name}", **send)
    after = next((m for m in await _matchers(c) if m["name"] == name), None)
    if after is None or not _matcher_same(after, params):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, delete))
    return after


@router.delete("/matchers/{name}")
async def delete_matcher(conn_id: int, name: str = Path(pattern=NAME.pattern), confirm: bool = Query(default=False), type_name: str | None = Query(default=None, max_length=64),
                         dry_run: bool = Query(default=False), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "notif-matcher-delete", name)
    cur = next((m for m in await _matchers(c) if m["name"] == name), None)
    if cur is None:
        c.refuse("Règle introuvable", status.HTTP_404_NOT_FOUND)
    if cur["builtin"]:
        c.refuse("Règle intégrée de Proxmox : elle ne peut pas être supprimée (désactive-la si besoin)", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if dry_run:
        return {"dry_run": True, "remove": [name], "retype": name}
    if not confirm:
        c.refuse("Suppression : renvoie la requête avec confirm=true et le nom retapé (type_name)", status.HTTP_400_BAD_REQUEST)
    if type_name != name:
        c.refuse("Le nom retapé ne correspond pas : suppression refusée", status.HTTP_400_BAD_REQUEST)
    await c.px("delete", f"{BASE}/matchers/{name}")
    if any(m["name"] == name for m in await _matchers(c)):
        c.refuse("Proxmox n'a pas supprimé la règle", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "règle supprimée")
    return {"deleted": name}
