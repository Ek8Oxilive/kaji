"""Serveurs de métriques (Datacenter → Metric Server) : lister, ajouter, modifier, supprimer. Validation par type et secrets : `app/metricsspec.py`.

Droits Proxmox : `Sys.Audit` (lire), `Sys.Modify` sur `/` (écrire). Verrous : créer ou activer un serveur (les métriques de TOUT le cluster sortent vers lui) exige `confirm=true` ; supprimer exige
`confirm=true` ET l'identifiant retapé (`type_name`). Un serveur peut être créé désactivé. Les secrets (jeton, en-têtes) ne sont jamais relus, journalisés ni renvoyés.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..metricsspec import ID, OUTBOUND, SECRETS, WIRE, ServerCreate, ServerUpdate, build, digest_of, shape_list, shape_server
from ..models import AdminUser
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/metrics/servers", tags=["metrics-servers"], dependencies=[Depends(current_user)])
BASE = "/cluster/metrics/server"
WIRE_SECRETS = {WIRE[s] for s in SECRETS}
WIRE_OUTBOUND = {WIRE[f] for f in OUTBOUND}
FROM_WIRE = {v: k for k, v in WIRE.items()}
FLAGS = ("disable", "verify_certificate", "otel_verify_ssl")


class Ctx:
    def __init__(self, db: Session, factory: Factory, conn_id: int, user: AdminUser, action: str, target: str):
        self.db, self.factory, self.conn_id, self.user, self.action, self.target = db, factory, conn_id, user, action, target

    def log(self, st: str, detail: str | None = None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action, target=self.target, status=st, detail=detail)

    def refuse(self, msg: str, code: int):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method: str, path: str, /, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise


def _masked(params: dict) -> dict:
    return {k: ("défini" if k in WIRE_SECRETS else v) for k, v in params.items()}


def _txt(params: dict, delete: list[str]) -> str:
    return ", ".join(f"{k}={'défini' if k in WIRE_SECRETS else v}" for k, v in sorted(params.items())) + (f" ; retiré : {','.join(delete)}" if delete else "")


def _matches(after: dict | None, params: dict) -> bool:
    """Le serveur relu porte-t-il bien les valeurs écrites ? Les SECRETS ne sont jamais relus par Proxmox : ils ne sont pas vérifiés."""
    if after is None:
        return False
    for k, v in params.items():
        f = FROM_WIRE[k]
        if k in WIRE_SECRETS:
            continue
        if f"{f}_set" in after:                                                      # champ exposé seulement « défini »
            if not after[f"{f}_set"]:
                return False
        elif f in FLAGS:
            if bool(after.get(f)) != bool(v):
                return False
        elif after.get(f) != v:
            return False
    return True


async def _exists(c: Ctx, sid: str) -> dict:
    rows = shape_list(await c.px("get", BASE))
    row = next((r for r in rows if r["id"] == sid), None)
    if row is None:
        c.refuse("Serveur de métriques introuvable", status.HTTP_404_NOT_FOUND)
    return row


async def _detail(c: Ctx, sid: str, typ: str) -> tuple[dict, str | None]:
    """`(détail pour l'API, digest de Proxmox s'il existe)`. Le `digest` de l'API est celui de Kaji (Proxmox n'en renvoie pas à la lecture d'un serveur)."""
    raw = await c.px("get", f"{BASE}/{sid}")
    raw = raw if isinstance(raw, dict) else {}
    d = shape_server({**raw, "id": sid}, typ)
    if d is None:
        c.refuse("Configuration illisible", status.HTTP_502_BAD_GATEWAY)
    pve_digest = d["digest"]
    d["digest"] = digest_of(d)
    return d, pve_digest


@router.get("")
async def list_servers(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    return shape_list(await _px(db, factory, conn_id, "get", BASE))


@router.get("/{sid}")
async def get_server(conn_id: int, sid: str = Path(pattern=ID.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Configuration d'un serveur. Les secrets ne sont jamais renvoyés (`token_set`, `otel_headers_set`)."""
    row = next((r for r in shape_list(await _px(db, factory, conn_id, "get", BASE)) if r["id"] == sid), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Serveur de métriques introuvable")
    d = shape_server({**(await _px(db, factory, conn_id, "get", f"{BASE}/{sid}") or {}), "id": sid}, row["type"])
    if d is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Configuration illisible")
    d["digest"] = digest_of(d)
    return d


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_server(body: ServerCreate, response: Response, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "metrics-server-create", body.id)
    try:
        params, _ = build(body.type, body, [], creating=True)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    enabled = not body.disable
    if body.dry_run:
        response.status_code = status.HTTP_200_OK                                      # aperçu : rien n'est créé
        return {"dry_run": True, "params": {"id": body.id, "type": body.type, **_masked(params)}, "needs_confirm": enabled}
    if enabled and not body.confirm:
        c.refuse("Un serveur activé reçoit les métriques de tout le cluster : renvoie la requête avec confirm=true (ou crée-le désactivé avec disable=true)", status.HTTP_400_BAD_REQUEST)
    if any(r["id"] == body.id for r in shape_list(await c.px("get", BASE))):
        c.refuse("Un serveur porte déjà cet identifiant", status.HTTP_409_CONFLICT)
    await c.px("post", f"{BASE}/{body.id}", type=body.type, **params)                # l'identifiant est dans le chemin
    if not any(r["id"] == body.id for r in shape_list(await c.px("get", BASE))):
        c.refuse("Proxmox n'a pas appliqué la création", status.HTTP_502_BAD_GATEWAY)
    after, _ = await _detail(c, body.id, body.type)
    if not _matches(after, params):
        c.refuse("Proxmox n'a pas appliqué la création", status.HTTP_502_BAD_GATEWAY)
    c.log("started", f"{body.type} ; {_txt(params, [])}")
    return after


@router.put("/{sid}")
async def update_server(body: ServerUpdate, conn_id: int, sid: str = Path(pattern=ID.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                        user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "metrics-server-update", sid)
    row = await _exists(c, sid)
    cur, pve_digest = await _detail(c, sid, row["type"])
    try:
        params, delete = build(cur["type"], body, list(body.clear), creating=False)
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.digest is not None and body.digest != cur["digest"]:
        c.refuse("La configuration a changé depuis ta lecture (digest périmé) : recharge avant de modifier", status.HTTP_409_CONFLICT)
    will_be_enabled = (params["disable"] == 0) if "disable" in params else not cur["disable"]
    enabling = cur["disable"] and params.get("disable") == 0
    changed_out = {w for w in WIRE_OUTBOUND & set(params) if cur.get(FROM_WIRE[w]) != params[w]}                # une valeur identique n'est pas un changement
    outbound = bool(changed_out) or bool(WIRE_OUTBOUND & set(delete))
    needs_confirm = will_be_enabled and (enabling or outbound)
    if body.dry_run:
        return {"dry_run": True, "params": _masked(params), "remove": delete, "needs_confirm": needs_confirm}
    if needs_confirm and not body.confirm:
        c.refuse("Ce changement modifie où partent les métriques de tout le cluster (ou active le serveur) : renvoie la requête avec confirm=true", status.HTTP_400_BAD_REQUEST)
    send = dict(params)
    send.setdefault("server", cur["server"])                       # Proxmox exige `server` et `port` même pour une modification (constaté en réel)
    send.setdefault("port", cur["port"])
    if delete:
        send["delete"] = ",".join(delete)
    if pve_digest:
        send["digest"] = pve_digest
    await c.px("put", f"{BASE}/{sid}", **send)
    after, _ = await _detail(c, sid, cur["type"])
    if not _matches(after, params):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, delete))
    return after


@router.delete("/{sid}")
async def delete_server(conn_id: int, sid: str = Path(pattern=ID.pattern), confirm: bool = Query(default=False), type_name: str | None = Query(default=None, max_length=64),
                        dry_run: bool = Query(default=False), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Supprime la configuration du serveur (les métriques cessent de partir). Exige `confirm=true` ET l'identifiant retapé."""
    c = Ctx(db, factory, conn_id, user, "metrics-server-delete", sid)
    await _exists(c, sid)
    if dry_run:
        return {"dry_run": True, "remove": [sid], "retype": sid}
    if not confirm:
        c.refuse("Suppression : renvoie la requête avec confirm=true et l'identifiant retapé (type_name)", status.HTTP_400_BAD_REQUEST)
    if type_name != sid:
        c.refuse("L'identifiant retapé ne correspond pas : suppression refusée", status.HTTP_400_BAD_REQUEST)
    await c.px("delete", f"{BASE}/{sid}")
    if any(r["id"] == sid for r in shape_list(await c.px("get", BASE))):
        c.refuse("Proxmox n'a pas supprimé le serveur", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "serveur de métriques supprimé")
    return {"deleted": sid}
