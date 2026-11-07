"""Configuration d'un stockage Proxmox (`/storage`) : ajouter, modifier, supprimer. Tout est validé, rien n'est transmis tel quel.

Principe : une table par type de stockage (`TYPES`) liste les champs acceptés, séparés en
- champs de **création seulement** (serveur NFS, volume group, pool ZFS… : Proxmox les refuse en modification) ;
- champs **modifiables**.
Un champ qui ne concerne pas le type, ou qui n'est pas modifiable, est **refusé** (422) au lieu d'être ignoré en silence.
Les secrets (mot de passe CIFS, keyring Ceph) ne sont jamais renvoyés ni journalisés : l'audit dit seulement « défini ».
Le type `pbs` est volontairement absent (lot suivant : sa clé de chiffrement est affichée une seule fois par Proxmox).
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

from .vmspec import STORAGE

NODE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9\-]{0,62})")
HOST = re.compile(r"[A-Za-z0-9\[\]]([A-Za-z0-9.:\[\]\-]{0,251}[A-Za-z0-9\]])?")
EXPORT = re.compile(r"/[A-Za-z0-9._@+/\-]{0,200}")                     # chemin absolu, sans espace
SHARE = re.compile(r"[A-Za-z0-9._$\-]{1,80}")
LVNAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._+\-]{0,63}")
ZPOOL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._+/\-]{0,127}")
USER = re.compile(r"[A-Za-z0-9._@!\-]{1,64}")
WORD = re.compile(r"[A-Za-z0-9._\-]{1,64}")
IQN = re.compile(r"[A-Za-z0-9.:_\-]{1,223}")
MOUNT_OPTS = re.compile(r"[A-Za-z0-9=,._\-]{1,200}")
DIGEST = re.compile(r"[0-9a-f]{40}")
KEYRING_CHARS = re.compile(r"[A-Za-z0-9+/=\[\]._\- \r\n]{1,2000}")

Content = Literal["images", "rootdir", "iso", "vztmpl", "backup", "snippets", "import"]
# Contenus que Proxmox accepte selon le type (les autres sont refusés ici avant l'appel).
CONTENTS: dict[str, tuple[str, ...]] = {
    "dir": ("images", "rootdir", "iso", "vztmpl", "backup", "snippets", "import"),
    "nfs": ("images", "rootdir", "iso", "vztmpl", "backup", "snippets", "import"),
    "cifs": ("images", "rootdir", "iso", "vztmpl", "backup", "snippets", "import"),
    "cephfs": ("iso", "vztmpl", "backup", "snippets"),
    "lvm": ("images", "rootdir"),
    "lvmthin": ("images", "rootdir"),
    "zfspool": ("images", "rootdir"),
    "rbd": ("images", "rootdir"),
    "iscsi": ("images",),
}

# type -> (champs de création seulement, champs modifiables)
TYPES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "dir": (frozenset({"path", "create_base_path"}),
            frozenset({"content", "nodes", "disable", "shared", "prune_backups", "max_protected_backups"})),
    "nfs": (frozenset({"server", "export"}),
            frozenset({"content", "nodes", "disable", "options", "prune_backups", "max_protected_backups"})),
    "cifs": (frozenset({"server", "share"}),
             frozenset({"content", "nodes", "disable", "username", "password", "domain", "smbversion", "subdir", "options",
                        "prune_backups", "max_protected_backups"})),
    "lvm": (frozenset({"vgname"}), frozenset({"content", "nodes", "disable", "shared", "saferemove"})),
    "lvmthin": (frozenset({"vgname", "thinpool"}), frozenset({"content", "nodes", "disable"})),
    "zfspool": (frozenset({"pool"}), frozenset({"content", "nodes", "disable", "blocksize", "sparse", "mountpoint"})),
    "iscsi": (frozenset({"portal", "target"}), frozenset({"content", "nodes", "disable"})),
    "cephfs": (frozenset(), frozenset({"content", "nodes", "disable", "monhost", "username", "fs_name", "subdir", "fuse", "keyring",
                                       "prune_backups", "max_protected_backups"})),
    "rbd": (frozenset({"pool"}), frozenset({"content", "nodes", "disable", "monhost", "username", "krbd", "keyring", "namespace"})),
}
StorageType = Literal["dir", "nfs", "cifs", "lvm", "lvmthin", "zfspool", "iscsi", "cephfs", "rbd"]
# Réglages qu'on peut retirer d'un stockage (« delete » de Proxmox) ; seulement ceux du type.
RESETTABLE = frozenset({"nodes", "options", "prune_backups", "domain", "subdir", "max_protected_backups", "namespace"})
SECRETS = frozenset({"password", "keyring"})
# Nom Python -> nom du paramètre Proxmox.
WIRE = {"create_base_path": "create-base-path", "prune_backups": "prune-backups", "max_protected_backups": "max-protected-backups",
        "fs_name": "fs-name"}
BOOLS = frozenset({"disable", "shared", "saferemove", "sparse", "fuse", "krbd", "create_base_path"})
PRUNE_KEYS = ("keep_last", "keep_hourly", "keep_daily", "keep_weekly", "keep_monthly", "keep_yearly")


class Prune(BaseModel):
    """Conservation des sauvegardes (`prune-backups`). `keep_all` exclut toutes les autres règles."""
    keep_all: bool = False
    keep_last: int | None = Field(default=None, ge=1, le=9999)
    keep_hourly: int | None = Field(default=None, ge=1, le=9999)
    keep_daily: int | None = Field(default=None, ge=1, le=9999)
    keep_weekly: int | None = Field(default=None, ge=1, le=9999)
    keep_monthly: int | None = Field(default=None, ge=1, le=9999)
    keep_yearly: int | None = Field(default=None, ge=1, le=9999)

    def wire(self) -> str:
        if self.keep_all:
            if any(getattr(self, k) is not None for k in PRUNE_KEYS):
                raise ValueError("keep_all exclut les autres règles de conservation")
            return "keep-all=1"
        parts = [f"{k.replace('_', '-')}={getattr(self, k)}" for k in PRUNE_KEYS if getattr(self, k) is not None]
        if not parts:
            raise ValueError("Aucune règle de conservation")
        return ",".join(parts)


def _match(rx: re.Pattern, v: str, what: str) -> str:
    if not isinstance(v, str) or not rx.fullmatch(v):
        raise ValueError(f"{what} invalide")
    return v


def _path(v: str, what: str) -> str:
    _match(EXPORT, v, what)
    if any(seg == ".." for seg in v.split("/")) or "//" in v:
        raise ValueError(f"{what} invalide")
    return v


class StorageFields(BaseModel):
    """Tous les champs possibles, tous facultatifs ; `check()` applique la table du type."""
    content: list[Content] | None = Field(default=None, max_length=7)
    nodes: list[str] | None = Field(default=None, max_length=64)
    disable: bool | None = None
    shared: bool | None = None
    prune_backups: Prune | None = None
    max_protected_backups: int | None = Field(default=None, ge=-1, le=1000000)
    path: str | None = None
    create_base_path: bool | None = None
    server: str | None = None
    export: str | None = None
    share: str | None = None
    options: str | None = None
    username: str | None = None
    password: SecretStr | None = Field(default=None, max_length=200)
    domain: str | None = None
    smbversion: Literal["default", "2.0", "2.1", "3", "3.0", "3.11"] | None = None
    subdir: str | None = None
    vgname: str | None = None
    thinpool: str | None = None
    saferemove: bool | None = None
    pool: str | None = None
    blocksize: Literal["4k", "8k", "16k", "32k", "64k", "128k"] | None = None
    sparse: bool | None = None
    mountpoint: str | None = None
    portal: str | None = None
    target: str | None = None
    monhost: list[str] | None = Field(default=None, max_length=8)
    fs_name: str | None = None
    fuse: bool | None = None
    keyring: SecretStr | None = Field(default=None, max_length=2000)
    krbd: bool | None = None
    namespace: str | None = None

    @field_validator("nodes")
    @classmethod
    def _nodes(cls, v):
        return None if v is None else [_match(NODE, n, "Nom de nœud") for n in v]

    @field_validator("monhost")
    @classmethod
    def _mon(cls, v):
        return None if v is None else [_match(HOST, h, "Moniteur") for h in v]

    @field_validator("path", "export", "mountpoint")
    @classmethod
    def _paths(cls, v):
        return None if v is None else _path(v, "Chemin")

    @field_validator("subdir")
    @classmethod
    def _subdir(cls, v):
        return None if v is None else _path(v, "Sous-dossier")


FIELD_RULES: dict[str, tuple[re.Pattern, str]] = {
    "server": (HOST, "Serveur"), "share": (SHARE, "Partage"), "options": (MOUNT_OPTS, "Options de montage"),
    "username": (USER, "Utilisateur"), "domain": (WORD, "Domaine"), "vgname": (LVNAME, "Groupe de volumes"),
    "thinpool": (LVNAME, "Pool thin"), "pool": (ZPOOL, "Pool"), "portal": (HOST, "Portail"), "target": (IQN, "Cible iSCSI"),
    "fs_name": (WORD, "Système de fichiers Ceph"), "namespace": (WORD, "Espace de noms"),
}


def check(stype: str, body: StorageFields, *, creating: bool, sent: set[str]) -> dict[str, str]:
    """Valide `body` pour ce type et renvoie les paramètres Proxmox (chaînes). `sent` = champs réellement fournis par l'appelant.

    Lève `ValueError` (message sans valeur saisie) si un champ ne concerne pas le type, n'est pas modifiable, ou est invalide."""
    if stype not in TYPES:
        raise ValueError("Type de stockage non géré")
    create_only, editable = TYPES[stype]
    allowed = create_only | editable if creating else editable
    for f in sorted(sent):
        if f not in allowed:
            raise ValueError(f"Champ « {f} » " + ("non modifiable après la création" if f in create_only else f"inutile pour un stockage {stype}"))
    out: dict[str, str] = {}
    for f in sent:
        v = getattr(body, f)
        if v is None:
            raise ValueError(f"Champ « {f} » vide")
        if f in FIELD_RULES:
            _match(FIELD_RULES[f][0], v, FIELD_RULES[f][1])
        if f == "content":
            bad = [c for c in v if c not in CONTENTS[stype]]
            if bad or not v:
                raise ValueError(f"Contenu non géré par un stockage {stype} : {', '.join(bad) or 'liste vide'}")
            out["content"] = ",".join(c for c in CONTENTS[stype] if c in v)
        elif f == "nodes":
            if not v:
                raise ValueError("Liste de nœuds vide : utilise « reset » pour retirer la restriction")
            out["nodes"] = ",".join(sorted(set(v)))
        elif f == "monhost":
            if not v:
                raise ValueError("Liste de moniteurs vide")
            out["monhost"] = ",".join(v)
        elif f == "prune_backups":
            out["prune-backups"] = v.wire()
        elif f in SECRETS:
            out[f] = v.get_secret_value()
            if f == "keyring" and not KEYRING_CHARS.fullmatch(out[f]):
                raise ValueError("Keyring invalide")
            if f == "password" and (not out[f] or "\n" in out[f] or "\r" in out[f]):
                raise ValueError("Mot de passe invalide")
        elif f in BOOLS:
            out[WIRE.get(f, f)] = "1" if v else "0"
        else:
            out[WIRE.get(f, f)] = str(v)
    if creating:
        need = {"dir": ("path",), "nfs": ("server", "export"), "cifs": ("server", "share"), "lvm": ("vgname",),
                "lvmthin": ("vgname", "thinpool"), "zfspool": ("pool",), "iscsi": ("portal", "target"),
                "cephfs": ("monhost",), "rbd": ("pool", "monhost")}[stype]
        missing = [n for n in need if n not in sent]
        if missing:
            raise ValueError("Champs obligatoires manquants : " + ", ".join(missing))
    return out


def reset_keys(stype: str, names: list[str]) -> str:
    """Valeur du paramètre `delete` de Proxmox pour retirer des réglages (liste blanche, limitée aux champs modifiables du type)."""
    editable = TYPES[stype][1]
    bad = [n for n in names if n not in RESETTABLE or n not in editable]
    if bad:
        raise ValueError("Réglage non retirable : " + ", ".join(bad))
    return ",".join(WIRE.get(n, n) for n in sorted(set(names)))


# --------------------------------------------------------------------------- lecture
def _list(v) -> list[str]:
    return [x for x in v.replace(";", ",").replace(" ", ",").split(",") if x] if isinstance(v, str) else []


def shape_config(raw) -> dict | None:
    """Configuration d'un stockage telle que Proxmox la renvoie, en liste blanche. Aucun secret : Proxmox n'en renvoie pas, et
    on ne reprend de toute façon que les champs connus (`password` et `keyring` sont signalés « définis » ailleurs)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("storage"), str) or not STORAGE.fullmatch(raw["storage"]):
        return None
    stype = raw.get("type")
    if stype not in TYPES:
        return {"storage": raw["storage"], "type": stype if isinstance(stype, str) else None, "managed": False}
    create_only, editable = TYPES[stype]
    out: dict = {"storage": raw["storage"], "type": stype, "managed": True,
                 "digest": raw["digest"] if isinstance(raw.get("digest"), str) and DIGEST.fullmatch(raw["digest"]) else None}
    for f in sorted((create_only | editable) - SECRETS):
        v = raw.get(WIRE.get(f, f))
        if v is None:
            continue
        if f in ("content", "nodes", "monhost"):
            out[f] = _list(v)
        elif f in BOOLS:
            out[f] = v in (1, "1", True)
        elif f == "max_protected_backups":
            out[f] = v if isinstance(v, int) and not isinstance(v, bool) else None
        elif isinstance(v, str):
            out[f] = v[:300]
    out["secrets_set"] = [s for s in sorted(SECRETS & (create_only | editable)) if raw.get(s) not in (None, "")]
    return out
