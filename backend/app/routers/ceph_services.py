"""Ceph, ÉCRITURE : moniteurs, gestionnaires, MDS, OSD (lot C3). Créer, démarrer, arrêter, mettre dedans ou dehors. Pas de destruction (C4).

Même discipline que les pools (`ceph_write.py`) : validation stricte, barrière de santé, confirmation décidée par le SERVEUR, une seule
écriture Ceph à la fois, audit de chaque cas. RIEN de tout cela n'a été validé sur un vrai Ceph.
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from ..cephservices import SERVICE_NAME, ConfirmBody, MdsCreate, OsdCreate, mds_stop, mgr_stop, mon_stop, osd_loss
from ..cephspec import shape_fs, shape_mgrs, shape_mons, shape_osds, shape_pools
from ..cephwrite import write_slot
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from .actions import NODE
from .auth import current_user
from .ceph import _NotInstalled, _get
from .ceph_write import NOT_INSTALLED_409, _health, _recorder
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/ceph/nodes/{node}", tags=["ceph-write"], dependencies=[Depends(current_user)])
CONFIRM = "Confirmation requise (renvoie la requête avec confirm=true) : "
NodeP = Path(pattern=NODE)
KindP = Path(pattern="^(osd|mon|mgr|mds)$")
NameP = Path(pattern=f"^{SERVICE_NAME.pattern}$")


class _Op:
    """Une opération d'écriture : audit (succès, refus, erreur), lectures sans fuite, envoi à Proxmox."""

    def __init__(self, db, factory, conn_id, user, action, target, base, node):
        self.db, self.factory, self.conn_id, self.node, self.base = db, factory, conn_id, node, base
        self.log, self.refuse = _recorder(db, user, conn_id, action, target)

    async def read(self, fn):
        try:
            return await fn()
        except _NotInstalled:
            self.refuse(NOT_INSTALLED_409, 409)
        except HTTPException as e:
            self.log("error", f"{self.base} · {e.detail}")
            raise

    async def get(self, path, **params):
        return await self.read(lambda: _get(self.db, self.factory, self.conn_id, path, **params))

    async def node_online(self):
        """Le nœud doit exister ET être en ligne : on n'écrit jamais sur un nom qu'on n'a pas vu."""
        data = await self.read(lambda: _px(self.db, self.factory, self.conn_id, "get", "/nodes"))
        if not any(isinstance(n, dict) and n.get("node") == self.node and n.get("status") == "online" for n in (data if isinstance(data, list) else [])):
            self.refuse("Nœud introuvable ou hors ligne", 404)

    async def health(self) -> str:
        return await self.read(lambda: _health(self.db, self.factory, self.conn_id))

    async def need_ok(self):
        h = await self.health()
        if h != "HEALTH_OK":
            self.refuse(f"Cette opération est refusée tant que la santé n'est pas HEALTH_OK (actuellement {h})", 409)

    async def need_not_error(self):
        h = await self.health()
        if h not in ("HEALTH_OK", "HEALTH_WARN"):
            self.refuse(f"Ceph n'est pas dans un état sûr ({h}) : l'opération est refusée", 409)

    def confirm(self, given: bool, reasons: list[str]):
        if not given:
            self.refuse(CONFIRM + " ; ".join(reasons), 400)

    async def fire(self, path, **params):
        try:
            upid = await _px(self.db, self.factory, self.conn_id, "post", path, **params)
        except HTTPException as e:
            self.log("error", f"{self.base} · {e.detail}")
            raise
        upid = upid if isinstance(upid, str) else None
        self.log("started", self.base, upid=upid)
        return {"upid": upid, "node": self.node}


# ============================================================ créer : moniteur, gestionnaire, MDS

@router.post("/monitors", status_code=202)
async def create_monitor(conn_id: int, node: str = NodeP, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                         user: AdminUser = Depends(current_user), body: ConfirmBody | None = Body(default=None)):
    """Crée le moniteur de ce nœud. Refusé si la santé est ERR ou inconnue, ou s'il y en a déjà un ici. Un nombre PAIR de moniteurs
    n'améliore pas la tolérance aux pannes : confirmation exigée dans ce cas."""
    op = _Op(db, factory, conn_id, user, "ceph-mon-create", f"mon/{node}", "création du moniteur", node)
    with write_slot(conn_id):
        await op.node_online()
        await op.need_not_error()
        mons = shape_mons(await op.get(f"/nodes/{node}/ceph/mon"))
        if any(m["host"] == node or m["name"] == node for m in mons):
            op.refuse("Ce nœud a déjà un moniteur", 409)
        if (len(mons) + 1) % 2 == 0:
            op.confirm(bool(body and body.confirm), [f"cela portera le nombre de moniteurs à {len(mons) + 1} (PAIR) : cela n'améliore pas "
                                                    "la tolérance aux pannes, un nombre impair est préférable"])
        return await op.fire(f"/nodes/{node}/ceph/mon")


@router.post("/managers", status_code=202)
async def create_manager(conn_id: int, node: str = NodeP, db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                         user: AdminUser = Depends(current_user)):
    """Crée le gestionnaire de ce nœud. Refusé si la santé est ERR ou inconnue, ou s'il y en a déjà un ici."""
    op = _Op(db, factory, conn_id, user, "ceph-mgr-create", f"mgr/{node}", "création du gestionnaire", node)
    with write_slot(conn_id):
        await op.node_online()
        await op.need_not_error()
        mgrs = shape_mgrs(await op.get(f"/nodes/{node}/ceph/mgr"))
        if any(m["host"] == node or m["name"] == node for m in mgrs):
            op.refuse("Ce nœud a déjà un gestionnaire", 409)
        return await op.fire(f"/nodes/{node}/ceph/mgr")


@router.post("/mds", status_code=202)
async def create_mds(conn_id: int, body: MdsCreate | None = Body(default=None), node: str = NodeP, db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Crée le serveur de métadonnées (MDS) de ce nœud. Refusé si la santé est ERR ou inconnue, ou s'il y en a déjà un ici."""
    body = body or MdsCreate()
    op = _Op(db, factory, conn_id, user, "ceph-mds-create", f"mds/{node}", "création du MDS" + (" de secours chaud" if body.hotstandby else ""), node)
    with write_slot(conn_id):
        await op.node_online()
        await op.need_not_error()
        servers = shape_fs([], await op.get(f"/nodes/{node}/ceph/mds"))["mds"]
        if any(m["host"] == node or m["name"] == node for m in servers):
            op.refuse("Ce nœud a déjà un MDS", 409)
        return await op.fire(f"/nodes/{node}/ceph/mds", hotstandby=1 if body.hotstandby else 0)


# ============================================================ créer : OSD (EFFACE le disque)

@router.post("/osds", status_code=202)
async def create_osd(body: OsdCreate, conn_id: int, node: str = NodeP, db: Session = Depends(get_db),
                     factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Crée un OSD sur un disque. **Cela EFFACE le disque.** Le disque doit figurer dans la liste des disques INUTILISÉS du nœud
    (lue chez Proxmox) ; confirmation du serveur, puis le nom du disque retapé (`confirm_dev`). Refusé si la santé est ERR ou inconnue."""
    base = f"création d'un OSD sur {body.dev}" + (" chiffré" if body.encrypted else "") + (f" classe={body.device_class}" if body.device_class else "")
    op = _Op(db, factory, conn_id, user, "ceph-osd-create", f"osd/{node}:{body.dev}", base, node)
    with write_slot(conn_id):
        await op.node_online()
        await op.need_not_error()
        await op.get(f"/nodes/{node}/ceph/osd")                      # Ceph installé ? (sinon 409, pas une écriture)
        disks = await op.read(lambda: _px(db, factory, conn_id, "get", f"/nodes/{node}/disks/list", type="unused"))
        disk = next((d for d in (disks if isinstance(disks, list) else []) if isinstance(d, dict) and d.get("devpath") == body.dev), None)
        if disk is None or disk.get("used") not in (None, ""):
            op.refuse("Ce disque n'existe pas sur ce nœud ou n'est pas libre : seul un disque inutilisé peut devenir un OSD", 409)
        size, model = disk.get("size"), disk.get("model")
        what = body.dev + (f" ({str(model)[:40]}" + (f", {size // 2**30} Gio" if isinstance(size, int) else "") + ")" if isinstance(model, str) else "")
        op.confirm(body.confirm, [f"cela EFFACE ENTIÈREMENT le disque {what} : toutes ses données seront perdues ; retape ensuite son nom exact"])
        if body.confirm_dev != body.dev:
            op.refuse("Le nom du disque retapé ne correspond pas : retape exactement " + body.dev, 400)
        params = {"dev": body.dev, "encrypted": 1 if body.encrypted else 0}
        if body.device_class:
            params["crush-device-class"] = body.device_class
        return await op.fire(f"/nodes/{node}/ceph/osd", **params)


# ============================================================ OSD : dedans / dehors

async def _osd_of(op: _Op, node: str, osd_id: int):
    osds = shape_osds(await op.get(f"/nodes/{node}/ceph/osd"))["osds"]
    target = next((o for o in osds if o["id"] == osd_id), None)
    if target is None:
        op.refuse("OSD introuvable", 404)
    if target["host"] != node:
        op.refuse(f"Cet OSD est sur « {target['host']} », pas sur « {node} »" if target["host"] else "L'hôte de cet OSD est illisible", 409)
    return target, osds, shape_pools(await op.get(f"/nodes/{node}/ceph/pool"))


@router.post("/osds/{osd_id}/out", status_code=202)
async def osd_out(conn_id: int, osd_id: int = Path(ge=0, le=100000), node: str = NodeP, db: Session = Depends(get_db),
                  factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user), body: ConfirmBody | None = Body(default=None)):
    """Met un OSD dehors : Ceph déplace ses données. Refusé tant que la santé n'est pas HEALTH_OK, si cela rend des données
    indisponibles (moins d'hôtes que `min_size`), puis exige `confirm=true`."""
    op = _Op(db, factory, conn_id, user, "ceph-osd-out", f"osd/{osd_id}", f"osd.{osd_id} dehors", node)
    with write_slot(conn_id):
        await op.node_online()
        target, osds, pools = await _osd_of(op, node, osd_id)
        if target["in"] is False:
            op.refuse("Cet OSD est déjà dehors", 409)
        await op.need_ok()
        refus, risks = osd_loss(target, osds, pools, "out")
        if refus:
            op.refuse(refus, 409)
        op.confirm(bool(body and body.confirm), risks)
        return await op.fire(f"/nodes/{node}/ceph/osd/{osd_id}/out")


@router.post("/osds/{osd_id}/in", status_code=202)
async def osd_in(conn_id: int, osd_id: int = Path(ge=0, le=100000), node: str = NodeP, db: Session = Depends(get_db),
                 factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Remet un OSD dedans (Ceph recommence à y placer des données). Pas de confirmation ; refusé si la santé est ERR ou inconnue."""
    op = _Op(db, factory, conn_id, user, "ceph-osd-in", f"osd/{osd_id}", f"osd.{osd_id} dedans", node)
    with write_slot(conn_id):
        await op.node_online()
        target, _osds, _pools = await _osd_of(op, node, osd_id)
        if target["in"] is True:
            op.refuse("Cet OSD est déjà dedans", 409)
        await op.need_not_error()
        return await op.fire(f"/nodes/{node}/ceph/osd/{osd_id}/in")


# ============================================================ démarrer / arrêter un service

async def _find(op: _Op, node: str, kind: str, name: str):
    """Le service doit exister et tourner SUR CE NŒUD. Renvoie `(cible, tous les services du type, pools si OSD)`."""
    if kind == "osd":
        if not name.isdigit():
            op.refuse("Nom d'OSD invalide", 404)
        return await _osd_of(op, node, int(name))
    raw = await op.get(f"/nodes/{node}/ceph/{kind}")
    items = shape_mons(raw) if kind == "mon" else shape_mgrs(raw) if kind == "mgr" else shape_fs([], raw)["mds"]
    target = next((m for m in items if m["name"] == name), None)
    if target is None:
        op.refuse("Service introuvable", 404)
    if target["host"] != node:
        op.refuse(f"Ce service est sur « {target['host']} », pas sur « {node} »" if target["host"] else "L'hôte de ce service est illisible", 409)
    return target, items, None


@router.post("/services/{kind}/{name}/start", status_code=202)
async def start_service(conn_id: int, kind: str = KindP, name: str = NameP, node: str = NodeP, db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Démarre un service (osd, mon, mgr, mds) de ce nœud. Pas de barrière de santé : démarrer RÉPARE (autorisé même en HEALTH_ERR)."""
    op = _Op(db, factory, conn_id, user, "ceph-service-start", f"{kind}.{name}", f"démarrage de {kind}.{name}", node)
    with write_slot(conn_id):
        await op.node_online()
        target, _items, _ctx = await _find(op, node, kind, name)
        if kind == "osd" and target["up"] is True:
            op.refuse("Cet OSD est déjà démarré", 409)
        return await op.fire(f"/nodes/{node}/ceph/start", service=f"{kind}.{name}")


@router.post("/services/{kind}/{name}/stop", status_code=202)
async def stop_service(conn_id: int, kind: str = KindP, name: str = NameP, node: str = NodeP, db: Session = Depends(get_db),
                       factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user),
                       body: ConfirmBody | None = Body(default=None)):
    """Arrête un service (osd, mon, mgr, mds). Toujours risqué : refusé tant que la santé n'est pas HEALTH_OK, refusé s'il fait perdre
    le quorum (moniteur) ou rend des données indisponibles (OSD), puis exige `confirm=true`."""
    op = _Op(db, factory, conn_id, user, "ceph-service-stop", f"{kind}.{name}", f"arrêt de {kind}.{name}", node)
    with write_slot(conn_id):
        await op.node_online()
        target, items, ctx = await _find(op, node, kind, name)
        if kind == "osd" and target["up"] is False:
            op.refuse("Cet OSD est déjà arrêté", 409)
        await op.need_ok()
        refus, risks = None, []
        if kind == "osd":
            refus, risks = osd_loss(target, items, ctx, "stop")
        elif kind == "mon":
            refus, risks = mon_stop(target, items)
        elif kind == "mgr":
            risks = mgr_stop(target, items)
        else:
            risks = mds_stop(target, items)
        if refus:
            op.refuse(refus, 409)
        op.confirm(bool(body and body.confirm), risks)
        return await op.fire(f"/nodes/{node}/ceph/stop", service=f"{kind}.{name}")
