"""Correspondances de ressources du datacenter (Datacenter → Resource Mappings) : PCI, USB, répertoires. Validation et formats : `app/mappingspec.py`.

Droits Proxmox : `Mapping.Audit` (lire) et `Mapping.Modify` (écrire) sur `/mapping/pci|usb|dir` ; le matériel d'un nœud demande `Sys.Audit`. Créer ou modifier une correspondance n'a aucun effet sur
une machine tant qu'elle n'est pas utilisée ; la **supprimer** casse les machines qui la citent : Kaji refuse tant qu'une VM la cite (`hostpciN` / `usbN` `mapping=…`, `virtiofsN` `dirid=…`),
et exige `confirm=true` ET l'identifiant retapé (`type_name`). Toute écriture accepte `dry_run`.
"""
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..deps import get_client_factory
from ..mappingspec import ID, NODE, HType, MappingCreate, MappingUpdate, MType, build_params, digest_of, parse_entry, shape_hardware, shape_list, shape_mapping
from ..models import AdminUser
from .auth import current_user
from .cluster import Factory, _px

router = APIRouter(prefix="/api/connections/{conn_id}", tags=["mappings"], dependencies=[Depends(current_user)])
BASE = "/cluster/mapping"
MAX_GUESTS = 64
USERS = {"pci": re.compile(r"^hostpci\d+$"), "usb": re.compile(r"^usb\d+$"), "dir": re.compile(r"^virtiofs\d+$")}


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


def _txt(params: dict, delete: list[str]) -> str:
    shown = ", ".join(f"{k}={len(v)} entrée(s)" if k == "map" else f"{k}={'défini' if k == 'description' else v}" for k, v in sorted(params.items()))
    return shown + (f" ; retiré : {','.join(delete)}" if delete else "")


def _same(after: dict | None, params: dict, mtype: str) -> bool:
    """La correspondance relue porte-t-elle ce qui vient d'être écrit ? (entrées comparées après lecture, dans n'importe quel ordre)"""
    if after is None:
        return False
    if "map" in params:
        key = lambda e: json.dumps(e, sort_keys=True)  # noqa: E731
        if sorted(map(key, (parse_entry(mtype, m) for m in params["map"]))) != sorted(map(key, after["map"])):
            return False
    if "description" in params and after["description"] != params["description"]:
        return False
    if "mdev" in params and after["mdev"] != bool(params["mdev"]):
        return False
    if "live-migration-capable" in params and after["live_migration_capable"] != bool(params["live-migration-capable"]):
        return False
    return True


async def _list(c: Ctx, mtype: str) -> list[dict]:
    return shape_list(await c.px("get", f"{BASE}/{mtype}"), mtype)


async def _detail(c: Ctx, mtype: str, mid: str) -> tuple[dict, dict]:
    """`(détail pour l'API, réponse brute de Proxmox)`. Le `digest` de l'API est celui de Kaji (celui de Proxmox, s'il existe, reste dans le brut)."""
    raw = await c.px("get", f"{BASE}/{mtype}/{mid}")
    raw = raw if isinstance(raw, dict) else {}
    d = shape_mapping({**raw, "id": mid}, mtype)
    if d is None:
        c.refuse("Configuration illisible", status.HTTP_502_BAD_GATEWAY)
    d["digest"] = digest_of(d)
    return d, raw


async def _users(c: Ctx, mtype: str, mid: str) -> list[str]:
    """Machines (VM) dont la configuration cite cette correspondance. Une configuration illisible est un refus : on ne devine pas."""
    rows = await c.px("get", "/cluster/resources", type="vm")
    guests = [(r["node"], r["vmid"]) for r in (rows if isinstance(rows, list) else []) if isinstance(r, dict) and r.get("type") == "qemu"
              and isinstance(r.get("node"), str) and NODE.fullmatch(r["node"]) and isinstance(r.get("vmid"), int) and not isinstance(r["vmid"], bool)]
    if len(guests) > MAX_GUESTS:
        c.refuse(f"Plus de {MAX_GUESTS} VM : impossible de vérifier qu'aucune n'utilise cette correspondance", status.HTTP_409_CONFLICT)
    key = "dirid" if mtype == "dir" else "mapping"
    pat = re.compile(rf"(?:^|,){key}={re.escape(mid)}(?:,|$)")
    used = []
    for node, vmid in sorted(guests):
        try:
            cfg = await _px(c.db, c.factory, c.conn_id, "get", f"/nodes/{node}/qemu/{vmid}/config")
        except HTTPException:
            c.refuse(f"Impossible de lire la configuration de vm:{vmid} pour vérifier qu'elle n'utilise pas cette correspondance", status.HTTP_409_CONFLICT)
        if isinstance(cfg, dict) and any(USERS[mtype].fullmatch(k) and isinstance(v, str) and pat.search(v) for k, v in cfg.items()):
            used.append(f"vm:{vmid}")
    return used


@router.get("/mappings/{mtype}")
async def list_mappings(conn_id: int, mtype: MType = Path(), check_node: str | None = Query(default=None, pattern=NODE.pattern), db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory)):
    """Correspondances du type demandé ; `check_node` ajoute les vérifications (`checks`) de ce nœud. Lecture seule."""
    params = {"check-node": check_node} if check_node else {}
    return shape_list(await _px(db, factory, conn_id, "get", f"{BASE}/{mtype}", **params), mtype)


@router.get("/mappings/{mtype}/{mid}")
async def get_mapping(conn_id: int, mtype: MType = Path(), mid: str = Path(pattern=ID.pattern), db: Session = Depends(get_db), factory: Factory = Depends(get_client_factory)):
    row = next((r for r in shape_list(await _px(db, factory, conn_id, "get", f"{BASE}/{mtype}"), mtype) if r["id"] == mid), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correspondance introuvable")
    raw = await _px(db, factory, conn_id, "get", f"{BASE}/{mtype}/{mid}")
    d = shape_mapping({**(raw if isinstance(raw, dict) else {}), "id": mid}, mtype)
    if d is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Configuration illisible")
    d["checks"], d["error"] = row["checks"], row["error"]
    d["digest"] = digest_of(d)
    return d


@router.post("/mappings/{mtype}", status_code=status.HTTP_201_CREATED)
async def create_mapping(body: MappingCreate, response: Response, conn_id: int, mtype: MType = Path(), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "mapping-create", f"{mtype}:{body.id}")
    try:
        params, _ = build_params(mtype, body, [])
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if body.dry_run:
        response.status_code = status.HTTP_200_OK
        return {"dry_run": True, "params": {"id": body.id, **params}}
    if any(r["id"] == body.id for r in await _list(c, mtype)):
        c.refuse("Une correspondance porte déjà cet identifiant", status.HTTP_409_CONFLICT)
    await c.px("post", f"{BASE}/{mtype}", id=body.id, **params)
    after, _ = await _detail(c, mtype, body.id)
    if not _same(after, params, mtype):
        c.refuse("Proxmox n'a pas appliqué la création", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, []))
    return after


@router.put("/mappings/{mtype}/{mid}")
async def update_mapping(body: MappingUpdate, conn_id: int, mtype: MType = Path(), mid: str = Path(pattern=ID.pattern), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    c = Ctx(db, factory, conn_id, user, "mapping-update", f"{mtype}:{mid}")
    if not any(r["id"] == mid for r in await _list(c, mtype)):
        c.refuse("Correspondance introuvable", status.HTTP_404_NOT_FOUND)
    cur, raw = await _detail(c, mtype, mid)
    try:
        params, delete = build_params(mtype, body, list(body.clear))
    except ValueError as e:
        c.refuse(str(e), status.HTTP_422_UNPROCESSABLE_ENTITY)
    if not params and not delete:
        c.refuse("Aucune modification demandée", status.HTTP_400_BAD_REQUEST)
    if body.digest is not None and body.digest != cur["digest"]:
        c.refuse("La correspondance a changé depuis ta lecture (digest périmé) : recharge avant de modifier", status.HTTP_409_CONFLICT)
    if body.dry_run:
        return {"dry_run": True, "params": params, "remove": delete}
    send = dict(params)
    if "map" not in send:                                           # Proxmox exige `map` dans le PUT d'une correspondance USB : on renvoie les entrées actuelles telles quelles
        current = raw.get("map") if isinstance(raw.get("map"), list) else []
        send["map"] = [m for m in current if isinstance(m, str)]
    if delete:
        send["delete"] = ",".join(delete)
    if isinstance(raw.get("digest"), str) and re.fullmatch(r"[0-9a-fA-F]{1,64}", raw["digest"]):
        send["digest"] = raw["digest"]
    await c.px("put", f"{BASE}/{mtype}/{mid}", **send)
    after, _ = await _detail(c, mtype, mid)
    gone = {"description": after["description"], "mdev": after["mdev"], "live-migration-capable": after["live_migration_capable"]}
    if not _same(after, params, mtype) or any(gone[k] for k in delete):
        c.refuse("Proxmox n'a pas appliqué la modification", status.HTTP_502_BAD_GATEWAY)
    c.log("started", _txt(params, delete))
    return after


@router.delete("/mappings/{mtype}/{mid}")
async def delete_mapping(conn_id: int, mtype: MType = Path(), mid: str = Path(pattern=ID.pattern), confirm: bool = Query(default=False),
                         type_name: str | None = Query(default=None, max_length=64), dry_run: bool = Query(default=False), db: Session = Depends(get_db),
                         factory: Factory = Depends(get_client_factory), user: AdminUser = Depends(current_user)):
    """Supprime la correspondance. Refusé (409) tant qu'une VM la cite ; exige `confirm=true` ET l'identifiant retapé."""
    c = Ctx(db, factory, conn_id, user, "mapping-delete", f"{mtype}:{mid}")
    if not any(r["id"] == mid for r in await _list(c, mtype)):
        c.refuse("Correspondance introuvable", status.HTTP_404_NOT_FOUND)
    used = await _users(c, mtype, mid)
    if dry_run:
        return {"dry_run": True, "remove": [mid], "retype": mid, "used_by": used}
    if used:
        c.refuse(f"Utilisée par {', '.join(used)} : retire-la de ces machines avant de la supprimer", status.HTTP_409_CONFLICT)
    if not confirm:
        c.refuse("Suppression : renvoie la requête avec confirm=true et l'identifiant retapé (type_name)", status.HTTP_400_BAD_REQUEST)
    if type_name != mid:
        c.refuse("L'identifiant retapé ne correspond pas : suppression refusée", status.HTTP_400_BAD_REQUEST)
    await c.px("delete", f"{BASE}/{mtype}/{mid}")
    if any(r["id"] == mid for r in await _list(c, mtype)):
        c.refuse("Proxmox n'a pas supprimé la correspondance", status.HTTP_502_BAD_GATEWAY)
    c.log("started", "correspondance supprimée")
    return {"deleted": mid}


@router.get("/nodes/{node}/hardware/{htype}")
async def node_hardware(conn_id: int, node: str = Path(pattern=NODE.pattern), htype: HType = Path(), db: Session = Depends(get_db),
                        factory: Factory = Depends(get_client_factory)):
    """Matériel PCI ou USB détecté sur le nœud, avec les valeurs prêtes pour une entrée de correspondance (`map_id`, `map_path`). Lecture seule."""
    return shape_hardware(await _px(db, factory, conn_id, "get", f"/nodes/{node}/hardware/{htype}"), htype)
