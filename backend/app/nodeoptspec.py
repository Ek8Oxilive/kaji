"""Options d'un nœud (Nœud → Système → Options) : réveil à distance (`wakeonlan`), délai de démarrage des machines (`startall-onboot-delay`) et
cible du ballooning (`ballooning-target`). Schéma lu sur `apidoc.js` de Proxmox 9 (`PUT /nodes/{node}/config`, droit `Sys.Modify` sur `/`).

Les notes (`description`) et l'ACME ont leurs propres fonctions : ils ne sont jamais touchés ici. Une valeur de `wakeonlan` que Kaji ne sait pas lire
fait REFUSER l'écriture de cette option (on ne la réécrit pas à l'aveugle).
"""
import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt

MAC = re.compile(r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}")
IFACE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,15}")
DIGEST = r"^[0-9a-f]{40}$"
_DIGEST = re.compile(r"[0-9a-f]{40}")
CLEARABLE = ("wakeonlan", "startall-onboot-delay", "ballooning-target")
_WOL_KEYS = {"mac": "mac", "bind-interface": "bind_interface", "broadcast-address": "broadcast_address"}


def _valid_ipv4(v: str) -> bool:
    try:
        ipaddress.IPv4Address(v)
        return True
    except ValueError:
        return False


def parse_wol(raw) -> tuple[dict | None, bool]:
    """`(valeur, lisible)` : la chaîne de Proxmox (`mac=AA:…,bind-interface=…` ou la seule adresse MAC) en dictionnaire ; `lisible` faux si une clé ou une valeur est inconnue."""
    if raw is None:
        return None, True
    if not isinstance(raw, str) or not raw or len(raw) > 200:
        return None, False
    out: dict = {"mac": None, "bind_interface": None, "broadcast_address": None}
    for i, part in enumerate(raw.split(",")):
        key, sep, val = part.partition("=")
        if not sep:                                               # clé par défaut : l'adresse MAC, en tête seulement
            key, val = ("mac", part) if i == 0 else ("?", part)
        name = _WOL_KEYS.get(key)
        if name is None or out[name] is not None:
            return None, False
        out[name] = val
    ok = bool(out["mac"] and MAC.fullmatch(out["mac"])) and (out["bind_interface"] is None or bool(IFACE.fullmatch(out["bind_interface"]))) \
        and (out["broadcast_address"] is None or _valid_ipv4(out["broadcast_address"]))
    return (out, True) if ok else (None, False)


def _int(v, lo: int, hi: int):
    if isinstance(v, str) and v.isdigit():
        v = int(v)
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def shape_options(cfg) -> dict:
    """Ce que Kaji sait lire de la configuration du nœud ; `empty` : configuration vide (Proxmox ne renvoie alors pas de digest)."""
    c = cfg if isinstance(cfg, dict) else {}
    wol, readable = parse_wol(c.get("wakeonlan"))
    digest = c.get("digest")
    return {"wakeonlan": wol, "wakeonlan_readable": readable, "startall_onboot_delay": _int(c.get("startall-onboot-delay"), 0, 300),
            "ballooning_target": _int(c.get("ballooning-target"), 0, 100), "digest": digest if isinstance(digest, str) and _DIGEST.fullmatch(digest) else None,
            "empty": isinstance(cfg, dict) and not cfg}


class OptionsBody(BaseModel):
    wakeonlan_mac: str | None = Field(default=None, pattern=f"^{MAC.pattern}$", max_length=17)
    wakeonlan_bind_interface: str | None = Field(default=None, pattern=f"^{IFACE.pattern}$", max_length=16)
    wakeonlan_broadcast_address: str | None = Field(default=None, max_length=15)
    startall_onboot_delay: StrictInt | None = Field(default=None, ge=0, le=300)
    ballooning_target: StrictInt | None = Field(default=None, ge=0, le=100)
    clear: list[Literal["wakeonlan", "startall-onboot-delay", "ballooning-target"]] = Field(default_factory=list, max_length=3)
    digest: str | None = Field(default=None, pattern=DIGEST)
    confirm: StrictBool = False
    dry_run: StrictBool = False


def build_params(cur: dict, body: OptionsBody) -> dict:
    """Paramètres Proxmox pour passer de `cur` (lu) à la demande ; `ValueError` si la demande est incohérente. Seules les options demandées sont envoyées."""
    p: dict = {}
    wol_given = {k: v for k, v in (("mac", body.wakeonlan_mac), ("bind_interface", body.wakeonlan_bind_interface), ("broadcast_address", body.wakeonlan_broadcast_address)) if v is not None}
    if len(set(body.clear)) != len(body.clear):
        raise ValueError("Option retirée en double")
    if body.wakeonlan_broadcast_address is not None and not _valid_ipv4(body.wakeonlan_broadcast_address):
        raise ValueError("Adresse de diffusion IPv4 invalide")
    if ("wakeonlan" in body.clear and wol_given) or ("startall-onboot-delay" in body.clear and body.startall_onboot_delay is not None) \
            or ("ballooning-target" in body.clear and body.ballooning_target is not None):
        raise ValueError("Une option ne peut pas être à la fois modifiée et retirée")
    if wol_given:
        if not cur["wakeonlan_readable"]:
            raise ValueError("Le réglage de réveil actuel du nœud n'est pas lisible par Kaji : modification refusée par précaution")
        merged = {**(cur["wakeonlan"] or {"mac": None, "bind_interface": None, "broadcast_address": None}), **wol_given}
        if not merged.get("mac"):
            raise ValueError("L'adresse MAC est obligatoire pour le réveil à distance")
        p["wakeonlan"] = ",".join(f"{k.replace('_', '-')}={v}" for k, v in merged.items() if v)
    if body.startall_onboot_delay is not None:
        p["startall-onboot-delay"] = body.startall_onboot_delay
    if body.ballooning_target is not None:
        p["ballooning-target"] = body.ballooning_target
    if body.clear:
        p["delete"] = ",".join(body.clear)
    if not p:
        raise ValueError("Aucune modification demandée")
    return p
