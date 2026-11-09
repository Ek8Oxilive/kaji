"""Options du datacenter (Datacenter → Options) et notes du datacenter. Validation et liste blanche : `app/datacenterspec.py`. Droit Proxmox : `Sys.Audit` (lire), `Sys.Modify` sur `/` (écrire)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import audit
from ..datacenterspec import DatacenterOptions, build, digest_of, shape_options
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/datacenter", tags=["datacenter"], dependencies=[Depends(current_user)])


def _read(raw) -> dict:
    shaped = shape_options(raw)
    return {**shaped, "digest": digest_of(shaped)}


@router.get("/options")
async def get_options(conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Options lues (champs gérés + champs en lecture seule) et `digest` (empreinte de Kaji, à renvoyer avec la modification)."""
    return _read(await _px(db, factory, conn_id, "get", "/cluster/options"))


def _same(k: str, got, want) -> bool:
    if k == "description":
        return (got or "").rstrip("\n") == want.rstrip("\n")
    if k == "mac_prefix":
        return isinstance(got, str) and got.upper() == want.upper()
    if k == "migration":
        typ, _, net = (want[len("type="):]).partition(",network=")
        return got == {"type": typ, "network": net or None}
    return got == want


@router.put("/options")
async def put_options(body: DatacenterOptions, conn_id: int, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    def log(st, detail=None):
        audit.record(db, username=user.username, connection_id=conn_id, action="datacenter-options", target="datacenter", status=st, detail=detail)

    def refuse(msg, code):
        log("error", msg)
        raise HTTPException(code, msg)

    async def px(method, path, /, **kw):
        try:
            return await _px(db, factory, conn_id, method, path, **kw)
        except HTTPException as e:
            log("error", str(e.detail))
            raise

    cur = _read(await px("get", "/cluster/options"))
    if body.digest is not None and body.digest != cur["digest"]:
        refuse("Les options ont changé depuis ta lecture (digest périmé) : recharge avant de modifier", status.HTTP_409_CONFLICT)
    try:
        params, delete, _ = build(body, cur)
    except ValueError as e:
        refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    insecure = "migration" in params and params["migration"].startswith("type=insecure") and cur["migration"]["type"] != "insecure"
    locks = {"insecure": insecure}
    if body.dry_run:
        return {"dry_run": True, "params": {k: ("défini" if k == "description" else v) for k, v in params.items()}, "remove": delete, "locks": locks}
    if insecure and not body.confirm:
        refuse("Migration non chiffrée : le trafic de migration (mémoire des machines) circulera en clair. Renvoie la requête avec confirm=true", status.HTTP_409_CONFLICT)
    send = dict(params)
    if delete:
        send["delete"] = ",".join(delete)
    await px("put", "/cluster/options", **send)
    fresh = _read(await px("get", "/cluster/options"))
    after = fresh
    for k, v in params.items():
        if not _same(k, after.get(k), v):
            refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    for k in delete:
        if after.get(k) not in (None, {"type": None, "network": None}):
            refuse("Proxmox n'a pas retiré le réglage", status.HTTP_502_BAD_GATEWAY)
    log("started", ", ".join(f"{k}={'défini' if k in ('description',) else v}" for k, v in sorted(params.items())) + (f" ; retiré : {','.join(delete)}" if delete else ""))
    return {"changed": sorted(params), "removed": delete, "locks": locks, **fresh}
