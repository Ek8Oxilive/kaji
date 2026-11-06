# Stockage (lecture seule)

Toutes les routes exigent une session ouverte. **Aucune ne modifie quoi que ce soit** : pas de création de stockage,
pas d'écriture (`POST`, `PUT`, `PATCH` et `DELETE` répondent 405).

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/storages` | Liste des stockages, une entrée par couple (stockage, nœud) |
| `GET /api/connections/{id}/nodes/{node}/storage/{storage}/content?content=…` | Volumes d'un stockage |

Les erreurs de Proxmox sont traduites en 502 (injoignable, droits insuffisants…) ou 504 (délai dépassé), sans jamais
exposer le token. Pour les autres codes d'erreur, le message de la réponse Proxmox est recopié dans `detail`
(comportement existant de `cluster.py`) : il peut contenir un détail d'infrastructure. Les erreurs de validation (422) ne renvoient pas la valeur saisie.

## `GET /storages`

Source : `/cluster/resources?type=storage`. Un stockage partagé apparaît une fois par nœud qui le porte.
Le tri est par nom de stockage puis par nœud.

Les champs historiques sont **conservés tels quels** (l'interface actuelle s'en sert) ; les champs de la
seconde moitié du tableau sont nouveaux.

| Champ | Type | Sens |
|---|---|---|
| `storage` | texte | Nom du stockage |
| `node` | texte ou `null` | Nœud de cette entrée |
| `type` | texte | Type de stockage Proxmox (`dir`, `lvmthin`, `rbd`, `nfs`…) |
| `status` | texte | Statut brut renvoyé par Proxmox (`available`…) |
| `shared` | booléen | Stockage partagé entre nœuds |
| `disk` | nombre | Octets utilisés, valeur brute de Proxmox |
| `maxdisk` | nombre | Octets au total, valeur brute de Proxmox |
| `content` | texte | Contenus acceptés, chaîne brute (`iso,backup`) |
| `contents` | liste | Contenus acceptés, dans cet ordre fixe (pas alphabétique) : `images`, `rootdir`, `iso`, `vztmpl`, `backup`, `snippets` ; types inconnus ignorés |
| `used` / `total` | entier ou `null` | Octets utilisés / total ; `null` si absent ou illisible |
| `free` | entier ou `null` | `total - used`, `null` si l'un des deux manque |
| `active` | booléen | `true` seulement si le statut est `available` |
| `nodes` | liste | Tous les nœuds qui portent un stockage de ce nom |

**Tolérance** : une ligne sans nom de stockage ou qui n'est pas un objet est ignorée ; un chiffre ou un nom de nœud
illisible (mauvais type, `--5`, `inf`, nombre démesuré) devient `null`. Un stockage inactif reste listé
(`active: false`). Rien de tout cela n'empêche de lister les autres stockages.

**Non vérifié** : pour un stockage inactif, les tests supposent que Proxmox n'envoie pas `disk` ni `maxdisk`
(chiffres à `null`). S'il envoie `0`, on aura `used: 0`, `total: 0`, `free: 0`.

## `GET /nodes/{node}/storage/{storage}/content`

| Paramètre | Validation |
|---|---|
| `node` | Même regex que les actions : lettres, chiffres, tirets, 63 caractères au plus, sans tiret en tête |
| `storage` | Même regex que la création de VM : 40 caractères au plus, lettres, chiffres, `_`, `-` |
| `content` (optionnel) | Liste blanche : `images`, `rootdir`, `iso`, `vztmpl`, `backup`, `snippets`. Une seule valeur ; toute autre est refusée (422) et **n'est jamais transmise à Proxmox** |

Sans `content`, tous les volumes sont renvoyés. Réponse : liste triée par type de contenu puis nom.

| Champ | Type | Sens |
|---|---|---|
| `volid` | texte | Identifiant complet (`local:iso/debian.iso`) |
| `name` | texte | Nom court, déduit du `volid` |
| `content` | texte ou `null` | Type de contenu |
| `format` | texte ou `null` | Format (`iso`, `qcow2`, `raw`, `vma.zst`, `tgz`…) |
| `size` | entier ou `null` | Octets |
| `ctime` | entier ou `null` | Date de création, secondes depuis 1970 |
| `date` | texte ou `null` | La même date en ISO 8601, UTC |
| `vmid` | entier ou `null` | Machine propriétaire, si Proxmox la connaît |
| `notes` | texte ou `null` | Notes (sauvegardes) |
| `protected` | booléen | Volume protégé contre la suppression |

Une entrée sans `volid` est ignorée ; un champ du mauvais type devient `null` (`date` aussi si l'horodatage est hors limites). Un stockage inactif ou illisible fait répondre 502 pour **ce** stockage ;
les autres restent consultables.

## Droits Proxmox nécessaires

Lecture seule, donc un token limité à l'audit des stockages (`Datastore.Audit`) devrait suffire. **Non vérifié sur un
vrai cluster** : seuls des tests avec un faux Proxmox ont été faits.
