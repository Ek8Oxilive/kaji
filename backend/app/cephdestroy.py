"""Ceph, DESTRUCTION (lot C4 de `docs/m12-ceph.md`) : règles pures, sans réseau. Pool, OSD, moniteur, gestionnaire, MDS.

Chaque règle renvoie `(blockers, risks)` :
- `blockers` : refus que **rien ne lève** (même avec `confirm`) : une dépendance existe, la santé n'est pas bonne, le quorum ou la disponibilité des données serait perdu ;
- `risks` : ce que la destruction fait, dit en clair ; l'écriture exige `confirm=true` ET le **nom exact retapé** (`name`).
`dry_run=true` renvoie les deux listes sans rien écrire. L'option `force` de Proxmox (détruire un pool « même utilisé ») n'est JAMAIS exposée.

Hypothèse assumée (comme en C3) : le domaine de panne est l'HÔTE (règle CRUSH par défaut). RIEN de tout cela n'a été validé sur un vrai Ceph.
CephFS : le schéma de Proxmox 9 n'a pas de `DELETE` pour un CephFS (seulement la création) : il se détruit en ligne de commande.
"""
from .cephservices import RUNNING_MGR

MAX_LISTED = 20
SYSTEM_POOL_PREFIX = "."                       # `.mgr` : pool interne du gestionnaire


def _names(items: list[str]) -> str:
    return ", ".join(items[:MAX_LISTED]) + ("…" if len(items) > MAX_LISTED else "")


def pool_plan(pool: dict, health: str, filesystems: list[dict], storages: list[dict], volumes: dict[str, list[dict] | None], remove_storages: bool) -> tuple[list[str], list[str]]:
    """Détruire un pool. `storages` : stockages Proxmox (type rbd) qui utilisent ce pool ; `volumes` : `{stockage: volumes}` (`None` = illisible)."""
    name = pool["name"]
    blockers: list[str] = []
    if name.startswith(SYSTEM_POOL_PREFIX):
        blockers.append(f"« {name} » est un pool interne de Ceph : il ne se détruit pas depuis Kaji")
    if health != "HEALTH_OK":
        blockers.append(f"la santé n'est pas HEALTH_OK (actuellement {health})")
    used_by_fs = sorted(f["name"] for f in filesystems if name == f["metadata_pool"] or name in f["data_pools"])
    if used_by_fs:
        blockers.append(f"ce pool est utilisé par le CephFS {_names(used_by_fs)} : détruis d'abord le système de fichiers (ligne de commande : Proxmox n'a pas d'API pour cela)")
    for storage, vols in sorted(volumes.items()):
        if vols is None:
            blockers.append(f"impossible de lister le contenu du stockage « {storage} » : Kaji refuse de détruire sans savoir ce qu'il contient")
        elif vols:
            vm = sorted({str(v["vmid"]) for v in vols if v.get("vmid") is not None})
            blockers.append(f"le stockage « {storage} » contient {len(vols)} volume(s)" + (f" (machines {_names(vm)})" if vm else "") + " : supprime-les ou déplace-les d'abord")
    risks = [f"le pool « {name} » et TOUTES ses données seront détruits, sans retour possible"]
    if pool.get("used"):
        risks.append(f"il contient environ {pool['used'] // 2**20} Mio de données")
    if storages:
        if remove_storages:
            risks.append(f"le(s) stockage(s) {_names(sorted(s['storage'] for s in storages))} sera/seront retiré(s) de TOUT le cluster (remove_storages)")
        else:
            blockers.append(f"le(s) stockage(s) {_names(sorted(s['storage'] for s in storages))} utilisent ce pool : renvoie la requête avec remove_storages=true pour les retirer avec lui")
    return blockers, risks


def osd_plan(target: dict, health: str, pgs_clean: bool, cleanup: bool) -> tuple[list[str], list[str]]:
    """Détruire un OSD : il doit être DEHORS et ARRÊTÉ, ne plus porter aucun groupe de placement, et Ceph doit être sain et propre."""
    blockers: list[str] = []
    if target["in"] is not False:
        blockers.append("l'OSD est encore DEDANS : mets-le dehors d'abord et attends que Ceph ait déplacé ses données")
    if target["up"] is not False:
        blockers.append("l'OSD tourne encore : arrête-le d'abord")
    if target["pgs"] is None:
        blockers.append("le nombre de groupes de placement de l'OSD est illisible")
    elif target["pgs"] > 0:
        blockers.append(f"l'OSD porte encore {target['pgs']} groupe(s) de placement : ses données ne sont pas évacuées")
    if health != "HEALTH_OK":
        blockers.append(f"la santé n'est pas HEALTH_OK (actuellement {health})")
    elif not pgs_clean:
        blockers.append("tous les groupes de placement ne sont pas « active+clean » : Ceph n'a pas fini de rééquilibrer")
    risks = [f"l'OSD {target['name']} sera DÉTRUIT : il disparaît de la carte CRUSH et son volume est supprimé"]
    if cleanup:
        risks.append("cleanup : la table de partitions du disque est EFFACÉE (le disque devient inutilisable sans reformatage)")
    return blockers, risks


def mon_plan(target: dict, mons: list[dict], health: str, mgr_here_is_last: bool) -> tuple[list[str], list[str]]:
    """Détruire un moniteur (Proxmox détruit aussi le gestionnaire du même nom). Refusé s'il est le dernier ou si le quorum serait perdu."""
    blockers: list[str] = []
    if len(mons) <= 1:
        blockers.append("c'est le DERNIER moniteur : le détruire détruit le cluster Ceph lui-même")
    if health != "HEALTH_OK":
        blockers.append(f"la santé n'est pas HEALTH_OK (actuellement {health})")
    if any(m["in_quorum"] is None for m in mons):
        blockers.append("l'état du quorum est illisible")
    else:
        left_total = len(mons) - 1
        needed = left_total // 2 + 1
        left = sum(1 for m in mons if m is not target and m["in_quorum"] is True)
        if left_total and left < needed:
            blockers.append(f"le quorum serait perdu ({left} moniteur(s) dans le quorum sur {left_total} restants, il en faut {needed})")
    risks = [f"le moniteur {target['name']} sera DÉTRUIT, avec le gestionnaire du même nom"]
    left_total = len(mons) - 1
    if left_total == 2:
        risks.append("il ne restera que 2 moniteurs : la panne d'un seul bloquera TOUT le stockage Ceph (il en faut 3 pour tolérer une panne)")
    elif left_total > 2 and left_total % 2 == 0:
        risks.append(f"il restera {left_total} moniteurs (PAIR) : cela n'améliore pas la tolérance aux pannes")
    if mgr_here_is_last:
        risks.append("c'est aussi le DERNIER gestionnaire actif : plus de tableau de bord ni d'autoscaler de groupes de placement")
    return blockers, risks


def mgr_plan(target: dict, mgrs: list[dict], health: str) -> tuple[list[str], list[str]]:
    blockers = [f"Ceph est en erreur ({health}) : la destruction est refusée"] if health not in ("HEALTH_OK", "HEALTH_WARN") else []
    others = [m for m in mgrs if m is not target and m.get("state") in RUNNING_MGR]
    risks = [f"le gestionnaire {target['name']} sera DÉTRUIT"]
    risks.append("un autre gestionnaire prendra le relais" if others else "c'est le DERNIER gestionnaire : plus de tableau de bord, plus d'autoscaler de groupes de placement, statistiques figées")
    return blockers, risks


def mds_plan(target: dict, servers: list[dict], filesystems: list[dict], health: str) -> tuple[list[str], list[str]]:
    blockers = [f"Ceph est en erreur ({health}) : la destruction est refusée"] if health not in ("HEALTH_OK", "HEALTH_WARN") else []
    others = [m for m in servers if m is not target and str(m.get("state") or "").startswith("up:")]
    if not others and filesystems:
        blockers.append(f"c'est le SEUL MDS et le CephFS {_names(sorted(f['name'] for f in filesystems))} existe : il deviendrait indisponible pour tous ses clients")
    risks = [f"le MDS {target['name']} sera DÉTRUIT"]
    risks.append("un autre MDS prendra le relais" if others else "aucun autre MDS ne tourne")
    return blockers, risks
