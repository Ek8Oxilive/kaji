# Disques d'un nœud (M11, lecture seule)

Deux routes, protégées par la session Kaji, qui n'envoient que des `GET` à Proxmox (droit `Sys.Audit`).

## `GET /api/connections/{id}/nodes/{node}/disks`
Rubriques `disks`, `lvm`, `lvmthin`, `directory`, `zfs`, chacune `{state: ok|forbidden|error, data}` ; `502` seulement si toutes échouent.
- `disks` : disques physiques avec leurs `partitions` (une partition n'est rattachée qu'au disque dont elle porte exactement le préfixe : `sda1` à `sda`, pas `sdab1`).
  `wearout` : pourcentage d'usure restante (100 = neuf), `null` si Proxmox répond `N/A`.
- `lvm` : groupes de volumes (taille, libre, nombre de volumes, périphériques). `lvmthin` : pools (taille, utilisé, métadonnées).
- `directory` : répertoires montés par Proxmox. `zfs` : pools (taille, alloué, libre, santé, fragmentation).
Les numéros de série et les WWN ne sont pas repris.

## `GET /api/connections/{id}/nodes/{node}/disks/smart?disk=/dev/sda`
`{health, type: "text"|"ata", wearout, attributes[], text}`. `disk` ancré `^/dev/[A-Za-z0-9]{1,30}$` (422 sinon : ni `..`, ni sous-dossier).
`attributes` (disques ATA) : `id, name, value, worst, threshold, raw, failing` ; `text` (NVMe) borné à 12 000 caractères et jamais interprété.

## Écriture (destructive)
Droit `Sys.Modify` sur `/nodes` (plus `Datastore.Allocate` sur `/storage` pour `add_storage`) : fonction `node-disks-write` de la page Accès.
Toutes en `POST …/nodes/{node}/disks/<action>`, réponse `202 {upid, node}`, corps commun `{confirm: true, type_name: "…"}`. **Rien n'est supprimé** :
la suppression de volumes existants n'est pas dans ce lot (aucune route `DELETE`, testé).

| Route | Corps (en plus) | Texte à retaper |
|---|---|---|
| `initgpt` | `disk` | le disque (`/dev/sdb`) |
| `wipe` (→ `PUT wipedisk`) | `disk` | le disque |
| `lvm`, `lvmthin` | `name`, `device`, `add_storage` | le nom |
| `directory` | `name`, `device`, `filesystem` (`ext4`/`xfs`), `add_storage` | le nom |
| `zfs` | `name`, `devices[]` (1 à 12), `raidlevel`, `compression` (`on/off/lz4/zstd`), `ashift` (9–16), `add_storage` | le nom |

**État relu chez Proxmox à chaque action** (illisible : `502`, rien n'est écrit). Un disque est :
- `free` (ni utilisation ni partition) : seul état accepté pour initialiser en GPT ou créer un volume ;
- `leftover` (partitions toutes inutilisées) : accepté pour **effacer** seulement ;
- `busy` (système, LVM, ZFS, monté, partition de démarrage, **OSD Ceph**, partition utilisée) : `422`, **jamais**, quelles que soient les confirmations.

Autres refus : disque inconnu `404` ; nom réservé (`pve`, `rpool`, `root`, `swap`, `data`, `vm`, `local`, `local-lvm`) `422` ; nom déjà pris `409` ;
règles RAID ZFS (`single` = 1 disque, `mirror` ≥ 2, `raid10` ≥ 4 et pair, `raidz` ≥ 3, `raidz2` ≥ 4, `raidz3` ≥ 5) `422` ; noms refusés par ZFS (`mirror…`, `raidz…`,
`c0…`) `422` ; pas de `confirm` / texte retapé différent `400`. Motifs ancrés (`disk`, `name`). Les champs inconnus du corps sont ignorés, jamais transmis.
`add_storage` (défaut non) crée le stockage **pour tout le cluster**. Chaque action est auditée (`disk-initgpt`, `disk-wipe`, `disk-<type>-create`).
