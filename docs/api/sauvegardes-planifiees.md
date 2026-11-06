# Sauvegardes planifiées (jobs)

Gère les jobs de `/cluster/backup` de Proxmox. Toutes les routes exigent une session ouverte. Les sauvegardes manuelles,
leur suppression et leur restauration sont dans `sauvegardes.md`.

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/backup-jobs` | Lister les jobs (lecture seule) |
| `GET /api/connections/{id}/backup-jobs/{job_id}` | Voir un job (lecture seule) |
| `POST /api/connections/{id}/backup-jobs` | Créer un job (201, renvoie `{"id"}`) |
| `PUT /api/connections/{id}/backup-jobs/{job_id}` | Modifier un job, l'activer ou le désactiver (mise à jour partielle) |
| `DELETE /api/connections/{id}/backup-jobs/{job_id}?confirm=true` | Supprimer un job (pas les sauvegardes déjà faites) |

Les erreurs de Proxmox sont traduites en 502 ou 504, sans jamais exposer le token. Les erreurs de validation (422) ne
renvoient pas la valeur saisie. Chaque création, modification et suppression est **auditée**
(`backup-job-create`, `backup-job-update`, `backup-job-delete`), y compris les refus et les erreurs, sans secret. Le texte
des notes n'est jamais copié dans l'audit (« notes=définies »).

## Droit Proxmox nécessaire pour écrire : `Sys.Modify` sur `/`

Dans la version de Proxmox testée, **créer, modifier ou supprimer un job de sauvegarde exige `Sys.Modify` sur `/`**, un
droit très large (il couvre aussi la configuration des nœuds). Sans lui, Proxmox répond « Permission check failed
(/, Sys.Modify) », même pour un job minimal et désactivé. **La lecture (`GET`) ne l'exige pas.**

Kaji traduit ce refus en 502 avec un message qui nomme le droit manquant : « Droits insuffisants pour cette opération :
Proxmox exige le droit Sys.Modify sur « / » pour créer, modifier ou supprimer un job de sauvegarde ». Le même texte est
écrit dans l'audit. Les autres erreurs de Proxmox ne sont pas commentées ainsi.

Ce droit n'est **pas** accordé au token de test actuel. L'accorder à `kaji@pve` est une décision du propriétaire :
sans lui, cette fonction reste **en lecture seule** en pratique.

## Pourquoi tant de garde-fous

Une rétention trop courte **détruit des sauvegardes**, et un job s'exécute sans personne devant. Ce que Proxmox applique :
après chaque sauvegarde, le job supprime les sauvegardes **plus anciennes des machines sélectionnées sur ce stockage**,
y compris celles qui n'ont pas été faites par ce job. Les règles de rétention **s'additionnent** (chacune couvre sa période) :
augmenter une valeur ou ajouter une règle garde un sur-ensemble ; en diminuer une ou en retirer une peut supprimer.

## Champs

**Seuls ces champs existent** ; tout autre champ envoyé (`script`, `mailto`, `bwlimit`, `id`, `exclude`, `remove`,
`delete`…) est ignoré et jamais transmis à Proxmox.

| Champ | Validation | Création | Mise à jour |
|---|---|---|---|
| `schedule` | **grammaire stricte** : `HH:MM`, éventuellement précédée de jours (`mon`, `mon,wed`, `mon..fri`). Pas de `*`, d'intervalle (`*:0/5`), de secondes ni de date | obligatoire | facultatif |
| `storage` | regex des stockages | obligatoire | facultatif |
| `selection` | voir ci-dessous | obligatoire | facultatif |
| `mode` | `snapshot`, `suspend`, `stop` | `snapshot` | facultatif |
| `compress` | `zstd`, `gzip`, `lzo`, `none` | `zstd` | facultatif |
| `retention` | voir ci-dessous | aucune (la rétention du stockage s'applique) | facultatif, jamais `null` |
| `node` | regex des nœuds ; absent = tous les nœuds | tous | `null` le retire |
| `enabled` | booléen | `true` | facultatif |
| `notes` | 200 caractères au plus, une seule ligne, sans antislash ; transmis sous le nom Proxmox `notes-template` | aucune | `null` le retire |
| `confirm` | booléen, voir plus bas ; jamais transmis à Proxmox | `false` | `false` |

Les jours sont `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`. Dans `schedule`, les jours et l'heure sont séparés par
**un seul espace** (jamais une tabulation, un saut de ligne ni une espace insécable) et cet espace est obligatoire
(`mon02:00` est refusé). Le saut de ligne final est refusé partout.

**`selection`** : exactement l'une de ces trois formes.
- `{"type": "vmids", "vmids": [100, 101]}` : 1 à 100 identifiants distincts, de 100 à 999999999.
- `{"type": "pool", "pool": "prod"}` : regex des pools.
- `{"type": "all"}` : toutes les machines.

À la mise à jour, fournir `selection` **remplace** la sélection : les anciennes clés (`vmid`, `pool`, `all`, et `exclude`
qui n'a de sens qu'avec `all`) sont supprimées côté Proxmox, seulement si elles existent dans le job.

**`retention`** : soit `{"keep_all": true}` (rien n'est supprimé), soit au moins une règle parmi `keep_last`,
`keep_hourly`, `keep_daily`, `keep_weekly`, `keep_monthly`, `keep_yearly`, **chacune de 1 à 999**.
- **Zéro est refusé** (422) : « garder 0 » supprimerait tout. Une politique vide l'est aussi.
- `keep_all` ne se combine avec aucune autre règle.

## Confirmations (`confirm: true`)

Sans elle, la route répond **400 avant tout appel d'écriture** à Proxmox, et le refus est audité. Le message dit
pourquoi. Elle est exigée dans ces cas :

| Cas | Raison |
|---|---|
| Création ou mise à jour avec `mode: "stop"` ; activation d'un job déjà en mode `stop` | `stop` **arrête chaque machine à chaque exécution** |
| **Création** avec une rétention finie (pas `keep_all`) | elle s'applique dès la première exécution à des sauvegardes qui existent déjà |
| **Mise à jour qui réduit la rétention** | voir la définition ci-dessous |
| Mise à jour du `storage` ou de la `selection` d'un job dont la rétention est finie | elle s'appliquera à d'autres sauvegardes, qui seront supprimées |
| **Suppression** d'un job (`?confirm=true`) | la réponse rappelle que les sauvegardes déjà faites sont conservées |

**Réduire la rétention** : la nouvelle politique est finie **et** l'ancienne gardait plus. Précisément, c'est le cas si
l'ancienne politique était absente ou `keep_all` (on ne sait pas ce qu'elle gardait, ou tout), ou si une règle de
l'ancienne est absente de la nouvelle ou a une valeur plus petite. Augmenter une valeur, ajouter une règle, garder
l'identique ou passer à `keep_all` ne demande aucune confirmation.

## Mise en forme d'un job

| Champ | Sens |
|---|---|
| `id`, `enabled`, `schedule`, `storage`, `mode`, `compress`, `node`, `notes` | comme ci-dessus (`compress: "none"` pour `0`) |
| `selection` | même forme que celle acceptée ; `{"type": null}` si le job n'a aucune sélection lisible |
| `retention` | `{"keep_all": true}`, ou les règles (`keep_last`…), ou `null` si le job n'en a pas |
| `next_run` | prochaine exécution (ISO 8601, UTC) ou `null` |
| `repeat_missed` | le job rattrape les exécutions manquées |

Une entrée sans `id` lisible est ignorée. Une valeur du mauvais type devient `null`.

## Ce qui a été validé en réel, et ce qui ne l'a pas été

Le code a été écrit et testé avec un **faux Proxmox**, d'après la documentation de `vzdump` (la page de manuel ne décrit
pas les options propres aux jobs). Un second agent (PC A) a ensuite essayé en réel, dans le bac à sable.

**Validé en réel**
- **Lecture** : `GET …/backup-jobs` renvoie 200. Le cluster n'avait **aucun job**, donc la liste était vide.
- **Refus de confirmation** : la création sans `confirm=true` (400) et la suppression sans `confirm=true` (400) sont
  refusées sans rien écrire.

**Non validé en réel : création, modification, suppression.** Proxmox les refuse avec « Permission check failed
(/, Sys.Modify) » tant que le droit décrit plus haut n'est pas accordé. Tout ce qui suit reste donc une hypothèse :
- `POST /cluster/backup` accepte exactement ces paramètres (`id` choisi par Kaji sous la forme `kaji-<10 hexa>`, `vmid`
  en liste séparée par des virgules, `all`, `pool`, `prune-backups`, `notes-template`, `enabled`, `node`) ;
- `PUT /cluster/backup/{id}` accepte `delete` avec une liste séparée par des virgules ;
- **la forme des jobs en lecture** : `prune-backups` sous la forme `keep-last=3,keep-daily=7`, `enabled` en 0 ou 1,
  `next-run` en secondes. Faute de job existant, la mise en forme d'un vrai job n'a **jamais été vue** ;
- **la rétention d'un job supprime bien les sauvegardes plus anciennes faites hors du job** (c'est ce qui justifie la
  confirmation à la création) ;
- `DELETE /cluster/backup/{id}` ne touche à aucune sauvegarde.
