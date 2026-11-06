"""Jobs de sauvegarde planifiés (`/cluster/backup`) : validation, paramètres Proxmox, mise en forme, détection de risque."""
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from .backupspec import NOTES, _int, _iso, _str
from .routers.actions import NODE
from .vmspec import POOL, STORAGE

# Identifiant d'un job Proxmox : Kaji le génère à la création (Proxmox ne le renvoie pas).
JOB_ID = r"^[A-Za-z][A-Za-z0-9_\-]{1,63}$"

# Planification : `HH:MM`, éventuellement précédée de jours (`mon`, `mon,wed`, `mon..fri`). Rien d'autre : ni `*`, ni
# intervalles (`*:0/5`), ni secondes, ni dates. Un format libre permettrait une sauvegarde toutes les minutes.
_DOW = r"(?:mon|tue|wed|thu|fri|sat|sun)"
SCHEDULE = re.compile(rf"(?:{_DOW}(?:(?:,|\.\.){_DOW})*\s)?(?:[01][0-9]|2[0-3]):[0-5][0-9]")

KEEP = ("keep_last", "keep_hourly", "keep_daily", "keep_weekly", "keep_monthly", "keep_yearly")  # ordre de la doc
MAX_KEEP = 999


# ------------------------------------------------------------------ rétention

class Retention(BaseModel):
    """Politique de rétention du job. Soit `keep_all`, soit au moins une règle à 1 ou plus (jamais 0 : « garder 0
    sauvegarde » supprimerait tout)."""
    keep_all: bool = False
    keep_last: int | None = Field(default=None, ge=1, le=MAX_KEEP)
    keep_hourly: int | None = Field(default=None, ge=1, le=MAX_KEEP)
    keep_daily: int | None = Field(default=None, ge=1, le=MAX_KEEP)
    keep_weekly: int | None = Field(default=None, ge=1, le=MAX_KEEP)
    keep_monthly: int | None = Field(default=None, ge=1, le=MAX_KEEP)
    keep_yearly: int | None = Field(default=None, ge=1, le=MAX_KEEP)

    @model_validator(mode="after")
    def _coherent(self):
        rules = [k for k in KEEP if getattr(self, k) is not None]
        if self.keep_all and rules:
            raise ValueError("keep_all ne se combine avec aucune autre règle")
        if not self.keep_all and not rules:
            raise ValueError("Au moins une règle de rétention est requise (valeur 1 ou plus)")
        return self

    def as_dict(self) -> dict[str, int]:
        if self.keep_all:
            return {"keep-all": 1}
        return {f"keep-{k[5:]}": getattr(self, k) for k in KEEP if getattr(self, k) is not None}


def retention_string(r: Retention) -> str:
    return ",".join(f"{k}={v}" for k, v in r.as_dict().items())


def parse_retention(raw) -> dict[str, int] | None:
    """`"keep-last=3,keep-daily=7"` (ou un objet) -> `{"keep-last": 3, "keep-daily": 7}` ; `None` si absent ou illisible."""
    items = raw.items() if isinstance(raw, dict) else None
    if items is None and isinstance(raw, str):
        items = (p.split("=", 1) for p in raw.split(",") if "=" in p)
    if items is None:
        return None
    out: dict[str, int] = {}
    for k, v in items:
        k, n = str(k).strip(), _int(v)
        if k.startswith("keep-") and n is not None and (n > 0 or k == "keep-all"):
            out[k] = n
    if out.get("keep-all") == 0:
        del out["keep-all"]
    return out or None


def retention_is_finite(d: dict[str, int] | None) -> bool:
    """Vrai si la politique peut supprimer des sauvegardes (au moins une règle, et pas `keep-all`)."""
    return bool(d) and not d.get("keep-all")


def retention_reduced(old: dict[str, int] | None, new: dict[str, int]) -> bool:
    """Vrai si `new` peut garder MOINS de sauvegardes que `old`. Les règles s'additionnent (chacune couvre sa période) :
    ajouter une règle ou en augmenter une garde un sur-ensemble ; en retirer une ou en diminuer une peut supprimer.
    Une ancienne politique absente ou `keep-all` garde tout : toute politique finie la réduit."""
    if not retention_is_finite(new):
        return False
    if not retention_is_finite(old):
        return True
    return any(k not in new or new[k] < v for k, v in old.items())


# ------------------------------------------------------------------ sélection

class SelVmids(BaseModel):
    type: Literal["vmids"]
    vmids: list[int] = Field(min_length=1, max_length=100)

    @field_validator("vmids")
    @classmethod
    def _ids(cls, v):
        if any(not 100 <= i <= 999999999 for i in v) or len(set(v)) != len(v):
            raise ValueError("Identifiants invalides ou en double")
        return v


class SelPool(BaseModel):
    type: Literal["pool"]
    pool: str

    @field_validator("pool")
    @classmethod
    def _pool(cls, v):
        if not POOL.fullmatch(v):
            raise ValueError("Nom de pool invalide")
        return v


class SelAll(BaseModel):
    type: Literal["all"]


Selection = Annotated[Union[SelVmids, SelPool, SelAll], Field(discriminator="type")]


def selection_params(s) -> dict:
    if s.type == "all":
        return {"all": 1}
    if s.type == "pool":
        return {"pool": s.pool}
    return {"vmid": ",".join(str(i) for i in sorted(s.vmids))}


def selection_of(job: dict) -> dict:
    """Sélection d'un job Proxmox, sous la même forme que celle acceptée par l'API."""
    if _int(job.get("all")):
        return {"type": "all"}
    if isinstance(job.get("pool"), str) and job["pool"]:
        return {"type": "pool", "pool": job["pool"]}
    ids = [i for i in (_int(x) for x in str(job.get("vmid", "")).split(",")) if i is not None]
    return {"type": "vmids", "vmids": sorted(ids)} if ids else {"type": None}


def selection_dict(s) -> dict:
    return selection_of(selection_params(s))


def describe_selection(sel: dict) -> str:
    return {"all": "toutes les machines", "pool": f"pool {sel.get('pool')}",
            "vmids": "machines " + ",".join(str(i) for i in sel.get("vmids", []))}.get(sel.get("type"), "sélection inconnue")


# ------------------------------------------------------------------ corps de requête

Mode = Literal["snapshot", "suspend", "stop"]
Compress = Literal["zstd", "gzip", "lzo", "none"]


class _JobFields(BaseModel):
    @field_validator("schedule", "storage", "node", "notes", check_fields=False)
    @classmethod
    def _text(cls, v, info):
        if v is None:
            return v
        ok = {"schedule": SCHEDULE.fullmatch, "storage": STORAGE.fullmatch, "node": re.compile(NODE).fullmatch,
              "notes": NOTES.fullmatch}[info.field_name](v)
        if not ok:
            raise ValueError(f"Valeur invalide pour {info.field_name}")
        return v


class JobCreate(_JobFields):
    """Seuls ces champs existent : tout autre champ est ignoré et jamais transmis à Proxmox."""
    schedule: str
    storage: str
    selection: Selection
    mode: Mode = "snapshot"
    compress: Compress = "zstd"
    retention: Retention | None = None
    node: str | None = None
    enabled: bool = True
    notes: str | None = Field(default=None, max_length=200)
    confirm: bool = False


class JobUpdate(_JobFields):
    """Mise à jour partielle : seuls les champs fournis changent. `node: null` et `notes: null` les retirent ; les autres
    champs ne peuvent pas être `null`."""
    schedule: str | None = None
    storage: str | None = None
    selection: Selection | None = None
    mode: Mode | None = None
    compress: Compress | None = None
    retention: Retention | None = None
    node: str | None = None
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=200)
    confirm: bool = False

    @model_validator(mode="after")
    def _partial(self):
        given = self.model_fields_set - {"confirm"}
        if not given:
            raise ValueError("Aucune modification demandée")
        for k in given - {"node", "notes"}:
            if getattr(self, k) is None:
                raise ValueError(f"{k} ne peut pas être null")
        return self


# ------------------------------------------------------------------ paramètres Proxmox

def _common(b) -> dict:
    p: dict = {}
    if b.schedule is not None:
        p["schedule"] = b.schedule
    if b.storage is not None:
        p["storage"] = b.storage
    if b.mode is not None:
        p["mode"] = b.mode
    if b.compress is not None:
        p["compress"] = "0" if b.compress == "none" else b.compress
    if b.enabled is not None:
        p["enabled"] = 1 if b.enabled else 0
    if b.retention is not None:
        p["prune-backups"] = retention_string(b.retention)
    if b.node:
        p["node"] = b.node
    if b.notes:
        p["notes-template"] = b.notes
    return p


def create_params(b: JobCreate, job_id: str) -> dict:
    return {"id": job_id, **selection_params(b.selection), **_common(b)}


def update_params(b: JobUpdate, old: dict) -> tuple[dict, list[str]]:
    """`(paramètres, clés à supprimer)`. Changer de sélection supprime les anciennes clés de sélection (et `exclude`,
    qui n'a de sens qu'avec `all`) ; seules les clés réellement présentes dans le job sont supprimées."""
    p, delete = _common(b), []
    given = b.model_fields_set
    if b.selection is not None:
        sp = selection_params(b.selection)
        p.update(sp)
        stale = {"vmid", "pool", "all"} - set(sp)
        if b.selection.type != "all":
            stale.add("exclude")
        delete += sorted(k for k in stale if old.get(k) not in (None, "", 0, "0"))
    if "node" in given and b.node is None and old.get("node"):
        delete.append("node")
    if "notes" in given and not b.notes and old.get("notes-template"):
        delete.append("notes-template")
    return p, delete


# ------------------------------------------------------------------ confirmations

R_STOP = "le mode « stop » ARRÊTE chaque machine à chaque exécution du job"
R_NEW_RETENTION = ("la rétention supprimera, dès la première exécution, les sauvegardes plus anciennes des machines "
                   "sélectionnées sur ce stockage, y compris celles faites hors de ce job")
R_REDUCED = "cette modification RÉDUIT la rétention : les sauvegardes qui ne rentrent plus seront supprimées"
R_RETARGET = ("la rétention s'appliquera à un autre stockage ou à d'autres machines : leurs sauvegardes plus anciennes "
              "seront supprimées")


def create_risks(b: JobCreate) -> list[str]:
    risks = []
    if b.mode == "stop":
        risks.append(R_STOP)
    if b.retention is not None and retention_is_finite(b.retention.as_dict()):
        risks.append(R_NEW_RETENTION)
    return risks


def update_risks(b: JobUpdate, old: dict) -> list[str]:
    risks = []
    old_ret = parse_retention(old.get("prune-backups"))
    old_enabled = _int(old.get("enabled")) != 0
    effective_mode = b.mode or old.get("mode") or "snapshot"
    if effective_mode == "stop" and (b.mode == "stop" or (b.enabled is True and not old_enabled)):
        risks.append(R_STOP)
    new_ret = b.retention.as_dict() if b.retention is not None else old_ret
    if b.retention is not None and retention_reduced(old_ret, new_ret):
        risks.append(R_REDUCED)
    if retention_is_finite(new_ret):
        storage_changed = b.storage is not None and b.storage != old.get("storage")
        selection_changed = b.selection is not None and selection_dict(b.selection) != selection_of(old)
        if storage_changed or selection_changed:
            risks.append(R_RETARGET)
    return risks


# ------------------------------------------------------------------ mise en forme

def shape_job(j) -> dict | None:
    if not isinstance(j, dict) or not isinstance(j.get("id"), str) or not j["id"]:
        return None
    ret = parse_retention(j.get("prune-backups"))
    nxt = _int(j.get("next-run"))
    return {
        "id": j["id"], "enabled": _int(j.get("enabled")) != 0, "schedule": _str(j.get("schedule")),
        "storage": _str(j.get("storage")), "mode": _str(j.get("mode")) or "snapshot",
        "compress": "none" if str(j.get("compress", "")) == "0" else _str(j.get("compress")),
        "node": _str(j.get("node")), "selection": selection_of(j),
        "retention": ({"keep_all": True} if ret and ret.get("keep-all")
                      else {k.replace("-", "_"): v for k, v in ret.items()} if ret else None),
        "notes": _str(j.get("notes-template")), "next_run": _iso(nxt), "repeat_missed": _int(j.get("repeat-missed")) == 1,
    }


def shape_jobs(data) -> list[dict]:
    return sorted((s for s in (shape_job(j) for j in (data if isinstance(data, list) else [])) if s),
                  key=lambda j: j["id"])
