# Configuration des stockages (ajouter, modifier, retirer)

Préfixe : `/api/connections/{id}/storage-config`. Droit Proxmox requis : `Datastore.Allocate` sur `/storage`. Toute écriture est auditée
(`storage-add`, `storage-edit`, `storage-delete`), refus compris ; les secrets n'y figurent jamais (« défini »).

| Route | Rôle |
|---|---|
| `GET /` | configuration de chaque stockage du datacenter (liste blanche, jamais de secret). `managed: false` = type que Kaji ne modifie pas (ex. `pbs`) |
| `GET /{storage}` | un stockage (404 s'il n'existe pas) |
| `POST /` | ajoute un stockage : `{storage, type, …champs du type}` → 201 |
| `PUT /{storage}` | modifie : champs modifiables + `reset` (réglages à retirer) + `digest` (refus si la configuration a changé) |
| `DELETE /{storage}?confirm=true&name=<id>` | retire de la configuration (les fichiers restent sur le disque) |

## Types gérés et champs
Un champ qui ne concerne pas le type, ou qui n'est pas modifiable, est refusé (**422**), jamais ignoré. Champs communs :
`content` (liste, filtrée selon le type), `nodes` (liste), `disable`, et `prune_backups` / `max_protected_backups` pour dir, nfs, cifs, cephfs.

| Type | À la création seulement | Modifiables en plus |
|---|---|---|
| `dir` | `path`, `create_base_path` | `shared` |
| `nfs` | `server`, `export` | `options` |
| `cifs` | `server`, `share` | `username`, `password`*, `domain`, `smbversion`, `subdir`, `options` |
| `lvm` | `vgname` | `shared`, `saferemove` |
| `lvmthin` | `vgname`, `thinpool` | |
| `zfspool` | `pool` | `blocksize`, `sparse`, `mountpoint` |
| `iscsi` | `portal`, `target` | |
| `cephfs` | (`monhost` obligatoire) | `monhost`, `username`, `fs_name`, `subdir`, `fuse`, `keyring`* |
| `rbd` | `pool` | `monhost`, `username`, `krbd`, `keyring`*, `namespace` |

\* secret : jamais renvoyé ; `GET` indique seulement `secrets_set`. `reset` accepte : `nodes`, `options`, `prune_backups`, `domain`, `subdir`, `max_protected_backups`, `namespace`.

Le type `pbs` est traité dans un lot à part (sa clé de chiffrement n'est affichée qu'une fois par Proxmox).

## Garde-fous
- Chaque champ a sa regex (`fullmatch`) : pas d'espace, de `..`, de `//` ni de saut de ligne dans un chemin ; `nodes` et `monhost` validés élément par élément.
- Suppression : `confirm=true` **et** le nom exact du stockage, vérifiés côté serveur. Kaji ne vérifie **pas** si des machines utilisent encore le stockage.
- Ajout : refus (409) si l'identifiant existe déjà, vérifié chez Proxmox au moment de l'appel.
- Les erreurs Proxmox sont traduites (502/504) sans message brut ; les erreurs de validation ne renvoient jamais la valeur saisie.
