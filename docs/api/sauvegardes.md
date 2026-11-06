# Sauvegardes (lister, lancer, supprimer)

Toutes les routes exigent une session ouverte. Elles ne concernent que les sauvegardes **vzdump sur un stockage de
fichiers** (`vzdump-qemu-100-2026_11_02-02_00_01.vma.zst`, `.tar.zst`…). Les sauvegardes d'un Proxmox Backup Server
(`backup/ct/100/…`) sont listées mais **ne peuvent pas être supprimées ici** (`deletable: false`).

La restauration vers une **nouvelle** machine (M5-3) est décrite plus bas. Les sauvegardes planifiées (M5-4) auront leur
propre fichier.

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/nodes/{node}/storage/{storage}/backups?vmid=` | Lister les sauvegardes d'un stockage (lecture seule) |
| `POST /api/connections/{id}/nodes/{node}/backups` | Lancer une sauvegarde manuelle d'une VM ou d'un LXC |
| `DELETE /api/connections/{id}/nodes/{node}/storage/{storage}/backups/{volume}?confirm=true&name=…` | Supprimer **définitivement** une sauvegarde |
| `POST /api/connections/{id}/nodes/{node}/restore` | Restaurer une sauvegarde vers une **nouvelle** machine (jamais d'écrasement) |

Les erreurs de Proxmox sont traduites en 502 ou 504, sans jamais exposer le token. Pour les autres codes d'erreur, le
message de la réponse Proxmox est recopié dans `detail` (comportement existant de `cluster.py`). Les erreurs de
validation (422) ne renvoient pas la valeur saisie. Tout lancement et toute suppression sont **audités**
(`backup-create`, `backup-delete`), y compris les refus et les erreurs, sans secret.

## Lister

`node` et `storage` sont validés par les mêmes regex que le reste de Kaji. Source : `content=backup` côté Proxmox.
Tri : de la plus récente à la plus ancienne. `vmid` (optionnel, 100 à 999999999) filtre sur une machine.

| Champ | Type | Sens |
|---|---|---|
| `volid` | texte | Identifiant complet (`local:backup/vzdump-qemu-100-….vma.zst`) |
| `name` | texte | Nom du fichier |
| `vmid` | entier ou `null` | Machine sauvegardée (donnée de Proxmox, sinon lue dans le nom du fichier) |
| `type` | `qemu`, `lxc` ou `null` | Lu dans le nom du fichier ; `null` si la forme est inconnue |
| `format`, `size`, `ctime`, `date`, `notes` | | Format, octets, date (secondes depuis 1970 et ISO 8601 UTC), notes ; `null` si absent ou illisible |
| `protected` | booléen | Sauvegarde protégée contre la suppression. **Par prudence, toute valeur inattendue compte comme protégée** : seules `0`, `"0"`, `false`, `"false"`, vide et absente comptent comme non protégée |
| `deletable` | booléen | `true` seulement si le nom est un fichier vzdump reconnu **et** que la sauvegarde n'est pas protégée |

Une entrée sans `volid` est ignorée.

## Lancer

Corps JSON. **Seuls ces champs existent** ; tout autre champ est ignoré et jamais transmis à Proxmox.

| Champ | Validation | Valeur par défaut |
|---|---|---|
| `vmid` | entier, 100 à 999999999 | obligatoire |
| `storage` | regex des stockages (40 caractères au plus, lettres, chiffres, `_`, `-`) | obligatoire |
| `mode` | `snapshot`, `suspend` ou `stop` | `snapshot` |
| `compress` | `zstd`, `gzip`, `lzo` ou `none` | `zstd` |
| `notes` | 200 caractères au plus, **une seule ligne, sans antislash** (saut de ligne final compris) | aucune |
| `confirm` | booléen. **Exigé à `true` quand `mode` vaut `stop`** ; sans effet pour les autres modes. Jamais transmis à Proxmox | `false` |

Réponse : `{"upid", "node", "vmid", "storage"}`. L'UPID se suit avec `lib/tasks.ts` (`runTask` avec
`LONG_TASK_SECONDS` : une sauvegarde est longue).

À savoir :
- **Mode `stop`** : Proxmox **arrête la machine** pendant la sauvegarde. Sans `confirm=true`, l'API répond 400 **avant
  tout appel à Proxmox** (le refus est audité). L'interface doit prévenir clairement avant d'envoyer `confirm=true`.
- **Mode `suspend`** : Proxmox met la machine en pause pendant la sauvegarde. **Aucune confirmation n'est exigée**
  (seul `stop` l'est, sur demande de PC A) : à reconsidérer si une coupure de service pose problème.
- **Jamais d'élagage** : Kaji envoie toujours `remove=0`. Sans cela, Proxmox applique la rétention du stockage
  après une sauvegarde manuelle et supprime d'anciennes sauvegardes. Écart volontaire avec le comportement par défaut de Proxmox.
- **`notes`** est transmis à Proxmox sous le nom `notes-template` (c'est le vrai nom de l'option vzdump). Proxmox y
  remplace `{{guestname}}`, `{{vmid}}`, `{{node}}` et `{{cluster}}`.
- Le texte des notes n'est pas copié dans l'audit (« notes=définies »).

## Supprimer

`volume` est le **nom du fichier**, validé strictement (`vzdump-(qemu|lxc)-<vmid>-AAAA_MM_JJ-HH_MM_SS.(vma|tar)[.zst|.gz|.lzo]`).
Pas de `/`, pas de chemin. Kaji reconstruit le `volid` à partir du stockage de la route.

Garde-fous, **vérifiés côté serveur**, dans cet ordre. Chacun refuse **avant tout appel d'écriture** à Proxmox :

| # | Condition | Réponse |
|---|---|---|
| 1 | `confirm=true` | 400 sinon |
| 2 | `name` identique, caractère pour caractère, au nom du fichier | 400 sinon |
| 3 | La sauvegarde existe sur **ce** stockage (lecture de `content=backup`, correspondance exacte du `volid`) | 404 sinon |
| 4 | Le volume est bien de type `backup` | 409 sinon |
| 5 | La sauvegarde n'est pas protégée | 409 sinon |

Une seule sauvegarde à la fois : il n'existe aucune route de suppression en masse.
Réponse : `{"upid", "deleted"}`.

Deux formes à ne pas confondre :
- **Dans l'URL de Kaji**, `{volume}` est le **nom du fichier** seul (`vzdump-qemu-100-….vma.zst`), jamais un `volid`.
- **Dans l'appel de Kaji à Proxmox**, c'est le `volid` complet (`local:backup/vzdump-…`) envoyé en **un seul segment
  encodé** (`local%3Abackup%2Fvzdump-…`). Le client de Kaji n'a pas à s'en occuper.

## Restaurer vers une nouvelle machine

`POST /api/connections/{id}/nodes/{node}/restore` (réponse 202). **Cette route ne remplace jamais une machine
existante** : l'option `force` de Proxmox n'existe pas dans l'API de Kaji et n'est jamais envoyée.

Corps JSON. **Seuls ces champs existent** ; tout autre champ (dont `force`, `start`, `type`…) est ignoré et jamais
transmis à Proxmox.

| Champ | Validation | Valeur par défaut |
|---|---|---|
| `volid` | exactement `stockage:backup/vzdump-(qemu\|lxc)-<vmid>-AAAA_MM_JJ-HH_MM_SS.(vma\|tar)[.zst\|.gz\|.lzo]` : pas de chemin, pas de `..`, pas de sauvegarde d'un Proxmox Backup Server | obligatoire |
| `vmid` | entier, 100 à 999999999 | **prochain identifiant libre** (`/cluster/nextid`) |
| `storage` | stockage de destination des disques, regex des stockages | obligatoire |
| `pool` | regex des pools | aucun |
| `unique` | booléen : nouvelle adresse MAC aléatoire | `true` |

Le **type** (VM ou conteneur) est lu dans le **nom du fichier**, jamais choisi par l'appelant : une archive `qemu` va
vers `POST /nodes/{node}/qemu` (`archive=<volid>`), une archive `lxc` vers `POST /nodes/{node}/lxc`
(`ostemplate=<volid>` et `restore=1`).

Garde-fous, **vérifiés côté serveur**, dans cet ordre. Chacun refuse **avant tout appel d'écriture** à Proxmox :

| # | Condition | Réponse |
|---|---|---|
| 1 | `volid`, `vmid`, `storage`, `pool` valides (regex strictes, saut de ligne final refusé) | 422 sinon |
| 2 | La sauvegarde existe sur ce stockage, avec le `volid` exact (lecture de `content=backup`) | 404 sinon |
| 3 | Le volume est bien de type `backup` | 409 sinon |
| 4 | Si `vmid` est fourni : **aucune VM ni aucun conteneur ne porte déjà cet identifiant**, sur n'importe quel nœud (lecture de `/cluster/resources`) | 409 sinon |
| 5 | Si `vmid` est absent : Proxmox renvoie bien un identifiant libre lisible | 502 sinon |

Réponse : `{"upid", "node", "vmid", "type", "archive"}`. La tâche est longue : `lib/tasks.ts` (`runTask` avec
`LONG_TASK_SECONDS`).

À savoir :
- **`storage` est toujours envoyé.** Pour un conteneur, Proxmox prendrait sinon le stockage « local ».
- **`unique=true` par défaut** : sans cela, la machine restaurée garde les adresses MAC de l'originale, et un doublon
  réseau apparaît tant que celle-ci existe. Écart avec ce que demande le ticket (qui ne le mentionne pas). `unique: false` est possible.
- **La machine restaurée n'est pas démarrée** (`start` n'est jamais envoyé).
- Restaurer sous l'identifiant de la machine d'origine n'est possible **que si celle-ci n'existe plus** : ce n'est
  alors pas un écrasement.
- Audit `backup-restore` pour le succès (avec l'UPID, la sauvegarde source, le stockage et le pool), pour chaque refus et
  pour chaque erreur, sans secret.
- **Droits Proxmox** : avec le token de test actuel, créer une machine hors du pool `kaji-test` est refusé par Proxmox
  (« Droits insuffisants », traduit en 502 par Kaji). Dans cette configuration, **`pool` est de fait obligatoire**. Ce
  n'est pas un défaut du code : cela dépend des droits accordés au token.

## Ce qui a été validé en réel, et ce qui ne l'a pas été

Le code a été écrit et testé avec un **faux Proxmox**. Un second agent (PC A) a ensuite validé une partie en réel, dans le
bac à sable (pool `kaji-test`, machines jetables supprimées après coup).

**Validé en réel**
- **Restauration d'une VM** : `POST …/restore` renvoie 202 ; la nouvelle VM est créée, **arrêtée**, avec le même disque ; la
  VM d'origine est intacte. Les paramètres `archive`, `vmid`, `storage` et `pool` sont acceptés.
- **Restauration d'un conteneur** (`ostemplate` et `restore=1`) : 202, nouveau conteneur créé et arrêté, original intact.
  Le type est bien lu dans le nom du fichier.
- **`unique=1` (défaut)** : sur une VM à deux cartes réseau, les deux adresses MAC changent ; avec `unique: false`, elles
  restent identiques à l'original.
- **Identifiant déjà utilisé**, avec `force: true` dans le corps : 409, rien n'est écrit, `force` n'est pas transmis.
- **`/cluster/resources?type=vm`** renvoie les machines des deux nœuds du cluster ; **`/cluster/nextid`** donne bien l'id suivant.
- **Sauvegarde** : lancement `vzdump` (notes conservées, 200) ; suppression refusée sans confirmation (400) ou avec un
  mauvais nom (400) ; suppression confirmée (200, avec un UPID) ; la liste est ensuite vide.

**Non validé en réel**
- **`protected: 1`** : une sauvegarde protégée apparaît-elle ainsi dans `content=backup` ? Kaji ne sait pas protéger une
  sauvegarde, il faut passer par Proxmox directement pour produire ce cas.
- **`remove=0`** : empêche-t-il bien tout élagage par la rétention du stockage ?
- **`/cluster/resources?type=vm` pour un nœud hors ligne** : y figure-t-il ? S'il n'y figurait pas, Proxmox refuserait
  quand même sans `force`, mais Kaji ne verrait pas l'identifiant pris avant l'appel.
