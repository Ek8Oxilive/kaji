"""Options d'un conteneur LXC : validation, lecture et construction des paramètres. Aucun réseau ici. Lot #145 (suite de `optionspec.py`).

Liste blanche : `onboot`, `startup`, `protection`, `features` (`nesting`, `fuse`, `keyctl`, `mount`), `ostype`, `console`, `cmode`, `tty`,
`timezone`, `description`. Jamais `hookscript`, `lock`, `lxc.*` ni aucune clé libre. `unprivileged` et `arch` ne sont PAS modifiables :
les fournir est refusé (422). Les propriétés de `features` que Kaji ne gère pas (`mknod`, `force_rw_sys`…) sont CONSERVÉES.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator

from .optionspec import AGENT_PROP, CONTROL, MAX_DESCRIPTION, Startup, _bool, kv, parse_startup

LXC_OSTYPES = ("debian", "devuan", "ubuntu", "centos", "fedora", "opensuse", "archlinux", "alpine", "gentoo", "nixos", "unmanaged")
CMODES = ("shell", "console", "tty")
MOUNTS = ("nfs", "cifs")
TIMEZONE = re.compile(r"^(host|[A-Za-z0-9_+\-]{1,32}(/[A-Za-z0-9_+\-]{1,32}){0,2})$")
LXC_CLEARABLE = Literal["onboot", "startup", "protection", "features", "ostype", "console", "cmode", "tty", "timezone", "description"]
LXC_BOOLEANS = ("onboot", "protection", "console")
IMMUTABLE = ("unprivileged", "arch")
MANAGED_FEATURES = ("nesting", "fuse", "keyctl", "mount")
ROOT_ONLY_FEATURES = ("fuse", "keyctl", "mount")                      # Proxmox les réserve à root@pam (essai réel, lot #164)
ROOT_ONLY_MESSAGE = ("Proxmox réserve keyctl, fuse et mount à root@pam : le token de Kaji ne peut pas les modifier. "
                     "Fais-le dans l'interface de Proxmox.")


class Features(BaseModel):
    nesting: StrictBool | None = None
    fuse: StrictBool | None = None
    keyctl: StrictBool | None = None
    mount: list[Literal["nfs", "cifs"]] | None = Field(default=None, max_length=2)

    @field_validator("mount")
    @classmethod
    def _mount(cls, v):
        if v is not None and len(set(v)) != len(v):
            raise ValueError("Type de montage en double")
        return v


class LxcOptionsUpdate(BaseModel):
    """Seuls ces champs existent : tout autre champ est ignoré, SAUF `unprivileged` et `arch` (refusés : non modifiables)."""
    onboot: StrictBool | None = None
    startup: Startup | None = None
    protection: StrictBool | None = None
    features: Features | None = None
    ostype: Literal["debian", "devuan", "ubuntu", "centos", "fedora", "opensuse", "archlinux", "alpine", "gentoo", "nixos", "unmanaged"] | None = None
    console: StrictBool | None = None
    cmode: Literal["shell", "console", "tty"] | None = None
    tty: int | None = Field(default=None, ge=0, le=6)
    timezone: str | None = Field(default=None, max_length=70)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    clear: list[LXC_CLEARABLE] = Field(default=[], max_length=10, description="Réglages à retirer (retour à la valeur par défaut)")
    confirm: StrictBool = False

    @model_validator(mode="before")
    @classmethod
    def _immutable(cls, data):
        if isinstance(data, dict) and any(k in data for k in IMMUTABLE):
            raise ValueError("unprivileged et arch ne sont pas modifiables")
        return data

    @field_validator("tty", mode="before")
    @classmethod
    def _tty(cls, v):
        if isinstance(v, bool) or (v is not None and not isinstance(v, int)):
            raise ValueError("Entier attendu")
        return v

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, v):
        if v is not None and not TIMEZONE.fullmatch(v):
            raise ValueError("Fuseau horaire invalide")
        return v

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        if v is not None and any(CONTROL.fullmatch(ch) for ch in v):
            raise ValueError("Caractère de contrôle interdit")
        return v

    @field_validator("features")
    @classmethod
    def _features(cls, v):
        if v is not None and all(getattr(v, k) is None for k in MANAGED_FEATURES):
            raise ValueError("Features vide")
        return v

    @field_validator("startup")
    @classmethod
    def _startup(cls, v):
        if v is not None and v.order is None and v.up is None and v.down is None:
            raise ValueError("Startup vide")
        return v


# ------------------------------------------------------------------ lecture

def parse_features(value) -> dict | None:
    if value is None:
        return None
    d = kv(value)
    mount = sorted(x for x in str(d.get("mount", "")).split(";") if x in MOUNTS)
    return {"nesting": _bool(d.get("nesting")), "fuse": _bool(d.get("fuse")), "keyctl": _bool(d.get("keyctl")), "mount": mount}


def _tty_value(v) -> int | None:
    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 6:
        return v
    if isinstance(v, str) and v.isascii() and v.isdigit() and int(v) <= 6:
        return int(v)
    return None


def normalize_lxc_options(cfg: dict, pending: list) -> dict:
    cfg = cfg if isinstance(cfg, dict) else {}
    desc = cfg.get("description")
    tty = cfg.get("tty")
    opts = {k: _bool(cfg[k]) if k in cfg else None for k in LXC_BOOLEANS}
    opts.update({
        "startup": parse_startup(cfg.get("startup")), "features": parse_features(cfg.get("features")),
        "ostype": cfg.get("ostype") if cfg.get("ostype") in LXC_OSTYPES else None, "cmode": cfg.get("cmode") if cfg.get("cmode") in CMODES else None,
        "tty": _tty_value(tty),
        "timezone": cfg.get("timezone") if isinstance(cfg.get("timezone"), str) and TIMEZONE.fullmatch(cfg["timezone"]) else None,
        "description": desc[:MAX_DESCRIPTION] if isinstance(desc, str) else None,
    })
    managed = set(LXC_BOOLEANS) | {"startup", "features", "ostype", "cmode", "tty", "timezone", "description"}
    pend = [{"key": p["key"], "value": p.get("value"), "pending": p.get("pending"), "delete": bool(p.get("delete"))}
            for p in pending if isinstance(p, dict) and p.get("key") in managed and ("pending" in p or p.get("delete"))]
    return {"type": "lxc", "options": opts, "unprivileged": _bool(cfg.get("unprivileged")), "pending": pend, "reboot_required": bool(pend)}


# ------------------------------------------------------------------ écriture

def build_lxc_params(body: LxcOptionsUpdate, cfg: dict) -> tuple[dict, list[str]]:
    p: dict = {}
    for k in LXC_BOOLEANS:
        v = getattr(body, k)
        if v is not None:
            p[k] = 1 if v else 0
    for k in ("ostype", "cmode", "timezone", "description", "tty"):
        v = getattr(body, k)
        if v is not None:
            p[k] = v
    if body.startup is not None:
        cur = parse_startup(cfg.get("startup")) or {}
        merged = {k: (getattr(body.startup, k) if getattr(body.startup, k) is not None else cur.get(k)) for k in ("order", "up", "down")}
        p["startup"] = ",".join(f"{k}={v}" for k, v in merged.items() if v is not None)
    if body.features is not None:
        d = kv(cfg.get("features"))
        d.pop("_", None)
        for k in ("nesting", "fuse", "keyctl"):
            v = getattr(body.features, k)
            if v is not None:
                d[k] = "1" if v else "0"
        if body.features.mount is not None:
            if body.features.mount:
                d["mount"] = ";".join(sorted(body.features.mount))
            else:
                d.pop("mount", None)
        extra = [f"{k}={v}" for k, v in d.items() if k not in MANAGED_FEATURES]
        if not all(AGENT_PROP.fullmatch(x) for x in extra):
            raise ValueError("Propriété de features illisible : modification refusée")
        parts = [f"{k}={d[k]}" for k in ("nesting", "fuse", "keyctl") if k in d] + ([f"mount={d['mount']}"] if "mount" in d else []) + extra
        if not parts:
            raise ValueError("Features vide")
        p["features"] = ",".join(parts)
    delete = list(dict.fromkeys(body.clear))
    clash = [k for k in delete if k in p]
    if clash:
        raise ValueError(f"Réglage à la fois modifié et retiré : {', '.join(clash)}")
    return p, delete


def lxc_risks(body: LxcOptionsUpdate, cfg: dict) -> list[str]:
    out = []
    if (body.protection is False or "protection" in body.clear) and _bool(cfg.get("protection")):
        out.append("la protection contre la suppression sera RETIRÉE : le conteneur et ses disques pourront être supprimés")
    return out


def lxc_protected_refusal(body: LxcOptionsUpdate, cfg: dict) -> str | None:
    """Une machine de `KAJI_PROTECTED_VMIDS` refuse de perdre sa protection, confirmation ou non."""
    if lxc_risks(body, cfg):
        return "Ce conteneur est protégé par Kaji : ce réglage dangereux est refusé"
    return None


_ROOT_ONLY_RE = re.compile(r"(?:.*,)?(?:fuse|keyctl|mount)=.*")


def touches_root_only(body, cfg, params, delete) -> bool:
    """La demande envoyée à Proxmox contient-elle `fuse`, `keyctl` ou `mount` ?

    Trois cas : le corps les modifie (même pour les retirer) ; la chaîne `features` reconstruite les garde (un conteneur qui les a déjà : `nesting`
    seul renvoie toute la chaîne) ; `clear: [features]` les retire. `nesting` sur un conteneur sans ces réglages reste permis au token de Kaji."""
    f = body.features
    if f is not None and any(getattr(f, k) is not None for k in ROOT_ONLY_FEATURES):
        return True
    if _ROOT_ONLY_RE.fullmatch(str(params.get("features", ""))):
        return True
    return "features" in delete and bool(_ROOT_ONLY_RE.fullmatch(str(cfg.get("features", ""))))
