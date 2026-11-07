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

**Écriture** (initialiser GPT, effacer, créer LVM / LVM-thin / répertoire / ZFS) : lot suivant, avec garde-fous (jamais un disque système ni déjà utilisé).
