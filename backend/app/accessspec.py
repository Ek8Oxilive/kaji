"""Accès Proxmox en lecture seule : utilisateurs, rôles, ACL, realms et « droits de Kaji ».

Tout est tolérant aux données illisibles. Règle de prudence : **« ok » n'est jamais affiché par défaut**. Une fonction n'est
« ok » que si Proxmox a répondu et que chaque privilège nécessaire est explicitement accordé ; une réponse absente ou
illisible donne « inconnu », jamais « ok ».
"""
import re
import shlex
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
    Feature("node-console", "Ouvrir la console (shell) d'un nœud", (("/nodes", ("Sys.Console",)),)),
    Feature("ha-write", "Gérer la haute disponibilité (ressources, règles, migrer, relocaliser)", (("/", ("Sys.Console",)),)),
    Feature("replication-write", "Gérer les jobs de réplication (créer, modifier, supprimer, lancer)", (("/vms", ("VM.Replicate",)),)),
    Feature("node-syslog", "Lire le journal système d'un nœud", (("/nodes", ("Sys.Syslog",)),)),
    Feature("node-updates", "Voir et rafraîchir les mises à jour disponibles d'un nœud", (("/nodes", ("Sys.Modify",)),)),
    Feature("node-services", "Démarrer, arrêter ou redémarrer un service d'un nœud", (("/nodes", ("Sys.Modify",)),)),
    Feature("node-power", "Redémarrer ou éteindre un nœud", (("/nodes", ("Sys.PowerMgmt",)),)),
    Feature("node-disks-write", "Initialiser, effacer un disque et créer un volume (LVM, LVM-thin, répertoire, ZFS)", (("/nodes", ("Sys.Modify",)), ("/storage", ("Datastore.Allocate",)))),
    Feature("node-config", "Modifier le DNS, le fichier hosts et le fuseau horaire d'un nœud", (("/nodes", ("Sys.Modify",)),)),
    Feature("node-certs", "Installer ou retirer un certificat personnalisé sur un nœud", (("/nodes", ("Sys.Modify",)),)),
    Feature("node-repos", "Activer, désactiver ou ajouter un dépôt de paquets d'un nœud", (("/nodes", ("Sys.Modify",)),)),
    Feature("acme", "Gérer les certificats ACME (comptes, domaines, commande)", (("/nodes", ("Sys.Modify",)), ("/", ("Sys.Modify",)))),
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


# ------------------------------------------------------------------ commandes de correction (jamais exécutées)

# Privilèges qui permettent de gérer les droits eux-mêmes : une commande de correction n'en contient JAMAIS (cadrage
# `docs/m6-ecriture.md`). Garde-fou en plus de la liste `FEATURES`, qui n'en contient aucun.
FORBIDDEN_PRIVS = frozenset({"Permissions.Modify", "User.Modify", "Group.Allocate", "Realm.Allocate", "Realm.AllocateUser"})
FIX_USER = re.compile(r"[A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32}")   # utilisateur de la connexion : `fullmatch`
_SLUG = re.compile(r"[^A-Za-z0-9]+")


def _role_name(feature_id: str, path: str, several_paths: bool) -> str:
    return f"Kaji-{feature_id}" + (f"-{_SLUG.sub('-', path).strip('-') or 'racine'}" if several_paths else "")


def build_fixes(features: list[dict], user: str, existing_roles: set[str] | None) -> list[dict]:
    """Pour chaque fonction dont un droit manque : les commandes `pveum` à lancer **en root sur un nœud**. Kaji n'exécute
    rien. Tout vient de constantes (chemins et privilèges de `FEATURES`) et de `user`, vérifié par `FIX_USER`
    (sinon aucune commande n'est produite). `existing_roles` : rôles connus de Proxmox (`None` : illisible, on propose
    la création)."""
    safe_user = bool(FIX_USER.fullmatch(user or ""))
    out = []
    for f in features:
        if f.get("status") != "missing":
            continue
        by_path: dict[str, list[str]] = {}
        for m in f.get("missing", []):
            by_path.setdefault(m["path"], []).append(m["privilege"])
        entry = {"id": f["id"], "label": f["label"], "commands": [], "error": None}
        privs_all = {p for ps in by_path.values() for p in ps}
        if not safe_user:
            entry["error"] = "Utilisateur de la connexion non reconnu : aucune commande n'est proposée."
        elif privs_all & FORBIDDEN_PRIVS:
            entry["error"] = "Privilège d'administration des droits : à accorder dans Proxmox, jamais proposé par Kaji."
        else:
            for path, privs in sorted(by_path.items()):
                role = _role_name(f["id"], path, len(by_path) > 1)
                plist = ",".join(sorted(set(privs)))
                if existing_roles is not None and role in existing_roles:
                    entry["commands"].append(f"pveum role modify {shlex.quote(role)} -privs {shlex.quote(plist)} -append 1")
                else:
                    entry["commands"].append(f"pveum role add {shlex.quote(role)} -privs {shlex.quote(plist)}")
                entry["commands"].append(f"pveum aclmod {shlex.quote(path)} -user {shlex.quote(user)} -role {shlex.quote(role)}")
        out.append(entry)
    return out
