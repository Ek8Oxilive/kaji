# Journal des tâches (lecture seule)

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/tasks` | **Liste** des tâches de tous les nœuds en ligne (ou d'un seul), fusionnées et triées, les plus récentes d'abord |
| `GET /api/connections/{id}/tasks/{node}/{upid}` | État d'une tâche (existant, jalon M2) |
| `GET /api/connections/{id}/tasks/{node}/{upid}/log?start=&limit=` | Journal d'une tâche, par morceaux (existant, jalon M2) |

Lecture seule : **aucune écriture** (Kaji n'annule ni ne supprime aucune tâche). Droit Proxmox : `Sys.Audit` sur `/nodes` (déjà accordé).

## Liste (`GET …/tasks`)

Paramètres (tous facultatifs, validés ; une valeur invalide donne **422** et rien n'est envoyé à Proxmox) :

| Paramètre | Sens |
|---|---|
| `node` | Un seul nœud ; sinon tous les nœuds **en ligne** (32 au plus) |
| `limit` | 1 à 500 (défaut 100) : les plus récentes, **tous nœuds confondus** (chaque nœud en fournit `limit`, puis la fusion garde les `limit` plus récentes, sans doublon d'UPID) |
| `errors` | Seulement les tâches dont l'état n'est pas « OK » (échecs **et avertissements**, comme Proxmox) |
| `running` | Seulement les tâches en cours |
| `vmid` | Une machine (100 à 999999999) |
| `type` | Un type de tâche (`qmstart`, `vzdump`…) : `^[a-z0-9_]{1,40}$` |

Réponse : `{"tasks": [...], "failed": [{"node", "reason"}]}`.

| Champ d'une tâche | Sens |
|---|---|
| `upid`, `node`, `type`, `id`, `user`, `token` | Tels que Proxmox les donne (`id` toujours en texte ; une valeur absente ou d'un autre type devient `null`) |
| `start`, `end`, `duration` | ISO 8601 UTC ; `end` et `duration` sont `null` pour une tâche en cours |
| `state` | `running`, `ok`, `warning` (« WARNINGS: n », réussie avec avertissements) ou `error` |
| `status_text` | Message d'état d'une tâche **non réussie** (borné à 200 caractères), sinon `null` |
| `by_kaji` | `true` si la tâche a été lancée par le **jeton de cette connexion** : même utilisateur **et** même nom de jeton |

Règles de prudence :
- **Constaté en réel** : par défaut, Proxmox ne renvoie que les tâches **archivées** (terminées) ; Kaji demande donc `source=all`
  (ou `source=active` pour le filtre « en cours »), sinon les tâches en cours seraient absentes. Une tâche active a le statut
  **`RUNNING`** et pas d'heure de fin.
- Une tâche qui a une heure de fin sans état lisible est `error`, **jamais `ok` par défaut**. Un état `RUNNING` avec une fin est aussi `error`.
- Une entrée dont l'UPID est absent ou de forme inattendue est ignorée (elle ne peut pas servir à lire un journal).
- **Un nœud en échec n'empêche pas les autres** : il est listé dans `failed`. Si **aucun** nœud ne répond, l'erreur est renvoyée
  (pas une liste vide trompeuse) ; aucun nœud en ligne : **503**.
- Aucun secret : les messages d'état sont du texte libre de Proxmox, borné, affiché sans interprétation.

## Page « Tâches »

Tableau (état en toutes lettres, tâche en français, machine nommée, nœud, utilisateur avec la mention **Kaji**, début, durée), filtres
(état, nœud, nombre, recherche), rafraîchissement toutes les 3 s tant qu'une tâche est en cours (15 s sinon). Un clic ouvre un **tiroir**
avec l'état et le **journal**, lu par morceaux de 1000 lignes (20 000 au plus) et **suivi en direct** tant que la tâche tourne.
Le filtre « Échecs » exclut les avertissements (que Proxmox compte comme « pas OK »).

## Validé en réel, et ce qui ne l'a pas été

Validé sur un vrai cluster (lecture seule, et des conteneurs jetables du bac à sable, supprimés ensuite) : la liste sur les deux nœuds,
les quatre états (dont **En cours** pour une tâche active, `RUNNING`), les filtres, le badge **Kaji**, les noms de machines, le tiroir
d'une tâche terminée (journal complet jusqu'à `TASK WARNINGS: 1`) et d'une tâche en cours (« Journal suivi en direct »).

**Non validé en réel** : le suivi en direct d'une tâche **jusqu'à sa fin** depuis le tiroir (la tâche de test avait déjà fini quand je
l'ai ouverte) ; un nœud qui ne répond pas (le cas est testé sur le faux Proxmox) ; plus de 500 tâches ; un journal de plus de 20 000
lignes ; l'écran étroit.
