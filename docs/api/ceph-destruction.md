# Ceph, destruction (lot C4)

Cinq routes `DELETE`, toutes sous `/api/connections/{id}/ceph`. **Jamais validées sur un vrai Ceph** (le cluster réel n'en a pas : `binary not installed`) : faux Proxmox strict seulement, voir `docs/m12-ceph.md`.

| Route | Proxmox | Paramètres Kaji |
|---|---|---|
| `DELETE /pools/{pool}` | `DELETE /nodes/{n}/ceph/pool/{pool}` | `node` (facultatif), `remove_storages` |
| `DELETE /nodes/{node}/osds/{id}` | `DELETE /nodes/{node}/ceph/osd/{id}` | `cleanup` |
| `DELETE /nodes/{node}/monitors/{name}` | `DELETE /nodes/{node}/ceph/mon/{name}` (détruit aussi le gestionnaire du même nom) | |
| `DELETE /nodes/{node}/managers/{name}` | `DELETE /nodes/{node}/ceph/mgr/{name}` | |
| `DELETE /nodes/{node}/mds/{name}` | `DELETE /nodes/{node}/ceph/mds/{name}` | |

Toutes prennent `confirm=true`, **`name` = le nom exact retapé** (`osd.N` pour un OSD) et `dry_run=true`. Réponse `202` `{upid, node}` (tâche Proxmox) ; un aperçu répond `200` `{dry_run, blockers, risks, expected_name, …}` **sans rien écrire ni auditer**.

**CephFS : non couvert.** Le schéma de Proxmox 9 n'a pas de `DELETE` pour un système de fichiers (seulement la création) : il se détruit en ligne de commande (`pveceph fs destroy` n'a pas d'équivalent API ici). Un test vérifie qu'aucune route Kaji n'existe pour cela. L'option `force` de Proxmox (détruire un pool « même utilisé ») n'est **jamais** exposée.

## Barrières (`app/cephdestroy.py`, le serveur décide)
**Refus (`blockers`, 409) : aucune confirmation ne les lève.**
- **Pool** : santé autre que `HEALTH_OK` ; pool interne (`.mgr`) ; utilisé par un CephFS (métadonnées ou données) ; un stockage Proxmox `rbd` qui l'utilise contient des volumes (machines citées), ou son contenu est illisible ; un stockage le référence et `remove_storages` n'est pas demandé (avec : il est retiré avec le pool, pour tout le cluster).
- **OSD** : encore DEDANS, encore en marche, nombre de groupes de placement illisible ou non nul (données non évacuées) ; santé autre que `HEALTH_OK` ; groupes de placement pas tous `active+clean`.
- **Moniteur** : le dernier ; santé autre que `HEALTH_OK` ; quorum illisible ou qui serait perdu (majorité des restants).
- **Gestionnaire** : Ceph en erreur (`HEALTH_ERR` / inconnue).
- **MDS** : Ceph en erreur ; le SEUL MDS actif alors qu'un CephFS existe.

**Risques (`risks`) : listés dans la confirmation.** Données du pool détruites (avec leur volume approximatif), `cleanup` qui efface la table de partitions, moniteur : 2 restants (une panne bloque tout Ceph) ou nombre pair, gestionnaire jumeau ou dernier gestionnaire, dernier gestionnaire, aucun autre MDS.

Une seule écriture Ceph à la fois par connexion (verrou partagé avec C2/C3/C5), nœud et hôte du service relus (`404` / `409`), `409` si Ceph n'est pas installé. Audit `ceph-pool-destroy`, `ceph-osd-destroy`, `ceph-mon-destroy`, `ceph-mgr-destroy`, `ceph-mds-destroy` (succès, refus, erreur), sans secret. Droit chez Proxmox : `Sys.Modify` sur `/` (pool, moniteur, gestionnaire, MDS) ; la destruction d'un OSD n'a pas de clause `permissions` dans le schéma.

## Interface
Page « Ceph » : bouton « Détruire… » sur chaque OSD, pool (sauf internes), moniteur, gestionnaire et MDS. La fenêtre lance l'aperçu tout de suite, montre les refus (rouge) et les risques (orange) ; « Détruire » ne s'active que sans refus et quand le nom est retapé. Les messages de refus construits avec des valeurs restent en français.
