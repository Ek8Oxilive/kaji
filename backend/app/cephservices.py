"""Ceph, ÉCRITURE : moniteurs, gestionnaires, MDS, OSD (lot C3 de `docs/m12-ceph.md`). Modèles et règles pures, sans réseau.

Créer, démarrer, arrêter, mettre dedans ou dehors. PAS de destruction (lot C4). Rien de tout cela n'a été validé sur un vrai Ceph.
Hypothèse assumée : le domaine de panne est l'HÔTE (règle CRUSH par défaut) ; une règle qui sépare autrement n'est pas comprise.
"""
import re
from typing import Literal

from pydantic import BaseModel, StrictBool, field_validator

SERVICE_KINDS = ("osd", "mon", "mgr", "mds")
SERVICE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{0,31}")          # `^…$` ajouté à l'usage : motif de chemin (Path)
DEV = re.compile(r"/dev/[A-Za-z0-9][A-Za-z0-9/_\-]{0,63}")
DEVICE_CLASSES = ("hdd", "ssd", "nvme")
RUNNING_MGR = ("active", "standby")


class ConfirmBody(BaseModel):
    """Seul `confirm` existe : tout autre champ est ignoré. Jamais transmis à Proxmox."""
    confirm: StrictBool = False        # le JSON `true` seulement : ni "true", ni 1, ni "oui" ne valent confirmation


class MdsCreate(BaseModel):
    hotstandby: bool = False           # MDS de secours « chaud » (suit le MDS actif de près)


class OsdCreate(BaseModel):
    dev: str
    encrypted: bool = False
    device_class: Literal["hdd", "ssd", "nvme"] | None = None
    confirm: StrictBool = False
    confirm_dev: str | None = None     # le disque retapé : créer un OSD EFFACE le disque

    @field_validator("dev")
    @classmethod
    def _dev(cls, v):
        if not DEV.fullmatch(v) or "//" in v:   # le motif exclut déjà « . » : pas de « .. » possible
            raise ValueError("Nom de disque invalide")
        return v


# ------------------------------------------------------------------ règles pures

def _serving(o: dict) -> bool:
    return o.get("up") is True and o.get("in") is True


def osd_loss(target: dict, osds: list[dict], pools: list[dict], verb: str) -> tuple[str | None, list[str]]:
    """Mettre un OSD dehors ou l'arrêter : `(refus, raisons de confirmation)`. Le refus s'applique même avec confirmation.
    Hôtes encore utiles après l'opération < `min_size` du pool le plus exigeant : des données deviendraient indisponibles.
    Hôtes < `size` : toujours disponible mais plus assez de copies."""
    risks = [("l'OSD sera mis DEHORS : Ceph va déplacer ses données vers les autres OSD (charge et risque pendant ce temps)" if verb == "out"
              else "l'OSD sera ARRÊTÉ : ses copies seront indisponibles tant qu'il ne redémarre pas")]
    if not _serving(target):
        return None, risks
    hosts = {o["host"] for o in osds if o is not target and _serving(o) and o.get("host")}
    mins = [p["min_size"] for p in pools if isinstance(p.get("min_size"), int)]
    sizes = [p["size"] for p in pools if isinstance(p.get("size"), int)]
    if mins and len(hosts) < max(mins):
        return (f"Refusé : il ne resterait que {len(hosts)} hôte(s) avec des OSD utiles pour min_size {max(mins)} : "
                "des données deviendraient indisponibles"), risks
    if sizes and len(hosts) < max(sizes):
        risks.append(f"il ne restera que {len(hosts)} hôte(s) avec des OSD utiles pour size {max(sizes)} : la redondance sera DÉGRADÉE")
    return None, risks


def mon_stop(target: dict, mons: list[dict]) -> tuple[str | None, list[str]]:
    """Arrêter un moniteur : refusé si le quorum (majorité) serait perdu, ou si on ne sait pas qui est dans le quorum."""
    if any(m["in_quorum"] is None for m in mons):
        return "Refusé : l'état du quorum est illisible", []
    needed = len(mons) // 2 + 1
    left = sum(1 for m in mons if m is not target and m["in_quorum"] is True)
    if target["in_quorum"] is True and left < needed:
        return f"Refusé : le quorum serait perdu ({left} moniteur(s) restants sur {len(mons)}, il en faut {needed})", []
    return None, [f"le moniteur sera ARRÊTÉ : {left} sur {len(mons)} resteront dans le quorum (minimum {needed})"]


def mgr_stop(target: dict, mgrs: list[dict]) -> list[str]:
    others = [m for m in mgrs if m is not target and m.get("state") in RUNNING_MGR]
    if not others:
        return ["c'est le DERNIER gestionnaire actif : plus de tableau de bord, plus d'autoscaler de groupes de placement, statistiques figées"]
    return ["le gestionnaire sera ARRÊTÉ : un autre prendra le relais"]


def mds_stop(target: dict, servers: list[dict]) -> list[str]:
    others = [m for m in servers if m is not target and str(m.get("state") or "").startswith("up:")]
    if not others:
        return ["c'est le SEUL MDS actif : CephFS deviendra INDISPONIBLE pour tous ses clients"]
    return ["le MDS sera ARRÊTÉ : un autre prendra le relais"]
