"""Volumes d'un stockage : protéger une sauvegarde, supprimer un fichier, élaguer les sauvegardes."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from .. import audit
from ..backupspec import BACKUP_FILE, _protected
from ..db import get_db
from ..deps import get_client_factory
from ..models import AdminUser
from ..vmspec import STORAGE
from ..volumespec import FILE_NAME, NODE_NAME, STORAGE_ID, CopyBody, CopyKind, FileKind, Protect, PrunePreview, PruneRun, copy_name_ok, prune_params, shape_prune
from .actions import NODE
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}/nodes/{node}/storage/{storage}", tags=["volumes"], dependencies=[Depends(current_user)])


class Ctx:
    def __init__(self, db, factory, user, conn_id, action, target):
        self.db, self.factory, self.user, self.conn_id, self.action, self.target = db, factory, user, conn_id, action, target

    def log(self, st, detail=None, upid=None):
        audit.record(self.db, username=self.user.username, connection_id=self.conn_id, action=self.action,
                     target=self.target, status=st, detail=detail, upid=upid)

    def refuse(self, msg, code):
        self.log("error", msg)
        raise HTTPException(code, msg)

    async def px(self, method, path, /, **kw):
        try:
            return await _px(self.db, self.factory, self.conn_id, method, path, **kw)
        except HTTPException as e:
            self.log("error", str(e.detail))
            raise

    async def find(self, node, storage, content, volid):
        """Volume relu chez Proxmox au moment de l'action (jamais une valeur du navigateur)."""
        listing = await self.px("get", f"/nodes/{node}/storage/{storage}/content", content=content)
        found = next((v for v in listing if isinstance(v, dict) and v.get("volid") == volid), None) if isinstance(listing, list) else None
        if found is None:
            self.refuse("Volume introuvable sur ce stockage", 404)
        if found.get("content") not in (None, content):
            self.refuse("Ce volume n'est pas du type attendu : refusé", 409)
        return found


def _upid(v):
    return v if isinstance(v, str) else None


# ---------------------------------------------------------------- protéger une sauvegarde
@router.put("/backups/{volume}/protect")
async def protect_backup(body: Protect, conn_id: int, node: str = Path(pattern=NODE), storage: str = Path(pattern=STORAGE.pattern),
                         volume: str = Path(pattern=BACKUP_FILE.pattern), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Protège une sauvegarde (elle ne peut plus être supprimée ni élaguée) ou retire sa protection. Réversible."""
    volid = f"{storage}:backup/{volume}"
    c = Ctx(db, factory, user, conn_id, "backup-protect" if body.protected else "backup-unprotect", f"{volid}@{node}")
    await c.find(node, storage, "backup", volid)
    await c.px("put", f"/nodes/{node}/storage/{storage}/content/{quote(volid, safe='')}", protected=1 if body.protected else 0)
    c.log("started", "protégée" if body.protected else "protection retirée")
    return {"volid": volid, "protected": body.protected}


# ---------------------------------------------------------------- supprimer un fichier
@router.delete("/files/{kind}/{name}")
async def delete_file(conn_id: int, kind: FileKind = Path(), name: str = Path(pattern=FILE_NAME.pattern), node: str = Path(pattern=NODE),
                      storage: str = Path(pattern=STORAGE.pattern), confirm: bool = Query(default=False),
                      typed: str = Query(default="", max_length=210), db: Session = Depends(get_db),
                      factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Supprime DÉFINITIVEMENT une ISO, un modèle, un snippet ou une image à importer. Exige confirm=true et le nom exact du fichier (?typed=).
    Kaji ne vérifie pas si une machine utilise encore ce fichier (ISO montée, par exemple)."""
    volid = f"{storage}:{kind}/{name}"
    c = Ctx(db, factory, user, conn_id, "file-delete", f"{volid}@{node}")
    if not confirm:
        c.refuse("Suppression définitive : renvoie la requête avec ?confirm=true et le nom du fichier (?typed=)", 400)
    if typed != name:
        c.refuse("Le nom du fichier ne correspond pas : suppression refusée", 400)
    await c.find(node, storage, kind, volid)
    upid = await c.px("delete", f"/nodes/{node}/storage/{storage}/content/{quote(volid, safe='')}")
    c.log("started", f"{kind} SUPPRIMÉ : {volid}", upid=_upid(upid))
    return {"upid": _upid(upid), "deleted": volid}


# ---------------------------------------------------------------- copier un fichier
@router.post("/copy/{kind}/{name}")
async def copy_file(body: CopyBody, conn_id: int, kind: CopyKind = Path(), name: str = Path(max_length=210), node: str = Path(pattern=NODE),
                    storage: str = Path(pattern=STORAGE.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory),
                    user: AdminUser = Depends(current_user)):
    """Copie un fichier vers un autre stockage (et éventuellement un autre nœud). La source n'est JAMAIS supprimée. API Proxmox expérimentale :
    source, destination et absence d'un fichier de même nom sont relues chez Proxmox avant d'appeler (409 si le fichier existe déjà)."""
    target_name = body.target_name or name
    dest_node = body.target_node or node
    volid = f"{storage}:{kind}/{name}"
    c = Ctx(db, factory, user, conn_id, "volume-copy", f"{volid}@{node}")
    ctype = kind                                                          # le type de contenu Proxmox porte le même nom que le type de fichier
    if not copy_name_ok(kind, name) or not copy_name_ok(kind, target_name):
        c.refuse("Nom de fichier invalide pour ce type", 422)
    if not STORAGE_ID.fullmatch(body.target_storage) or not NODE_NAME.fullmatch(dest_node):
        c.refuse("Stockage ou nœud de destination invalide", 422)
    if dest_node == node and body.target_storage == storage and target_name == name:
        c.refuse("La destination est la source elle-même", 422)
    target = f"{body.target_storage}:{kind}/{target_name}"
    await c.find(node, storage, ctype, volid)
    nodes = await c.px("get", "/nodes")
    if not isinstance(nodes, list) or not any(isinstance(n, dict) and n.get("node") == dest_node for n in nodes):
        c.refuse("Nœud de destination inconnu du cluster", 422)
    accepting = await c.px("get", f"/nodes/{dest_node}/storage", content=ctype)
    if not isinstance(accepting, list) or not any(isinstance(s, dict) and s.get("storage") == body.target_storage and s.get("active", 1) for s in accepting):
        c.refuse("Ce stockage n'accepte pas ce type de fichier ou n'est pas actif sur le nœud de destination", 422)
    present = await c.px("get", f"/nodes/{dest_node}/storage/{body.target_storage}/content", content=ctype)
    if not isinstance(present, list):
        c.refuse("Contenu de la destination illisible : copie refusée", 502)
    if any(isinstance(v, dict) and v.get("volid") == target for v in present):
        c.refuse("Un fichier de ce nom existe déjà sur la destination : copie refusée, rien n'est écrasé", 409)
    if body.dry_run:
        return {"dry_run": True, "source": volid, "target": target, "target_node": dest_node, "node": node}
    params = {"target": target, **({"target_node": dest_node} if dest_node != node else {})}
    upid = await c.px("post", f"/nodes/{node}/storage/{storage}/content/{quote(volid, safe='')}", **params)
    c.log("started", f"{kind} COPIÉ : {volid} -> {dest_node}:{target}", upid=_upid(upid))
    return {"upid": _upid(upid), "source": volid, "target": target, "target_node": dest_node, "node": node}


# ---------------------------------------------------------------- élaguer les sauvegardes
@router.post("/prune/preview")
async def prune_preview(body: PrunePreview, conn_id: int, node: str = Path(pattern=NODE), storage: str = Path(pattern=STORAGE.pattern),
                        db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    """Ce que l'élagage supprimerait (`mark`: remove) ou garderait, calculé par Proxmox. **Ne supprime rien.**"""
    try:
        params = prune_params(body)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return shape_prune(await _px(db, factory, conn_id, "get", f"/nodes/{node}/storage/{storage}/prunebackups", **params))


@router.post("/prune")
async def prune_run(body: PruneRun, conn_id: int, node: str = Path(pattern=NODE), storage: str = Path(pattern=STORAGE.pattern),
                    db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Élague les sauvegardes. Exige confirm=true, le nom du stockage retapé et le nombre exact de sauvegardes à supprimer vu dans l'aperçu :
    l'aperçu est recalculé au moment de l'appel, et l'exécution est refusée (409) si le nombre a changé. Les sauvegardes protégées ne sont pas touchées."""
    c = Ctx(db, factory, user, conn_id, "storage-prune", f"{storage}@{node}")
    try:
        params = prune_params(body)
    except ValueError as e:
        c.refuse(str(e), 422)
    if not body.confirm:
        c.refuse("Élagage définitif : renvoie la requête avec confirm=true", 400)
    if body.type_name != storage:
        c.refuse("Le nom du stockage ne correspond pas : élagage refusé", 400)
    now = shape_prune(await c.px("get", f"/nodes/{node}/storage/{storage}/prunebackups", **params))
    if now["remove"] == 0:
        c.refuse("Rien à supprimer avec ces règles", 422)
    if now["remove"] != body.expected_remove:
        c.refuse(f"Le stockage a changé : {now['remove']} sauvegarde(s) seraient supprimées au lieu de {body.expected_remove}. Refais l'aperçu", 409)
    upid = await c.px("delete", f"/nodes/{node}/storage/{storage}/prunebackups", **params)
    c.log("started", f"{now['remove']} sauvegarde(s) supprimées" + (f", règles : {params['prune-backups']}" if "prune-backups" in params else ", règles du stockage")
          + (f", VM {params['vmid']}" if "vmid" in params else ""), upid=_upid(upid))
    return {"upid": _upid(upid), "node": node, "removed": now["remove"]}
