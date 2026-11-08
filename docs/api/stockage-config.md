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
| `pbs` | `server`, `datastore`, `encryption_key` (`"autogen"`), `master_pubkey` | `username`, `password`*, `fingerprint`, `namespace`, `port` |
| `rbd` | `pool` | `monhost`, `username`, `krbd`, `keyring`*, `namespace` |

\* secret : jamais renvoyé ; `GET` indique seulement `secrets_set`. `reset` accepte : `nodes`, `options`, `prune_backups`, `domain`, `subdir`, `max_protected_backups`, `namespace`.

## Proxmox Backup Server (`pbs`)
- À la création : `server`, `datastore`, `username` (ou jeton `user@realm!jeton`) et `password` sont obligatoires ; `content` ne peut être que `backup`.
- **Chiffrement** : `encryption_key: "autogen"` fait générer une clé par Proxmox. Elle est renvoyée **une seule fois**, dans la réponse du `POST`
  (`encryption_key`, en-tête `Cache-Control: no-store`) ; Kaji ne la journalise pas et ne peut plus la relire (`GET` donne seulement `encrypted: true`).
  Sans cette clé, les sauvegardes chiffrées sont irrécupérables. Elle n'est **pas modifiable** après la création (la changer rendrait les anciennes sauvegardes illisibles).
  `master_pubkey` (clé RSA publique, base64) exige le chiffrement. Une clé fournie par l'appelant n'est pas acceptée : seulement `autogen`.
- `fingerprint` : SHA-256 du certificat (`AB:CD:…`, 32 octets), obligatoire en pratique si le PBS a un certificat auto-signé. `namespace` : jusqu'à 7 niveaux (`prod/vm`).
- Lecture des sauvegardes d'un stockage PBS (`GET …/storage/{storage}/content`) : chaque volume porte `verification` (`ok`, `failed`, `none` ou `null`) et `encrypted`.
  Les tâches de vérification elles-mêmes se planifient sur le PBS, pas dans Proxmox VE : Kaji n'en crée pas.

## Garde-fous
- Chaque champ a sa regex (`fullmatch`) : pas d'espace, de `..`, de `//` ni de saut de ligne dans un chemin ; `nodes` et `monhost` validés élément par élément.
- Suppression : `confirm=true` **et** le nom exact du stockage, vérifiés côté serveur. Kaji ne vérifie **pas** si des machines utilisent encore le stockage.
- Ajout : refus (409) si l'identifiant existe déjà, vérifié chez Proxmox au moment de l'appel.
- Les erreurs Proxmox sont traduites (502/504) sans message brut ; les erreurs de validation ne renvoient jamais la valeur saisie.
