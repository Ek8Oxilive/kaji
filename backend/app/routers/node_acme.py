"""ACME (certificats automatiques) : comptes, domaines d'un nœud, commande et renouvellement (droit `Sys.Modify`). Garde-fous : `acmespec`.

Les opérations contactent une autorité extérieure (Let's Encrypt). Les plugins DNS (qui portent des secrets d'API) ne sont pas gérés ici.
"""
import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .. import acmespec as A, audit
from ..certspec import CUSTOM_FILE
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _get_or_404, _params, _px, http_error

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["acme"], dependencies=[Depends(current_user)])


# ---------------------------------------------------------------- lecture
async def _section(coro, shape):
    try:
        return {"state": "ok", "data": shape(await coro)}
    except httpx.HTTPStatusError as e:
        return {"state": "forbidden" if e.response.status_code == 403 else "error", "data": None}
    except httpx.HTTPError:
        return {"state": "error", "data": None}


@router.get("/nodes/{node}/acme")
async def read_acme(conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Comptes, annuaires, conditions d'utilisation, plugins et configuration ACME du nœud. Rubriques indépendantes. Lecture seule."""
    client = factory(**_params(_get_or_404(db, conn_id)))
    try:
        names = await _section(client.get("/cluster/acme/account"), lambda r: r)
        details: dict = {}
        if names["state"] == "ok" and isinstance(names["data"], list):
            for r in names["data"][:10]:
                n = r.get("name") if isinstance(r, dict) else None
                if isinstance(n, str) and A.re.fullmatch(A.ACCOUNT[1:-1], n):
                    try:
                        details[n] = await client.get(f"/cluster/acme/account/{n}")
                    except httpx.HTTPError:
                        details[n] = {}
        accounts = {"state": names["state"], "data": A.shape_accounts(names["data"], details) if names["state"] == "ok" else None}
        rest = await asyncio.gather(
            _section(client.get("/cluster/acme/directories"), A.shape_directories), _section(client.get("/cluster/acme/tos"), lambda r: r if isinstance(r, str) else None),
            _section(client.get("/cluster/acme/plugins"), A.shape_plugins), _section(client.get(f"/nodes/{node}/config"), A.shape_node_acme))
    finally:
        await client.aclose()
    out = {"accounts": accounts, **dict(zip(("directories", "tos", "plugins", "config"), rest))}
    if all(v["state"] == "error" for v in out.values()):
        raise http_error(httpx.ConnectError("injoignable"))
    return out


# ---------------------------------------------------------------- écriture
def _recorder(db, user, conn_id, action, target):
    def fail(code: int, msg: str):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="error", detail=msg)
        raise HTTPException(code, msg)

    def ok(upid=None, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action=action, target=target, status="started" if upid else "ok",
                     upid=upid if isinstance(upid, str) else None, detail=detail)
    return fail, ok


async def _read(db, factory, conn_id, fail, path, **params):
    try:
        return await _px(db, factory, conn_id, "get", path, **params)
    except HTTPException:
        fail(502, "État ACME illisible : action refusée par précaution")


async def _send(db, factory, conn_id, fail, method, path, **params):
    try:
        return await _px(db, factory, conn_id, method, path, **params)
    except HTTPException as e:
        fail(e.status_code, str(e.detail))


@router.post("/acme/accounts", status_code=status.HTTP_202_ACCEPTED)
async def create_account(body: A.AccountCreate, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                         user: AdminUser = Depends(current_user)):
    """Enregistre un compte auprès de l'autorité ACME : **son adresse de contact lui est transmise** et tu acceptes ses conditions (`accept_tos`)."""
    fail, ok = _recorder(db, user, conn_id, "acme-account-create", f"acme/{body.name}")
    directories = A.shape_directories(await _read(db, factory, conn_id, fail, "/cluster/acme/directories"))
    tos = await _read(db, factory, conn_id, fail, "/cluster/acme/tos")
    existing = {a["name"] for a in A.shape_accounts(await _read(db, factory, conn_id, fail, "/cluster/acme/account"), {})}
    refused = A.verdict_account(body, directories, tos if isinstance(tos, str) else None, existing)
    if refused:
        fail(*refused)
    upid = await _send(db, factory, conn_id, fail, "post", "/cluster/acme/account", name=body.name, contact=body.contact, directory=body.directory, tos_url=tos)
    ok(upid, f"annuaire {body.directory}")
    return {"upid": upid if isinstance(upid, str) else None}


@router.post("/acme/accounts/{name}/delete", status_code=status.HTTP_202_ACCEPTED)
async def delete_account(body: A.AccountDelete, conn_id: int, name: str = Path(pattern=A.ACCOUNT), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Désactive un compte auprès de l'autorité (irréversible). Refusé tant qu'un nœud l'utilise."""
    fail, ok = _recorder(db, user, conn_id, "acme-account-delete", f"acme/{name}")
    existing = {a["name"] for a in A.shape_accounts(await _read(db, factory, conn_id, fail, "/cluster/acme/account"), {})}
    used_by: list[str] | None = []
    try:
        for n in await _px(db, factory, conn_id, "get", "/nodes"):
            node = n.get("node") if isinstance(n, dict) else None
            if isinstance(node, str):
                if A.shape_node_acme(await _px(db, factory, conn_id, "get", f"/nodes/{node}/config"))["account"] == name:
                    used_by.append(node)
    except HTTPException:
        used_by = None
    refused = A.verdict_delete(body, name, existing, used_by)
    if refused:
        fail(*refused)
    upid = await _send(db, factory, conn_id, fail, "delete", f"/cluster/acme/account/{name}")
    ok(upid)
    return {"upid": upid if isinstance(upid, str) else None}


@router.put("/nodes/{node}/acme/config")
async def set_config(body: A.AcmeConfig, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Compte et domaines ACME du nœud (`acme`, `acmedomain0..4` de sa configuration). Les autres réglages du nœud ne sont jamais touchés."""
    fail, ok = _recorder(db, user, conn_id, "acme-config", f"node/{node}")
    accounts = {a["name"] for a in A.shape_accounts(await _read(db, factory, conn_id, fail, "/cluster/acme/account"), {})}
    plugins = {p["id"]: p["type"] for p in A.shape_plugins(await _read(db, factory, conn_id, fail, "/cluster/acme/plugins"))}
    current = A.shape_node_acme(await _read(db, factory, conn_id, fail, f"/nodes/{node}/config"))
    refused = A.verdict_config(body, accounts, plugins, current)
    if refused:
        fail(*refused)
    params: dict = {"acme": f"account={body.account}"}
    for i, d in enumerate(body.domains):
        params[f"acmedomain{i}"] = f"domain={d.domain}" + (f",plugin={d.plugin}" if d.plugin else "")
    stale = [f"acmedomain{c['slot']}" for c in current["domains"] if c["slot"] >= len(body.domains)]
    if stale:
        params["delete"] = ",".join(stale)
    if current["digest"]:
        params["digest"] = current["digest"]
    await _send(db, factory, conn_id, fail, "put", f"/nodes/{node}/config", **params)
    ok(detail=f"compte {body.account}, {len(body.domains)} domaine(s)")
    return {"ok": True}


async def _order(kind: str, body: A.Order, conn_id, node, db, factory, user):
    fail, ok = _recorder(db, user, conn_id, f"acme-{kind}", f"node/{node}")
    current = A.shape_node_acme(await _read(db, factory, conn_id, fail, f"/nodes/{node}/config"))
    directory = None
    if current["account"]:
        try:
            directory = (await _px(db, factory, conn_id, "get", f"/cluster/acme/account/{current['account']}")).get("directory")
        except (HTTPException, AttributeError):
            directory = None
    info = await _read(db, factory, conn_id, fail, f"/nodes/{node}/certificates/info")
    has_custom = any(isinstance(c, dict) and c.get("filename") == CUSTOM_FILE for c in (info if isinstance(info, list) else []))
    refused = A.verdict_order(body, current, directory if isinstance(directory, str) else None, has_custom and kind == "order", _get_or_404(db, conn_id).verify_ssl)
    if refused:
        fail(*refused)
    upid = await _send(db, factory, conn_id, fail, "post" if kind == "order" else "put", f"/nodes/{node}/certificates/acme/certificate",
                       force=int(body.replace_existing and kind == "order"))
    ok(upid)
    return {"upid": upid if isinstance(upid, str) else None, "node": node}


@router.post("/nodes/{node}/acme/order", status_code=status.HTTP_202_ACCEPTED)
async def order_certificate(body: A.Order, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                            factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Commande un certificat à l'autorité pour les domaines configurés (tâche Proxmox)."""
    return await _order("order", body, conn_id, node, db, factory, user)


@router.post("/nodes/{node}/acme/renew", status_code=status.HTTP_202_ACCEPTED)
async def renew_certificate(body: A.Order, conn_id: int, node: str = Path(pattern=NODE), db: Session = Depends(get_db),
                            factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Renouvelle le certificat ACME du nœud (Proxmox ne le fait que s'il expire bientôt)."""
    return await _order("renew", body, conn_id, node, db, factory, user)
