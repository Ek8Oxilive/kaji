"""Haute disponibilité (HA) Proxmox en ÉCRITURE : validation en liste blanche, paramètres, verrous décidés par le serveur.

Droit requis chez Proxmox : `Sys.Console` sur `/` pour toutes les routes d'écriture HA. Les groupes HA n'existent plus (remplacés par des règles).

Verrous (état relu chez Proxmox, jamais décidé par le navigateur) :
- **interdit, même confirmé** : une machine de `KAJI_PROTECTED_VMIDS` (dont Kaji lui-même) ne peut ni entrer en HA, ni être migrée / relocalisée, ni figurer dans une règle ;
- **coupure possible** (`acknowledge_cut_access=true` ET `type_name == "COUPURE POSSIBLE"`) : cluster à moins de 3 nœuds. La HA arme un chien de garde ; si un nœud tombe,
  l'autre perd le quorum et redémarre. Toute écriture qui ACTIVE ou DÉPLACE de la HA est concernée ; retirer ou désactiver ne l'est pas ;
- **en direct** (`acknowledge_live=true`) : modifier, migrer, relocaliser ou retirer ce que la HA gère déjà, créer une ressource qui sera démarrée / gérée tout de suite.
`dry_run=true` renvoie les verrous et ce qui serait envoyé, sans rien écrire.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator, model_validator

SID = re.compile(r"^(vm|ct):[1-9][0-9]{2,8}$")
NODE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,62})$")
RULE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")
ASCII_TEXT = re.compile(r"[\x20-\x7e]*")
PHRASE = "COUPURE POSSIBLE"
STATE = Literal["started", "stopped", "enabled", "disabled", "ignored"]
INACTIVE_STATES = ("disabled", "ignored")
MIN_NODES = 3
RESOURCE_CLEARABLE = ("comment", "max_restart", "max_relocate", "failback")
RULE_CLEARABLE = ("comment", "disable", "strict")


def vmid_of(sid: str) -> int:
    return int(sid.split(":", 1)[1])


def gtype_of(sid: str) -> str:
    return "qemu" if sid.startswith("vm:") else "lxc"


def _comment(v):
    """Constaté en réel : Proxmox ALTÈRE les accents dans le commentaire d'une règle HA (« è » revient en U+FFFD). ASCII imprimable seulement."""
    if v is not None and not ASCII_TEXT.fullmatch(v):
        raise ValueError("Le commentaire HA ne peut contenir que des caractères ASCII imprimables (Proxmox altère les accents)")
    return v


class Locks(BaseModel):
    confirm: StrictBool = False
    acknowledge_live: StrictBool = False
    acknowledge_cut_access: StrictBool = False
    type_name: str | None = Field(default=None, max_length=40, description=f"« {PHRASE} » pour une opération à risque de coupure")
    dry_run: StrictBool = False


class ResourceFields(Locks):
    state: STATE | None = None
    max_restart: StrictInt | None = Field(default=None, ge=0, le=10)
    max_relocate: StrictInt | None = Field(default=None, ge=0, le=10)
    failback: StrictBool | None = None
    comment: str | None = Field(default=None, max_length=500)

    _c = field_validator("comment")(lambda cls, v: _comment(v))


class ResourceCreate(ResourceFields):
    sid: str = Field(pattern=SID.pattern, description="vm:ID ou ct:ID")


class ResourceUpdate(ResourceFields):
    clear: list[Literal["comment", "max_restart", "max_relocate", "failback"]] = Field(default=[], max_length=4)


class MoveBody(Locks):
    node: str = Field(pattern=NODE.pattern)


class NodeSel(BaseModel):
    node: str = Field(pattern=NODE.pattern)
    priority: StrictInt | None = Field(default=None, ge=0, le=1000)


class RuleFields(Locks):
    type: Literal["node-affinity", "resource-affinity"]
    resources: list[str] | None = Field(default=None, min_length=1, max_length=64)
    nodes: list[NodeSel] | None = Field(default=None, min_length=1, max_length=32)
    strict: StrictBool | None = None
    affinity: Literal["positive", "negative"] | None = None
    disable: StrictBool | None = None
    comment: str | None = Field(default=None, max_length=500)

    _c = field_validator("comment")(lambda cls, v: _comment(v))

    @field_validator("resources")
    @classmethod
    def _res(cls, v):
        if v is not None:
            if any(not SID.fullmatch(s) for s in v):
                raise ValueError("Identifiant de ressource invalide")
            if len(set(v)) != len(v):
                raise ValueError("Ressource en double")
        return v

    @field_validator("nodes")
    @classmethod
    def _nodes(cls, v):
        if v is not None and len({n.node for n in v}) != len(v):
            raise ValueError("Nœud en double")
        return v

    @model_validator(mode="after")
    def _by_type(self):
        if self.type == "resource-affinity" and (self.nodes is not None or self.strict is not None):
            raise ValueError("`nodes` et `strict` ne concernent que node-affinity")
        return self


class RuleCreate(RuleFields):
    rule: str = Field(pattern=RULE.pattern)

    @model_validator(mode="after")
    def _complete(self):
        if self.resources is None:
            raise ValueError("`resources` est obligatoire")
        if self.type == "node-affinity" and self.nodes is None:
            raise ValueError("`nodes` est obligatoire pour node-affinity")
        if self.type == "resource-affinity":
            if self.affinity is None:
                raise ValueError("`affinity` est obligatoire pour resource-affinity")
            if len(self.resources) < 2:
                raise ValueError("resource-affinity exige au moins deux ressources")
        return self


class RuleUpdate(RuleFields):
    clear: list[Literal["comment", "disable", "strict"]] = Field(default=[], max_length=3)


def _flag(v: bool) -> int:
    return 1 if v else 0


def build_resource(body: ResourceFields, clear: list[str]) -> tuple[dict, list[str]]:
    """`(paramètres Proxmox, réglages à retirer)` ; rien hors liste blanche n'est jamais envoyé."""
    p: dict = {}
    for k in ("state", "max_restart", "max_relocate", "comment"):
        v = getattr(body, k)
        if v is not None:
            p[k] = v
    if body.failback is not None:
        p["failback"] = _flag(body.failback)
    delete = list(dict.fromkeys(clear))
    if set(delete) & set(p):
        raise ValueError("Réglage à la fois modifié et retiré")
    return p, delete


def build_rule(body: RuleFields, clear: list[str]) -> tuple[dict, list[str]]:
    p: dict = {"type": body.type}
    if body.resources is not None:
        p["resources"] = ",".join(body.resources)
    if body.nodes is not None:
        p["nodes"] = ",".join(n.node if n.priority is None else f"{n.node}:{n.priority}" for n in body.nodes)
    for k in ("strict", "disable"):
        v = getattr(body, k)
        if v is not None:
            p[k] = _flag(v)
    if body.affinity is not None:
        p["affinity"] = body.affinity
    if body.comment is not None:
        p["comment"] = body.comment
    delete = list(dict.fromkeys(clear))
    if body.type == "resource-affinity" and "strict" in delete:
        raise ValueError("`strict` ne concerne que node-affinity")
    if set(delete) & set(p):
        raise ValueError("Réglage à la fois modifié et retiré")
    return p, delete


def protected_hits(sids: list[str], protected: set[int]) -> list[str]:
    return [s for s in sids if vmid_of(s) in protected]


def locks(action: str, n_nodes: int, *, existing: bool, activates: bool) -> dict:
    """Verrous d'après l'état relu. `action` : create | update | delete | migrate | relocate. `activates` : l'écriture active ou déplace de la HA.

    `cut` : raisons de coupure possible (phrase) ; `live` : raisons « effet immédiat » ; `inert` : rien de tout cela.
    """
    cut: list[str] = []
    live: list[str] = []
    if activates and n_nodes < MIN_NODES:
        cut.append(f"le cluster n'a que {n_nodes} nœud(s) (moins de {MIN_NODES}) : la HA arme un chien de garde ; si un nœud tombe, l'autre perd le quorum "
                   "et redémarre tout seul")
    if action in ("migrate", "relocate"):
        live.append("la machine est déplacée tout de suite par la HA" + (" (arrêt puis redémarrage pour un déplacement par relocalisation)" if action == "relocate" else ""))
    elif existing and action in ("update", "delete"):
        live.append("la HA gère déjà cette ressource : la modification s'applique tout de suite" if action == "update" else "la HA cessera de gérer cet élément")
    elif action == "create" and activates:
        live.append("la HA prend la main tout de suite sur ce qui est créé")
    if cut:
        live = live or ["la modification s'applique tout de suite"]
    return {"cut": cut, "live": live, "inert": not (cut or live)}
