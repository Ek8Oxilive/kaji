# Sauvegardes (lister, lancer, supprimer)

Toutes les routes exigent une session ouverte. Elles ne concernent que les sauvegardes **vzdump sur un stockage de
fichiers** (`vzdump-qemu-100-2026_11_02-02_00_01.vma.zst`, `.tar.zst`…). Les sauvegardes d'un Proxmox Backup Server
(`backup/ct/100/…`) sont listées mais **ne peuvent pas être supprimées ici** (`deletable: false`).

La restauration (M5-3) complétera ce fichier.

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/nodes/{node}/storage/{storage}/backups?vmid=` | Lister les sauvegardes d'un stockage (lecture seule) |
| `POST /api/connections/{id}/nodes/{node}/backups` | Lancer une sauvegarde manuelle d'une VM ou d'un LXC |
| `DELETE /api/connections/{id}/nodes/{node}/storage/{storage}/backups/{volume}?confirm=true&name=…` | Supprimer **définitivement** une sauvegarde |

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
| `protected` | booléen | Sauvegarde protégée contre la suppression |
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
| `notes` | 200 caractères au plus, **une seule ligne, sans antislash** | aucune |

Réponse : `{"upid", "node", "vmid", "storage"}`. L'UPID se suit avec `lib/tasks.ts` (`runTask` avec
`LONG_TASK_SECONDS` : une sauvegarde est longue).

À savoir :
- **Mode `stop`** : Proxmox arrête la machine pendant la sauvegarde. `suspend` la met en pause. Aucune confirmation
  n'est exigée par l'API (le ticket ne la demande pas) : l'interface devrait prévenir.
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
Réponse : `{"upid", "deleted"}`. Le volume est envoyé à Proxmox en un seul segment encodé
(`local%3Abackup%2Fvzdump-…`).

## Non vérifié sur un vrai cluster

Tout ce qui précède a été testé avec un **faux Proxmox**, écrit d'après la documentation officielle de `vzdump`.
À valider en réel, dans le bac à sable :
- `DELETE …/content/local%3Abackup%2F<fichier>` (volid complet encodé en un segment) est accepté par Proxmox et renvoie un UPID ;
- `POST /nodes/{node}/vzdump` accepte exactement ces paramètres, et `remove=0` empêche bien tout élagage ;
- une sauvegarde protégée apparaît avec `protected: 1` dans `content=backup`.
