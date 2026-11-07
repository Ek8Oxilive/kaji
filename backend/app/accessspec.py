"""Accès Proxmox en lecture seule : utilisateurs, rôles, ACL, realms et « droits de Kaji ».

Tout est tolérant aux données illisibles. Règle de prudence : **« ok » n'est jamais affiché par défaut**. Une fonction n'est
« ok » que si Proxmox a répondu et que chaque privilège nécessaire est explicitement accordé ; une réponse absente ou
illisible donne « inconnu », jamais « ok ».
"""
from dataclasses import dataclass

from .storagespec import _int, _str


def _text_list(v) -> list[str]:
    """`"a,b"` -> `["a", "b"]` ; autre chose qu'un texte -> `[]`."""
    return [x for x in (p.strip() for p in v.split(",")) if x] if isinstance(v, str) else []


def _rows(data) -> list[dict]:
    return [r for r in (data if isinstance(data, list) else []) if isinstance(r, dict)]


def shape_users(data) -> list[dict]:
    out = []
    for r in _rows(data):
        uid = _str(r.get("userid"))
        if not uid:
            continue
        exp = _int(r.get("expire"))
        out.append({"userid": uid, "realm": uid.rpartition("@")[2] or None, "realm_type": _str(r.get("realm-type")),
                    "enabled": _int(r.get("enable")) != 0, "expire": exp if exp else None})
    return sorted(out, key=lambda u: u["userid"])


def shape_groups(data) -> list[dict]:
    out = [{"groupid": g, "comment": _str(r.get("comment")), "users": _text_list(r.get("users"))}
           for r in _rows(data) if (g := _str(r.get("groupid")))]
    return sorted(out, key=lambda g: g["groupid"])


def shape_roles(data) -> list[dict]:
    out = [{"roleid": rid, "special": _int(r.get("special")) == 1, "privs": sorted(_text_list(r.get("privs")))}
           for r in _rows(data) if (rid := _str(r.get("roleid")))]
    return sorted(out, key=lambda r: r["roleid"])


def shape_acl(data) -> list[dict]:
    out = []
    for r in _rows(data):
        path, role, ugid = _str(r.get("path")), _str(r.get("roleid")), _str(r.get("ugid"))
        if not (path and role and ugid):
            continue
        out.append({"path": path, "type": _str(r.get("type")), "ugid": ugid, "roleid": role,
                    "propagate": _int(r.get("propagate")) == 1})
    return sorted(out, key=lambda a: (a["path"], a["ugid"], a["roleid"]))


def shape_realms(data) -> list[dict]:
    out = [{"realm": rl, "type": _str(r.get("type")), "comment": _str(r.get("comment"))}
           for r in _rows(data) if (rl := _str(r.get("realm")))]
    return sorted(out, key=lambda r: r["realm"])


# ------------------------------------------------------------------ droits de Kaji

@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    needs: tuple[tuple[str, tuple[str, ...]], ...]   # (chemin, privilèges tous nécessaires)


# Indicatif : privilèges que la fonction demande d'après la documentation de Proxmox (et, pour les jobs, ce qui a été constaté
# en réel). Un cas particulier peut en demander d'autres ; la page le dit.
FEATURES: tuple[Feature, ...] = (
    Feature("view", "Voir le cluster, les nœuds et les machines", (("/", ("Sys.Audit", "VM.Audit")),)),
    Feature("storage-view", "Voir les stockages et leur contenu", (("/storage", ("Datastore.Audit",)),)),
    Feature("pools", "Voir les pools", (("/pool", ("Pool.Audit",)),)),
    Feature("power", "Démarrer, éteindre, redémarrer une machine", (("/vms", ("VM.PowerMgmt",)),)),
    Feature("create", "Créer ou supprimer une machine", (("/vms", ("VM.Allocate",)),)),
    Feature("hardware", "Modifier le matériel d'une machine",
            (("/vms", ("VM.Config.CPU", "VM.Config.Memory", "VM.Config.Disk", "VM.Config.Network", "VM.Config.Options")),)),
    Feature("snapshot", "Créer, restaurer ou supprimer un snapshot", (("/vms", ("VM.Snapshot", "VM.Snapshot.Rollback")),)),
    Feature("clone", "Cloner une machine", (("/vms", ("VM.Clone",)),)),
    Feature("migrate", "Migrer une machine", (("/vms", ("VM.Migrate",)),)),
    Feature("backup", "Lancer une sauvegarde",
            (("/vms", ("VM.Backup",)), ("/storage", ("Datastore.AllocateSpace",)))),
    Feature("restore", "Restaurer une sauvegarde vers une nouvelle machine",
            (("/vms", ("VM.Allocate",)), ("/storage", ("Datastore.AllocateSpace",)))),
    Feature("backup-jobs", "Gérer les sauvegardes planifiées", (("/", ("Sys.Modify",)),)),
    Feature("network", "Ajouter une carte réseau sur un bridge ou un VNet", (("/sdn/zones", ("SDN.Use",)),)),
)


def needed_paths() -> list[str]:
    """Chemins à interroger (constantes : aucune saisie n'entre dans l'appel à Proxmox)."""
    return sorted({path for f in FEATURES for path, _ in f.needs})


def granted(perms) -> set[str] | None:
    """Privilèges accordés sur un chemin : `{"VM.Audit": 1, ...}` -> `{"VM.Audit"}`. `None` si la réponse est illisible.
    Seule la valeur `1` compte comme accordée."""
    if not isinstance(perms, dict):
        return None
    return {k for k, v in perms.items() if isinstance(k, str) and not isinstance(v, bool) and v == 1}


def check_features(perms_by_path: dict[str, set[str] | None]) -> list[dict]:
    """`ok` : tous les privilèges sont accordés. `missing` : au moins un manque sur un chemin lu avec succès.
    `unknown` : un chemin n'a pas pu être lu, et rien ne prouve un manque. Jamais `ok` sans preuve."""
    out = []
    for f in FEATURES:
        missing, unknown = [], False
        for path, privs in f.needs:
            have = perms_by_path.get(path)
            if have is None:
                unknown = True
                continue
            missing += [{"path": path, "privilege": p} for p in privs if p not in have]
        status = "missing" if missing else "unknown" if unknown else "ok"
        out.append({"id": f.id, "label": f.label, "status": status, "missing": missing})
    return out
