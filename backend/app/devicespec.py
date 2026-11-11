"""Périphériques d'une VM : carte d'affichage (`vga`), ports série (`serial0..3`), audio (`audio0`), générateur aléatoire (`rng0`), watchdog.
Validation, lecture et construction des paramètres. Aucun réseau ici (lot #225).

Liste blanche stricte. Choix de sécurité : un port série n'est JAMAIS un périphérique de l'hôte (`/dev/…`), seulement `socket` ; la source du
RNG n'est que `/dev/urandom` (pas `/dev/hwrng` ni `/dev/random`, qui touchent l'hôte). Un réglage déjà posé avec une autre valeur (par root)
est LU (en lecture seule) et conservé : Kaji ne le réécrit pas. Pour `vga`, les propriétés que Kaji ne gère pas sont CONSERVÉES.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt

VGA_TYPES = ("cirrus", "none", "qxl", "qxl2", "qxl3", "qxl4", "serial0", "serial1", "serial2", "serial3", "std", "virtio", "virtio-gl", "vmware")
AUDIO_DEVICES = ("ich9-intel-hda", "intel-hda", "AC97")
AUDIO_DRIVERS = ("spice", "none")
WATCHDOG_MODELS = ("i6300esb", "ib700")
WATCHDOG_ACTIONS = ("reset", "shutdown", "poweroff", "pause", "debug", "none")
RNG_SOURCE = "/dev/urandom"
SERIALS = ("serial0", "serial1", "serial2", "serial3")
KEYS = ("vga", "audio0", "rng0", "watchdog") + SERIALS
CLEARABLE = Literal["vga", "audio0", "rng0", "watchdog", "serial0", "serial1", "serial2", "serial3"]
EXTRA_PROP = re.compile(r"^[A-Za-z0-9_\-]{1,40}=[A-Za-z0-9_\-.]{0,40}$")
SAFE_SOURCE = re.compile(r"^/dev/[a-z0-9]{1,20}$")


class Vga(BaseModel):
    type: Literal["cirrus", "none", "qxl", "qxl2", "qxl3", "qxl4", "serial0", "serial1", "serial2", "serial3", "std", "virtio", "virtio-gl", "vmware"] | None = None
    memory: StrictInt | None = Field(default=None, ge=4, le=512, description="Mémoire vidéo en Mo")
    clipboard: Literal["vnc"] | None = None


class Audio(BaseModel):
    device: Literal["ich9-intel-hda", "intel-hda", "AC97"]
    driver: Literal["spice", "none"] | None = None


class Rng(BaseModel):
    """La source est toujours `/dev/urandom` : elle n'est pas modifiable."""
    max_bytes: StrictInt | None = Field(default=None, ge=0, le=1_000_000)
    period: StrictInt | None = Field(default=None, ge=1, le=3_600_000)


class Watchdog(BaseModel):
    model: Literal["i6300esb", "ib700"]
    action: Literal["reset", "shutdown", "poweroff", "pause", "debug", "none"] | None = None


class DevicesUpdate(BaseModel):
    """Seuls ces champs existent : tout autre champ est ignoré et jamais transmis à Proxmox."""
    vga: Vga | None = None
    serial0: Literal["socket"] | None = None
    serial1: Literal["socket"] | None = None
    serial2: Literal["socket"] | None = None
    serial3: Literal["socket"] | None = None
    audio: Audio | None = None
    rng: Rng | None = None
    watchdog: Watchdog | None = None
    clear: list[CLEARABLE] = Field(default=[], max_length=8, description="Réglages à retirer")
    confirm: StrictBool = False


# ------------------------------------------------------------------ lecture

def kv(value) -> dict[str, str]:
    """« a=1,b=2 » -> {a: 1, b: 2} ; le premier élément sans « = » (forme courte) est rendu sous la clé `_`."""
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


def _int(v) -> int | None:
    return int(v) if isinstance(v, str) and v.isdigit() else None


def parse_vga(value) -> dict | None:
    if value is None:
        return None
    d = kv(value)
    t = d.get("type", d.get("_"))
    return {"type": t if t in VGA_TYPES else None, "memory": _int(d.get("memory")), "clipboard": d.get("clipboard") if d.get("clipboard") == "vnc" else None}


def parse_serial(value) -> str | None:
    """`socket`, ou `device` (un périphérique de l'hôte posé par root : lecture seule, chemin non renvoyé)."""
    if value is None:
        return None
    return "socket" if str(value) == "socket" else "device"


def parse_audio(value) -> dict | None:
    if value is None:
        return None
    d = kv(value)
    dev, drv = d.get("device"), d.get("driver")
    return {"device": dev if dev in AUDIO_DEVICES else None, "driver": drv if drv in AUDIO_DRIVERS else None}


def parse_rng(value) -> dict | None:
    if value is None:
        return None
    d = kv(value)
    src = d.get("source", d.get("_"))
    return {"source": src if isinstance(src, str) and SAFE_SOURCE.fullmatch(src) else None, "max_bytes": _int(d.get("max_bytes")), "period": _int(d.get("period"))}


def parse_watchdog(value) -> dict | None:
    if value is None:
        return None
    d = kv(value)
    m, a = d.get("model", d.get("_")), d.get("action")
    return {"model": m if m in WATCHDOG_MODELS else None, "action": a if a in WATCHDOG_ACTIONS else None}


def normalize_devices(cfg: dict, pending: list) -> dict:
    cfg = cfg if isinstance(cfg, dict) else {}
    devices = {"vga": parse_vga(cfg.get("vga")), "audio": parse_audio(cfg.get("audio0")), "rng": parse_rng(cfg.get("rng0")),
               "watchdog": parse_watchdog(cfg.get("watchdog")), **{k: parse_serial(cfg.get(k)) for k in SERIALS}}
    pend = [{"key": p["key"], "value": p.get("value"), "pending": p.get("pending"), "delete": bool(p.get("delete"))}
            for p in pending if isinstance(p, dict) and p.get("key") in KEYS and ("pending" in p or p.get("delete"))]
    return {"type": "qemu", "devices": devices, "pending": pend, "reboot_required": bool(pend)}


# ------------------------------------------------------------------ écriture

def build_params(body: DevicesUpdate, cfg: dict) -> tuple[dict, list[str]]:
    """`(paramètres à écrire, réglages à retirer)`. `vga` garde ses propriétés inconnues ; `serialN` n'écrase jamais un périphérique d'hôte existant."""
    p: dict = {}
    if body.vga is not None:
        d = kv(cfg.get("vga"))
        if "_" in d:                                                         # forme courte « vga: std »
            d = {"type": d.pop("_"), **d}
        for k in ("type", "memory", "clipboard"):
            v = getattr(body.vga, k)
            if v is not None:
                d[k] = str(v)
        extra = [f"{k}={v}" for k, v in d.items() if k not in ("type", "memory", "clipboard")]
        if not all(EXTRA_PROP.fullmatch(x) for x in extra):
            raise ValueError("Propriété de la carte d'affichage illisible : modification refusée")
        p["vga"] = ",".join([f"{k}={d[k]}" for k in ("type", "memory", "clipboard") if k in d] + extra)
        if not p["vga"]:
            raise ValueError("Carte d'affichage vide")
    for k in SERIALS:
        if getattr(body, k) is not None:
            cur = parse_serial(cfg.get(k))
            if cur == "device":
                raise ValueError(f"{k} est un périphérique de l'hôte (posé par root) : à modifier dans Proxmox")
            p[k] = "socket"
    if body.audio is not None:
        p["audio0"] = ",".join([f"device={body.audio.device}"] + ([f"driver={body.audio.driver}"] if body.audio.driver else []))
    if body.rng is not None:
        cur = parse_rng(cfg.get("rng0")) or {}
        if cur and cur.get("source") != RNG_SOURCE:
            raise ValueError("Source du générateur aléatoire différente de /dev/urandom (posée par root) : à modifier dans Proxmox")
        merged = {k: (getattr(body.rng, k) if getattr(body.rng, k) is not None else cur.get(k)) for k in ("max_bytes", "period")}
        p["rng0"] = ",".join([f"source={RNG_SOURCE}"] + [f"{k}={v}" for k, v in merged.items() if v is not None])
    if body.watchdog is not None:
        p["watchdog"] = ",".join([f"model={body.watchdog.model}"] + ([f"action={body.watchdog.action}"] if body.watchdog.action else []))
    delete = list(dict.fromkeys(body.clear))
    for k in delete:                                                         # retirer un port série ou un RNG posé par root : refusé
        if k in SERIALS and parse_serial(cfg.get(k)) == "device":
            raise ValueError(f"{k} est un périphérique de l'hôte (posé par root) : à retirer dans Proxmox")
        if k == "rng0" and (cur_rng := parse_rng(cfg.get("rng0"))) and cur_rng.get("source") != RNG_SOURCE:
            raise ValueError("Générateur aléatoire sur une source de l'hôte (posé par root) : à retirer dans Proxmox")
    clash = [k for k in delete if k in p]
    if clash:
        raise ValueError(f"Réglage à la fois modifié et retiré : {', '.join(clash)}")
    return p, delete


def risks(body: DevicesUpdate, cfg: dict) -> list[str]:
    """Pourquoi la demande exige une confirmation (relu chez Proxmox)."""
    out = []
    cur = parse_vga(cfg.get("vga")) or {}
    t = body.vga.type if body.vga else None
    if t == "none" and cur.get("type") != "none":
        out.append("vga=none : la console graphique (noVNC) n'affichera plus rien")
    if t and t.startswith("serial") and cur.get("type") != t:
        out.append(f"vga={t} : la console graphique sera remplacée par le port série (noVNC vide)")
    return out
