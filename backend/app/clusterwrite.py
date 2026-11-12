"""Cluster Proxmox en ÉCRITURE (M10-2) : créer un cluster, joindre un nœud, retirer un nœud. Validation en liste blanche, paramètres, verrous décidés par le serveur.

Où part chaque appel (constaté dans le schéma officiel de Proxmox 9, `apidoc.js`) :
- **créer** (`POST /cluster/config`) et **joindre** (`POST /cluster/config/join`) s'adressent au nœud ISOLÉ qui va créer / rejoindre : la connexion de Kaji doit donc pointer sur ce nœud ;
- **retirer** (`DELETE /cluster/config/nodes/{node}`) s'adresse à un AUTRE membre du cluster.

Verrous (état relu chez Proxmox, jamais décidé par le navigateur) :
- **refus, même confirmé** (`blockers`) : ce que Proxmox refuserait de toute façon ou qui casserait le cluster (nœud déjà en cluster, nœud avec des machines à joindre, nœud en ligne ou local à retirer, pas de quorum,
  machine de `KAJI_PROTECTED_VMIDS` sur le nœud retiré) ;
- **coupure possible** (`acknowledge_cut_access=true` ET `type_name == "COUPURE POSSIBLE"`) : joindre (la configuration `/etc/pve` du nœud est REMPLACÉE par celle du cluster : utilisateurs, jetons, stockages ;
  la connexion de Kaji à ce nœud ne marche plus) ; retirer un nœud quand il restera moins de 3 nœuds ;
- **machines concernées** (`acknowledge_guests=true`) : retirer un nœud qui garde des configurations de machines.
`confirm=true` est toujours exigé ; `dry_run=true` renvoie les verrous et ce qui serait envoyé, sans rien écrire.

Le mot de passe root du pair n'existe que dans cette requête : `SecretStr`, jamais journalisé, jamais renvoyé, jamais dans l'audit (« défini »).
"""
import ipaddress
import re

from pydantic import BaseModel, Field, SecretStr, StrictBool, StrictInt, field_validator

from .clusterspec import FP
from .metricsspec import check_host

PHRASE = "COUPURE POSSIBLE"
NODE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,62})$")
CLUSTER_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,13})$")                # format `pve-node`, 15 caractères au plus
NO_CONTROL = re.compile(r"[^\x00-\x1f\x7f]*")
MIN_NODES = 3
MAX_LINKS = 8


def check_link_address(v: str) -> str:
    """Adresse d'un lien corosync : une adresse IP (jamais un nom, jamais une adresse locale, de multidiffusion ou réservée)."""
    try:
        ip = ipaddress.ip_address(v.strip())
    except ValueError:
        raise ValueError("Adresse IP invalide") from None
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        raise ValueError("Adresse locale refusée")
    return str(ip)


class Locks(BaseModel):
    confirm: StrictBool = False
    acknowledge_cut_access: StrictBool = False
    acknowledge_guests: StrictBool = False
    type_name: str | None = Field(default=None, max_length=40, description=f"« {PHRASE} » pour une opération à risque de coupure")
    dry_run: StrictBool = False


class Link(BaseModel):
    link: StrictInt = Field(ge=0, le=MAX_LINKS - 1, description="Numéro du lien corosync (0 à 7)")
    address: str = Field(max_length=45)
    priority: StrictInt | None = Field(default=None, ge=0, le=255, description="Priorité en mode passif (créer seulement : ignorée à l'ajout d'un nœud)")

    _a = field_validator("address")(lambda cls, v: check_link_address(v))


class NodeFields(Locks):
    links: list[Link] = Field(default=[], max_length=MAX_LINKS)
    nodeid: StrictInt | None = Field(default=None, ge=1, le=10000)

    @field_validator("links")
    @classmethod
    def _links(cls, v):
        if len({lk.link for lk in v}) != len(v):
            raise ValueError("Lien en double")
        if len({lk.address for lk in v}) != len(v):
            raise ValueError("Adresse de lien en double")
        return v


class CreateBody(NodeFields):
    clustername: str = Field(pattern=CLUSTER_NAME.pattern, description="Nom du cluster (15 caractères au plus)")
    votes: StrictInt | None = Field(default=None, ge=1, le=10)


class JoinBody(NodeFields):
    hostname: str = Field(max_length=253, description="Nom ou adresse d'un membre du cluster à rejoindre")
    fingerprint: str = Field(pattern=FP.pattern, description="Empreinte SHA-256 du certificat de ce membre (« Join Information »)")
    password: SecretStr = Field(min_length=1, max_length=128, description="Mot de passe root du membre contacté : utilisé une fois, jamais gardé")
    votes: StrictInt | None = Field(default=None, ge=0, le=10)

    _h = field_validator("hostname")(lambda cls, v: check_host(v))

    @field_validator("password")
    @classmethod
    def _pw(cls, v: SecretStr):
        if not NO_CONTROL.fullmatch(v.get_secret_value()):
            raise ValueError("Caractère de contrôle refusé")
        return v


def link_params(links: list[Link], with_priority: bool) -> dict[str, str]:
    out = {}
    for lk in links:
        s = f"address={lk.address}"
        if with_priority and lk.priority is not None:
            s += f",priority={lk.priority}"
        out[f"link{lk.link}"] = s
    return out


def build_create(body: CreateBody) -> dict:
    p: dict = {"clustername": body.clustername, **link_params(body.links, True)}
    if body.nodeid is not None:
        p["nodeid"] = body.nodeid
    if body.votes is not None:
        p["votes"] = body.votes
    return p


def build_join(body: JoinBody) -> dict:
    """Sans le mot de passe : il est ajouté au dernier moment, à l'envoi, et n'apparaît dans aucune réponse ni aucun journal."""
    p: dict = {"hostname": body.hostname, "fingerprint": body.fingerprint, **link_params(body.links, False)}
    if body.nodeid is not None:
        p["nodeid"] = body.nodeid
    if body.votes is not None:
        p["votes"] = body.votes
    return p


def remove_locks(*, nodes_after: int, guests: list[str]) -> dict:
    """Verrous d'un retrait de nœud (les `blockers` sont calculés dans le routeur : ils dépendent de l'état relu)."""
    cut = [f"il restera {nodes_after} nœud(s) : sous {MIN_NODES}, la perte d'un seul nœud fait perdre le quorum au reste du cluster"] if nodes_after < MIN_NODES else []
    live = [f"le nœud garde la configuration de {len(guests)} machine(s) ({', '.join(guests[:10])}{'…' if len(guests) > 10 else ''}) : elles ne démarreront plus tant qu'elles ne sont pas déplacées"] if guests else []
    return {"cut": cut, "live": live}

