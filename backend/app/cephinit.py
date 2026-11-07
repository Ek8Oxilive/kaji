"""Ceph, ÉCRITURE : initialisation (lot C5 de `docs/m12-ceph.md`). Modèle et règles pures, sans réseau.

`pveceph init` écrit la configuration partagée de TOUT le cluster (`/etc/pve/ceph.conf`) et fixe ses réseaux. L'installation des
paquets n'a PAS d'API chez Proxmox (elle passe par `pveceph install`, dans le shell du nœud) : elle n'est pas faite ici.
Rien de tout cela n'a été validé sur un vrai Ceph. `disable_cephx` et `pg_bits` ne sont JAMAIS transmis.
"""
import ipaddress
import re

from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator

NETWORK_TEXT = re.compile(r"[0-9A-Fa-f:.]{2,45}/[0-9]{1,3}")        # ni espace, ni retour à la ligne, ni nom d'hôte
V4_PREFIX = (8, 30)
V6_PREFIX = (32, 120)


def normalize_network(v: str) -> str:
    """`10.10.10.7/24` -> `10.10.10.0/24`. Refuse ce qui ne peut pas être un réseau de stockage : adresse sans réseau, boucle locale,
    multicast, lien local, préfixe trop large ou trop étroit."""
    if not isinstance(v, str) or not NETWORK_TEXT.fullmatch(v):
        raise ValueError("Réseau invalide : attendu au format CIDR, par exemple 10.10.10.0/24")
    try:
        net = ipaddress.ip_network(v, strict=False)
    except ValueError:
        raise ValueError("Réseau invalide : attendu au format CIDR, par exemple 10.10.10.0/24") from None
    lo, hi = V4_PREFIX if net.version == 4 else V6_PREFIX
    if not lo <= net.prefixlen <= hi:
        raise ValueError(f"Préfixe invalide : entre /{lo} et /{hi}")
    if net.network_address.is_unspecified or net.network_address.is_loopback or net.network_address.is_multicast or net.network_address.is_link_local:
        raise ValueError("Ce réseau ne peut pas servir à Ceph (adresse nulle, boucle locale, multicast ou lien local)")
    return str(net)


class CephInit(BaseModel):
    """Seuls ces champs existent : tout autre champ est ignoré et jamais transmis à Proxmox."""
    network: str
    cluster_network: str | None = None
    size: int = Field(default=3, ge=2, le=7)
    min_size: int = Field(default=2, ge=2, le=7)
    confirm: StrictBool = False

    @field_validator("network", "cluster_network")
    @classmethod
    def _net(cls, v):
        return None if v is None else normalize_network(v)

    @model_validator(mode="after")
    def _coherent(self):
        if self.min_size > self.size:
            raise ValueError("min_size ne peut pas dépasser size")
        if self.cluster_network is not None and self.cluster_network == self.network:
            raise ValueError("Le réseau de cluster est identique au réseau public : laisse-le vide")
        return self


def init_params(b: CephInit) -> dict:
    p: dict = {"network": b.network, "size": b.size, "min_size": b.min_size}
    if b.cluster_network:
        p["cluster-network"] = b.cluster_network
    return p


def init_risks(b: CephInit) -> list[str]:
    risks = ["cela initialise Ceph pour TOUT le cluster : la configuration partagée (/etc/pve/ceph.conf) est écrite et les réseaux sont fixés ; "
             "les changer ensuite est délicat"]
    for label, net in (("public", b.network), ("de cluster", b.cluster_network)):
        if net and not ipaddress.ip_network(net).is_private:
            risks.append(f"le réseau {label} {net} n'est PAS un réseau privé : le trafic Ceph circulerait sans chiffrement sur un réseau public")
    if b.size == 2:
        risks.append("size vaut 2 : par défaut, chaque pool n'aura que 2 copies des données")
    return risks
