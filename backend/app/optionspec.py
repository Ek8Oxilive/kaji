"""Options d'une VM (onglet « Options » de Proxmox) : validation, lecture et construction des paramètres. Aucun réseau ici.

Liste blanche : `onboot`, `startup`, `ostype`, `agent`, `tablet`, `protection`, `hotplug`, `numa`, `localtime`, `acpi`, `kvm`, `freeze`,
`description`. Jamais `hookscript`, `args`, `lock`, `vmgenid` ni aucune clé libre. Les réglages « structurés » (`startup`, `agent`,
`hotplug`) sont reconstruits champ par champ ; pour `agent`, les propriétés que Kaji ne gère pas sont CONSERVÉES telles quelles.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, field_validator

OSTYPES = ("other", "wxp", "w2k", "w2k3", "w2k8", "wvista", "win7", "win8", "win10", "win11", "l24", "l26", "solaris")
HOTPLUG = ("network", "disk", "cpu", "memory", "usb", "cloudinit")
KEYBOARDS = ("de", "de-ch", "da", "en-gb", "en-us", "es", "fi", "fr", "fr-be", "fr-ca", "fr-ch", "hu", "is", "it", "ja", "lt", "mk", "nl", "no", "pl", "pt", "pt-br", "sv", "sl", "tr")
CLEARABLE = Literal["onboot", "startup", "ostype", "agent", "tablet", "protection", "hotplug", "numa", "localtime", "acpi", "kvm", "freeze", "reboot", "keyboard", "description"]
BOOLEANS = ("onboot", "tablet", "protection", "numa", "localtime", "acpi", "kvm", "freeze", "reboot")
DIGEST = re.compile(r"^[0-9a-f]{40}$")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")              # tout sauf \t \n \r
MAX_DESCRIPTION = 8192
MAX_SECONDS = 86400
MAX_ORDER = 9999
AGENT_PROP = re.compile(r"^[A-Za-z0-9_\-]{1,40}=[A-Za-z0-9_\-.]{0,40}$")


class Startup(BaseModel):
    order: int | None = Field(default=None, ge=0, le=MAX_ORDER, description="Ordre de démarrage (0 = premier)")
    up: int | None = Field(default=None, ge=0, le=MAX_SECONDS, description="Délai d'attente après le démarrage, en secondes")
    down: int | None = Field(default=None, ge=0, le=MAX_SECONDS, description="Délai d'attente à l'arrêt, en secondes")


class Agent(BaseModel):
    enabled: StrictBool | None = None
    fstrim_cloned_disks: StrictBool | None = None


class OptionsUpdate(BaseModel):
    """Seuls ces champs existent : tout autre champ est ignoré et jamais transmis à Proxmox."""
    onboot: StrictBool | None = None
    startup: Startup | None = None
    ostype: Literal["other", "wxp", "w2k", "w2k3", "w2k8", "wvista", "win7", "win8", "win10", "win11", "l24", "l26", "solaris"] | None = None
    agent: Agent | None = None
    tablet: StrictBool | None = None
    protection: StrictBool | None = None
    hotplug: list[Literal["network", "disk", "cpu", "memory", "usb", "cloudinit"]] | None = Field(default=None, max_length=6)
    numa: StrictBool | None = None
    localtime: StrictBool | None = None
    acpi: StrictBool | None = None
    kvm: StrictBool | None = None
    freeze: StrictBool | None = None
    reboot: StrictBool | None = None
    keyboard: Literal["de", "de-ch", "da", "en-gb", "en-us", "es", "fi", "fr", "fr-be", "fr-ca", "fr-ch", "hu", "is", "it", "ja", "lt", "mk", "nl", "no", "pl", "pt", "pt-br", "sv", "sl", "tr"] | None = None
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    clear: list[CLEARABLE] = Field(default=[], max_length=15, description="Réglages à retirer (retour à la valeur par défaut)")
    confirm: StrictBool = False

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        if v is not None and any(CONTROL.fullmatch(ch) for ch in v):
            raise ValueError("Caractère de contrôle interdit")
        return v

    @field_validator("hotplug")
    @classmethod
    def _hotplug(cls, v):
        if v is not None and len(set(v)) != len(v):
            raise ValueError("Fonction en double")
        return v

    @field_validator("startup")
    @classmethod
    def _startup(cls, v):
        if v is not None and v.order is None and v.up is None and v.down is None:
            raise ValueError("Startup vide")
        return v

    @field_validator("agent")
    @classmethod
    def _agent(cls, v):
        if v is not None and v.enabled is None and v.fstrim_cloned_disks is None:
            raise ValueError("Agent vide")
        return v


# ------------------------------------------------------------------ lecture

def _bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if str(v) in ("1", "true"):
        return True
    if str(v) in ("0", "false"):
        return False
    return None


def kv(value) -> dict[str, str]:
    """« a=1,b=2 » -> {a: 1, b: 2}. Un premier élément sans « = » (forme courte de `agent`, `1`) est rendu sous la clé `_`."""
    out: dict[str, str] = {}
    for i, part in enumerate(str(value or "").split(",")):
        k, sep, v = part.partition("=")
        if not part:
            continue
        if sep:
            out[k.strip()] = v.strip()
        elif i == 0:
            out["_"] = k.strip()
    return out


def parse_agent(value) -> dict | None:
    if value is None:
        return None
    d = kv(value)
    enabled = _bool(d.get("enabled", d.get("_")))
    return {"enabled": enabled, "fstrim_cloned_disks": _bool(d.get("fstrim_cloned_disks"))}


def parse_startup(value) -> dict | None:
    if value is None:
        return None
    d = kv(value)
    num = lambda k: int(d[k]) if d.get(k, "").isdigit() else None  # noqa: E731
    return {"order": num("order"), "up": num("up"), "down": num("down")}


def parse_hotplug(value) -> list[str] | None:
    if value is None:
        return None
    s = str(value).strip()
    if s in ("0", ""):
        return []
    if s == "1":
        return ["disk", "network", "usb"]                                  # valeur par défaut de Proxmox
    return sorted(x for x in s.split(",") if x in HOTPLUG)


def normalize_options(cfg: dict, pending: list) -> dict:
    cfg = cfg if isinstance(cfg, dict) else {}
    desc = cfg.get("description")
    opts = {k: _bool(cfg[k]) if k in cfg else None for k in BOOLEANS}
    opts.update({
        "startup": parse_startup(cfg.get("startup")), "ostype": cfg.get("ostype") if cfg.get("ostype") in OSTYPES else None,
        "agent": parse_agent(cfg.get("agent")), "hotplug": parse_hotplug(cfg.get("hotplug")), "keyboard": cfg.get("keyboard") if cfg.get("keyboard") in KEYBOARDS else None,
        "description": desc[:MAX_DESCRIPTION] if isinstance(desc, str) else None,
    })
    managed = set(BOOLEANS) | {"startup", "ostype", "agent", "hotplug", "keyboard", "description"}
    pend = [{"key": p["key"], "value": p.get("value"), "pending": p.get("pending"), "delete": bool(p.get("delete"))}
            for p in pending if isinstance(p, dict) and p.get("key") in managed and ("pending" in p or p.get("delete"))]
    return {"type": "qemu", "options": opts, "pending": pend, "reboot_required": bool(pend)}


# ------------------------------------------------------------------ écriture

def build_params(body: OptionsUpdate, cfg: dict) -> tuple[dict, list[str]]:
    """`(paramètres à écrire, réglages à retirer)`. Les réglages structurés sont reconstruits ; `agent` garde les propriétés inconnues."""
    p: dict = {}
    for k in BOOLEANS:
        v = getattr(body, k)
        if v is not None:
            p[k] = 1 if v else 0
    if body.ostype is not None:
        p["ostype"] = body.ostype
    if body.keyboard is not None:
        p["keyboard"] = body.keyboard
    if body.description is not None:
        p["description"] = body.description
    if body.hotplug is not None:
        p["hotplug"] = ",".join(sorted(body.hotplug)) if body.hotplug else "0"
    if body.startup is not None:
        cur = parse_startup(cfg.get("startup")) or {}
        merged = {k: (getattr(body.startup, k) if getattr(body.startup, k) is not None else cur.get(k)) for k in ("order", "up", "down")}
        p["startup"] = ",".join(f"{k}={v}" for k, v in merged.items() if v is not None)
    if body.agent is not None:
        d = kv(cfg.get("agent"))
        if "_" in d:                                                         # forme courte « agent: 1 »
            d = {"enabled": d.pop("_"), **d}
        if body.agent.enabled is not None:
            d["enabled"] = "1" if body.agent.enabled else "0"
        if body.agent.fstrim_cloned_disks is not None:
            d["fstrim_cloned_disks"] = "1" if body.agent.fstrim_cloned_disks else "0"
        extra = [f"{k}={v}" for k, v in d.items() if k not in ("enabled", "fstrim_cloned_disks")]
        if not all(AGENT_PROP.fullmatch(x) for x in extra):
            raise ValueError("Propriété de l'agent illisible : modification refusée")
        p["agent"] = ",".join([f"{k}={d[k]}" for k in ("enabled", "fstrim_cloned_disks") if k in d] + extra)
    delete = list(dict.fromkeys(body.clear))
    clash = [k for k in delete if k in p]
    if clash:
        raise ValueError(f"Réglage à la fois modifié et retiré : {', '.join(clash)}")
    return p, delete


def risks(body: OptionsUpdate, cfg: dict) -> list[str]:
    """Pourquoi la demande exige une confirmation (relu chez Proxmox, jamais une valeur du navigateur)."""
    out = []
    cur = {k: _bool(cfg.get(k)) for k in ("protection", "kvm", "acpi", "freeze", "reboot")}
    if (body.protection is False or "protection" in body.clear) and cur["protection"]:
        out.append("la protection contre la suppression sera RETIRÉE : la machine et ses disques pourront être supprimés")
    if body.kvm is False and cur["kvm"] is not False:
        out.append("kvm=0 désactive la virtualisation matérielle : la machine sera très lente, voire inutilisable")
    if body.acpi is False and cur["acpi"] is not False:
        out.append("acpi=0 : l'arrêt et le redémarrage propres depuis Proxmox peuvent ne plus fonctionner")
    if body.reboot is False and cur["reboot"] is not False:
        out.append("reboot=0 : un redémarrage lancé depuis le système invité ARRÊTERA la machine au lieu de la redémarrer")
    if body.freeze is True and not cur["freeze"]:
        out.append("freeze=1 : la machine démarrera GELÉE (le processeur ne s'exécute pas) tant qu'on ne la relance pas à la main")
    return out


def protected_refusal(body: OptionsUpdate, cfg: dict) -> str | None:
    """Pour une machine protégée par Kaji (`KAJI_PROTECTED_VMIDS`) : les réglages qui retirent ou affaiblissent une protection sont
    refusés, confirmation ou non. Elle ne peut pas être contournée par cette route."""
    if risks(body, cfg):
        return "Cette machine est protégée par Kaji : ce réglage dangereux est refusé"
    return None
