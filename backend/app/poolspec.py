"""Pools de ressources (Datacenter → Permissions → Pools) : validation, lecture et construction des paramètres. Aucun réseau ici (lot #298).

Liste blanche stricte. Identifiant `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$` (pas de pool imbriqué). Listes de machines et de stockages validées élément par élément,
sans doublon ; un même élément ne peut pas être ajouté ET retiré dans la même demande. Les membres lus chez Proxmox sont ramenés à une liste blanche de champs.
"""
import re

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

POOLID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,39}")
STORAGE_ID = re.compile(r"[A-Za-z][A-Za-z0-9._\-]{0,63}")                # pve-storage-id
CONTROL = re.compile(r".*[\x00-\x08\x0b-\x1f\x7f].*", re.DOTALL)         # contient un caractère de contrôle (tout sauf \t et \n)
MAX_COMMENT = 200
MAX_MEMBERS = 500
MIN_VMID, MAX_VMID = 100, 999_999_999


def _comment(v):
    if v is not None and CONTROL.fullmatch(v):
        raise ValueError("Caractère de contrôle interdit")
    return v


class PoolCreate(BaseModel):
    poolid: str = Field(max_length=40)
    comment: str | None = Field(default=None, max_length=MAX_COMMENT)

    @field_validator("poolid")
    @classmethod
    def _poolid(cls, v):
        if not POOLID.fullmatch(v):
            raise ValueError("Identifiant de pool invalide")
        return v

    _c = field_validator("comment")(lambda cls, v: _comment(v))


class PoolUpdate(BaseModel):
    """Seuls ces champs existent : tout autre champ est ignoré et jamais transmis à Proxmox."""
    comment: str | None = Field(default=None, max_length=MAX_COMMENT)
    add_vms: list[StrictInt] = Field(default=[], max_length=50)
    remove_vms: list[StrictInt] = Field(default=[], max_length=50)
    add_storage: list[str] = Field(default=[], max_length=20)
    remove_storage: list[str] = Field(default=[], max_length=20)
    allow_move: StrictBool = False
    confirm: StrictBool = False
    dry_run: StrictBool = False

    _c = field_validator("comment")(lambda cls, v: _comment(v))

    @field_validator("add_vms", "remove_vms")
    @classmethod
    def _vms(cls, v):
        if any(not MIN_VMID <= x <= MAX_VMID for x in v) or len(set(v)) != len(v):
            raise ValueError("Identifiants de machine invalides ou en double")
        return v

    @field_validator("add_storage", "remove_storage")
    @classmethod
    def _storage(cls, v):
        if any(not STORAGE_ID.fullmatch(x) for x in v) or len(set(v)) != len(v):
            raise ValueError("Identifiants de stockage invalides ou en double")
        return v

    def check(self) -> str | None:
        """Incohérences entre champs (sans réseau) : message de refus ou None."""
        if set(self.add_vms) & set(self.remove_vms) or set(self.add_storage) & set(self.remove_storage):
            return "Un même élément ne peut pas être ajouté et retiré dans la même demande"
        if not (self.comment is not None or self.add_vms or self.remove_vms or self.add_storage or self.remove_storage):
            return "Aucune modification demandée"
        return None


# ------------------------------------------------------------------ lecture

def _s(v, n=200) -> str | None:
    return v[:n] if isinstance(v, str) else None


def shape_member(m) -> dict | None:
    """Membre d'un pool -> champs sûrs. Machine : `{type, vmid, name, node, status}` ; stockage : `{type: storage, storage, node}`."""
    if not isinstance(m, dict):
        return None
    t = m.get("type")
    if t in ("qemu", "lxc", "openvz") and isinstance(m.get("vmid"), int) and not isinstance(m.get("vmid"), bool):
        return {"type": "lxc" if t != "qemu" else "qemu", "vmid": m["vmid"], "name": _s(m.get("name"), 100), "node": _s(m.get("node"), 64), "status": _s(m.get("status"), 20)}
    if t == "storage" and isinstance(m.get("storage"), str) and STORAGE_ID.fullmatch(m["storage"]):
        return {"type": "storage", "storage": m["storage"], "node": _s(m.get("node"), 64)}
    return None


def shape_pool(raw) -> dict | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("poolid"), str) or not POOLID.fullmatch(raw["poolid"]):
        return None
    members = [x for x in (shape_member(m) for m in (raw.get("members") if isinstance(raw.get("members"), list) else [])) if x][:MAX_MEMBERS]
    return {"poolid": raw["poolid"], "comment": _s(raw.get("comment"), MAX_COMMENT), "members": members,
            "vms": sorted(x["vmid"] for x in members if x["type"] != "storage"), "storages": sorted({x["storage"] for x in members if x["type"] == "storage"})}


def shape_pools(raw) -> list[dict]:
    return sorted((p for p in (shape_pool(r) for r in (raw if isinstance(raw, list) else [])) if p), key=lambda p: p["poolid"])


# ------------------------------------------------------------------ plan d'écriture

def plan_calls(poolid: str, body: PoolUpdate) -> list[dict]:
    """Appels `PUT /pools` à faire, dans l'ordre : ajouts (et commentaire) d'abord, retraits ensuite (Proxmox a un seul indicateur `delete`)."""
    calls = []
    add: dict = {"poolid": poolid}
    if body.comment is not None:
        add["comment"] = body.comment
    if body.add_vms:
        add["vms"] = ",".join(str(v) for v in body.add_vms)
    if body.add_storage:
        add["storage"] = ",".join(body.add_storage)
    if body.allow_move and body.add_vms:
        add["allow-move"] = 1
    if len(add) > 1:
        calls.append(add)
    if body.remove_vms or body.remove_storage:
        rem: dict = {"poolid": poolid, "delete": 1}
        if body.remove_vms:
            rem["vms"] = ",".join(str(v) for v in body.remove_vms)
        if body.remove_storage:
            rem["storage"] = ",".join(body.remove_storage)
        calls.append(rem)
    return calls
