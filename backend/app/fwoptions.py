"""Options du pare-feu Proxmox (datacenter, nœud, machine) : écriture, avec verrous à déverrouillage explicite (décision d'Enzo : tout est possible, rien par accident).

Deux verrous, décidés par le SERVEUR sur l'état relu chez Proxmox (jamais par le navigateur) :
- **actif** : le niveau filtre déjà (`enable` vrai) ⇒ toute modification d'option exige `acknowledge_live=true` ;
- **coupure possible** : activer le pare-feu du datacenter ou d'un nœud, ou passer une politique par défaut en `DROP`/`REJECT` sur un niveau actif (ou qu'on active), ou toucher
  au pare-feu de la machine de Kaji ⇒ exige `acknowledge_cut_access=true` ET `type_name == "COUPURE POSSIBLE"`.
`dry_run=true` renvoie les verrous et les paramètres qui seraient envoyés, sans rien écrire. Un niveau désactivé reste modifiable avec `confirm` seul : ses réglages
ne s'appliqueront qu'à l'activation (la réponse le dit).
"""
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

LOG = Literal["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug", "nolog"]
POLICY = Literal["ACCEPT", "REJECT", "DROP"]
HELPERS = ("amanda", "ftp", "irc", "netbios-ns", "pptp", "sane", "sip", "snmp", "tftp")
PHRASE = "COUPURE POSSIBLE"
RESTRICTIVE = ("DROP", "REJECT")
CLEARABLE = {
    "cluster": ("ebtables", "policy_forward", "policy_in", "policy_out"),
    "node": ("log_level_forward", "log_level_in", "log_level_out", "log_nf_conntrack", "ndp", "nf_conntrack_allow_invalid", "nf_conntrack_helpers", "nf_conntrack_max",
             "nf_conntrack_tcp_timeout_established", "nf_conntrack_tcp_timeout_syn_recv", "nftables", "nosmurfs", "protection_synflood", "protection_synflood_burst",
             "protection_synflood_rate", "smurf_log_level", "tcp_flags_log_level", "tcpflags"),
    "guest": ("dhcp", "ipfilter", "log_level_in", "log_level_out", "macfilter", "ndp", "policy_in", "policy_out", "radv"),
}


class Locks(BaseModel):
    confirm: StrictBool = False
    acknowledge_live: StrictBool = False
    acknowledge_cut_access: StrictBool = False
    type_name: str | None = Field(default=None, max_length=40, description=f"« {PHRASE} » pour une opération à risque de coupure")
    dry_run: StrictBool = False
    enable: StrictBool | None = None


class ClusterOptions(Locks):
    ebtables: StrictBool | None = None
    policy_forward: Literal["ACCEPT", "DROP"] | None = None
    policy_in: POLICY | None = None
    policy_out: POLICY | None = None
    clear: list[str] = Field(default=[], max_length=5)


class NodeOptions(Locks):
    log_level_forward: LOG | None = None
    log_level_in: LOG | None = None
    log_level_out: LOG | None = None
    log_nf_conntrack: StrictBool | None = None
    ndp: StrictBool | None = None
    nf_conntrack_allow_invalid: StrictBool | None = None
    nf_conntrack_helpers: list[Literal["amanda", "ftp", "irc", "netbios-ns", "pptp", "sane", "sip", "snmp", "tftp"]] | None = Field(default=None, max_length=9)
    nf_conntrack_max: StrictInt | None = Field(default=None, ge=32768, le=100_000_000)
    nf_conntrack_tcp_timeout_established: StrictInt | None = Field(default=None, ge=7875, le=31_536_000)
    nf_conntrack_tcp_timeout_syn_recv: StrictInt | None = Field(default=None, ge=30, le=60)
    nftables: StrictBool | None = None
    nosmurfs: StrictBool | None = None
    protection_synflood: StrictBool | None = None
    protection_synflood_burst: StrictInt | None = Field(default=None, ge=1, le=1_000_000)
    protection_synflood_rate: StrictInt | None = Field(default=None, ge=1, le=1_000_000)
    smurf_log_level: LOG | None = None
    tcp_flags_log_level: LOG | None = None
    tcpflags: StrictBool | None = None
    clear: list[str] = Field(default=[], max_length=20)

    @field_validator("nf_conntrack_helpers")
    @classmethod
    def _helpers(cls, v):
        if v is not None and len(set(v)) != len(v):
            raise ValueError("Assistant en double")
        return v


class GuestOptions(Locks):
    dhcp: StrictBool | None = None
    ipfilter: StrictBool | None = None
    log_level_in: LOG | None = None
    log_level_out: LOG | None = None
    macfilter: StrictBool | None = None
    ndp: StrictBool | None = None
    policy_in: POLICY | None = None
    policy_out: POLICY | None = None
    radv: StrictBool | None = None
    clear: list[str] = Field(default=[], max_length=10)


MODELS = {"cluster": ClusterOptions, "node": NodeOptions, "guest": GuestOptions}
META = set(Locks.model_fields) - {"enable"} | {"clear"}


def check_clear(level: str, clear: list[str]) -> list[str]:
    bad = [k for k in clear if k not in CLEARABLE[level] + ("enable",)]
    if bad:
        raise ValueError("Réglage non retirable pour ce niveau")
    return list(dict.fromkeys(clear))


def build(level: str, body: BaseModel) -> tuple[dict, list[str]]:
    """`(paramètres Proxmox, réglages à retirer)`. Rien d'autre que la liste blanche n'est jamais envoyé."""
    p: dict = {}
    for k in body.model_fields_set - META - {"enable"}:
        v = getattr(body, k)
        if v is None:
            continue
        p[k] = (1 if v else 0) if isinstance(v, bool) else ",".join(sorted(v)) if isinstance(v, list) else v
    if body.enable is not None:
        p["enable"] = 1 if body.enable else 0
    delete = check_clear(level, list(body.clear))
    clash = [k for k in delete if k in p]
    if clash:
        raise ValueError("Réglage à la fois modifié et retiré")
    if not p and not delete:
        raise ValueError("Aucune modification demandée")
    return p, delete


def locks(level: str, cur: dict, params: dict, delete: list[str], protected_guest: bool) -> dict:
    """Verrous qui s'appliquent, d'après l'état ACTUEL relu chez Proxmox. `cut` : raisons de coupure possible ; `live` : raisons « niveau actif »."""
    was_on = bool(cur.get("enable"))
    will_on = (bool(params["enable"]) if "enable" in params else False if "enable" in delete else was_on)
    turning_on = will_on and not was_on
    cut: list[str] = []
    live: list[str] = []
    if turning_on and level in ("cluster", "node"):
        cut.append(f"activer le pare-feu {'du datacenter' if level == 'cluster' else 'du nœud'} filtre immédiatement tout le trafic de {'tous les nœuds' if level == 'cluster' else 'ce nœud'}, "
                   "y compris l'accès à Proxmox et à Kaji")
    for k in ("policy_in", "policy_out", "policy_forward"):
        new = params.get(k)
        if new in RESTRICTIVE and cur.get(k) != new and will_on and level in ("cluster", "node", "guest"):
            if level != "guest" or protected_guest:
                cut.append(f"{k} = {new} refuse par défaut tout le trafic {'entrant' if k == 'policy_in' else 'sortant' if k == 'policy_out' else 'transféré'} non autorisé par une règle")
    if protected_guest and (turning_on or (will_on and params)):
        cut.append("c'est le pare-feu de la machine de Kaji : une erreur coupe Kaji lui-même")
    if was_on and (params or delete) and not turning_on:
        live.append("le pare-feu de ce niveau est ACTIF : la modification s'applique tout de suite")
    if turning_on and level == "guest" and not protected_guest:
        live.append("le pare-feu de cette machine va commencer à filtrer son trafic")
    if cut:
        live = live or ["la modification s'applique tout de suite"]
    return {"cut": cut, "live": live, "inert": not (cut or live)}
