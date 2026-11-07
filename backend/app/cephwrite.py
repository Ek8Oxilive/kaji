"""Ceph, ÉCRITURE : pools (lot C2 de `docs/m12-ceph.md`). Validation stricte, garde-fous, verrou.

Une erreur sur Ceph détruit les données de TOUTES les machines d'un pool. Les règles du cadrage (§3) sont donc appliquées ici
et vérifiées côté serveur : redondance minimale, champs en liste blanche, barrière de santé, confirmation, une seule écriture
à la fois. Rien de tout cela n'a été validé sur un vrai Ceph (le cluster de test n'en a pas).

Les noms et bornes des paramètres viennent de la documentation officielle de `pveceph pool create` et `pveceph pool set`.
"""
import contextlib
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

# Nom de pool : plus strict que Proxmox (`^[^:/\s]+$`). Jamais de point initial : les pools internes de Ceph (`.mgr`)
# commencent par un point et ne doivent pas être touchés.
POOL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,62}")
RULE_NAME = POOL_NAME
MIN_COPIES = 2                      # refus de `size` inférieur à 2 et de `min_size` à 1 (cadrage §3, règle 3)
MAX_COPIES = 7                      # borne de Proxmox
MAX_PG = 32768                      # borne de Proxmox

Autoscale = Literal["on", "off", "warn"]
Application = Literal["rbd", "cephfs", "rgw"]


def _power_of_two(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0


class _PoolFields(BaseModel):
    @field_validator("pg_num", check_fields=False)
    @classmethod
    def _pg(cls, v):
        if v is not None and not _power_of_two(v):
            raise ValueError("pg_num doit être une puissance de 2")
        return v

    @field_validator("crush_rule", check_fields=False)
    @classmethod
    def _rule(cls, v):
        if v is not None and not RULE_NAME.fullmatch(v):
            raise ValueError("Nom de règle CRUSH invalide")
        return v


class PoolCreate(_PoolFields):
    """Seuls ces champs existent : tout autre champ est ignoré et jamais transmis à Proxmox."""
    name: str
    size: int = Field(default=3, ge=MIN_COPIES, le=MAX_COPIES)
    min_size: int = Field(default=2, ge=MIN_COPIES, le=MAX_COPIES)
    pg_num: int = Field(default=128, ge=1, le=MAX_PG)
    autoscale: Autoscale = "warn"
    application: Application = "rbd"
    crush_rule: str | None = None
    add_storage: bool = False          # crée aussi le stockage RBD (cluster entier) : seulement pour l'application `rbd`
    confirm: bool = False              # jamais transmis à Proxmox : le serveur décide quand il est exigé (create_risks)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if not POOL_NAME.fullmatch(v):
            raise ValueError("Nom de pool invalide")
        return v

    @model_validator(mode="after")
    def _coherent(self):
        if self.min_size > self.size:
            raise ValueError("min_size ne peut pas dépasser size")
        if self.add_storage and self.application != "rbd":
            raise ValueError("Le stockage associé n'existe que pour l'application rbd")
        return self


class PoolUpdate(_PoolFields):
    """Mise à jour partielle : seuls les champs fournis changent (et seulement s'ils diffèrent de l'existant)."""
    size: int | None = Field(default=None, ge=MIN_COPIES, le=MAX_COPIES)
    min_size: int | None = Field(default=None, ge=MIN_COPIES, le=MAX_COPIES)
    pg_num: int | None = Field(default=None, ge=1, le=MAX_PG)
    autoscale: Autoscale | None = None
    application: Application | None = None
    crush_rule: str | None = None
    confirm: bool = False

    @model_validator(mode="after")
    def _partial(self):
        given = self.model_fields_set - {"confirm"}
        if not given:
            raise ValueError("Aucune modification demandée")
        for k in given:
            if getattr(self, k) is None:
                raise ValueError(f"{k} ne peut pas être null")
        return self


PROXMOX_NAME = {"autoscale": "pg_autoscale_mode"}
RISKY = ("size", "min_size", "pg_num", "crush_rule")      # déplacent ou dupliquent des données : santé et confirmation exigées


def create_params(b: PoolCreate) -> dict:
    p: dict = {"name": b.name, "size": b.size, "min_size": b.min_size, "pg_num": b.pg_num, "pg_autoscale_mode": b.autoscale,
               "application": b.application, "add_storages": 1 if b.add_storage else 0}
    if b.crush_rule:
        p["crush_rule"] = b.crush_rule
    return p


def update_params(changes: dict) -> dict:
    return {PROXMOX_NAME.get(k, k): v for k, v in changes.items()}


def changes_of(b: PoolUpdate, current: dict) -> dict:
    """Les champs demandés qui diffèrent réellement de l'existant. Une valeur identique n'est jamais renvoyée."""
    cur = {"size": current.get("size"), "min_size": current.get("min_size"), "pg_num": current.get("pg_num"),
           "autoscale": current.get("autoscale"), "crush_rule": current.get("crush_rule"),
           "application": (current.get("applications") or [None])[0] if len(current.get("applications") or []) == 1 else None}
    return {k: getattr(b, k) for k in b.model_fields_set - {"confirm"} if getattr(b, k) != cur.get(k)}


def create_risks(b: PoolCreate) -> list[str]:
    """Pourquoi la CRÉATION demande une confirmation (le serveur décide, l'interface ne fait que relayer)."""
    risks = []
    if b.size == MIN_COPIES:
        risks.append(f"ce pool n'aura que {MIN_COPIES} copies des données : la perte de deux disques (ou d'un nœud et d'un disque) fera perdre des données, "
                     "surtout sur un cluster de 3 nœuds ou plus")
    if b.add_storage:
        risks.append("le stockage RBD associé sera créé pour TOUT le cluster (visible sur tous les nœuds)")
    return risks


def update_risks(changes: dict, current: dict) -> list[str]:
    """Pourquoi la modification demande une confirmation : dit ce que Ceph va faire, avec les valeurs avant et après."""
    risks = []
    if "size" in changes:
        a, b = current.get("size"), changes["size"]
        risks.append(f"cette modification RÉDUIT le nombre de copies (de {a} à {b}) : la panne de disques fera perdre plus facilement des données"
                     if a is not None and b < a else f"cette modification AJOUTE des copies (de {a} à {b}) : Ceph va copier les données, avec une charge importante sur les disques et le réseau")
    if "min_size" in changes:
        a, b = current.get("min_size"), changes["min_size"]
        risks.append(f"cette modification RÉDUIT min_size (de {a} à {b}) : Ceph acceptera d'écrire avec moins de copies disponibles"
                     if a is not None and b < a else f"cette modification AUGMENTE min_size (de {a} à {b}) : les écritures seront bloquées s'il reste moins de {b} copies")
    if "pg_num" in changes:
        risks.append(f"cette modification change le nombre de groupes de placement (de {current.get('pg_num')} à {changes['pg_num']}) : Ceph va redistribuer des données")
    if "crush_rule" in changes:
        risks.append(f"cette modification change la règle de placement (de {current.get('crush_rule')} à {changes['crush_rule']}) : Ceph va déplacer les données")
    return risks


# ------------------------------------------------------------------ une seule écriture à la fois

_BUSY: set[int] = set()


@contextlib.contextmanager
def write_slot(conn_id: int):
    """Une seule écriture Ceph à la fois par connexion (cadrage §3, règle 6). Le test et la prise du verrou se font sans
    `await` entre les deux : deux requêtes ne peuvent pas passer ensemble. La tâche Proxmox lancée peut durer plus longtemps
    que ce verrou ; c'est la barrière de santé qui empêche d'enchaîner une seconde modification risquée pendant ce temps."""
    if conn_id in _BUSY:
        raise HTTPException(409, "Une autre écriture Ceph est déjà en cours pour ce cluster : attends sa fin")
    _BUSY.add(conn_id)
    try:
        yield
    finally:
        _BUSY.discard(conn_id)
