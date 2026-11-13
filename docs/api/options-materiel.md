# Options fines du matériel : disque, carte réseau, CPU (lot #377)

Onglet « Matériel » de la page Machine : un bouton « Options… » par disque (VM), par carte réseau (VM et conteneur) et pour le processeur (VM).
Noms, énumérations et bornes lus dans le schéma officiel de Proxmox 9 (`apidoc.js`). Liste blanche : une option inconnue est ignorée, jamais transmise.

| Route | Corps (tous les champs sont facultatifs) |
|---|---|
| `PATCH …/guests/{node}/qemu/{vmid}/disks/{key}/options` | `cache`, `discard`, `aio`, `iothread`, `ssd`, `backup`, `ro`, `replicate`, `detect_zeroes`, `mbps_rd`, `mbps_wr`, `iops_rd`, `iops_wr` (et `mbps`, `iops`), `clear`, `confirm`, `dry_run` |
| `PATCH …/guests/{node}/{qemu\|lxc}/{vmid}/nets/{key}/options` | `rate` (Mo/s), `mtu`, `queues` (VM), `link_down`, `trunks` (liste de VLAN ou de plages), `clear`, `confirm`, `dry_run` |
| `PATCH …/guests/{node}/qemu/{vmid}/cpu-options` | `cpuunits`, `cpulimit`, `affinity`, `hugepages`, `clear`, `confirm`, `dry_run` |

## Comment ça écrit
- La chaîne du périphérique est **réécrite en ne touchant qu'aux options demandées** : le volume, la taille, la MAC, le bridge, le VLAN et les options que Kaji ne gère pas sont conservés tels quels ; une option remplacée garde sa place. `clear` retire une option (retour au défaut de Proxmox).
- `PUT …/config` avec le `digest` de la configuration lue (refus si elle a changé), puis **relecture** : si Proxmox n'a pas enregistré (réponse OK sans écriture), 502. Les nombres sont comparés comme des nombres (Proxmox peut renvoyer `4.0` pour `4`).
- Machine en marche : le changement est « en attente » jusqu'au prochain démarrage (bandeau de l'onglet).
- Audit `hw-options` (succès, refus, erreur), sans nom de volume ni MAC. Machine de `KAJI_PROTECTED_VMIDS` : **refusée même confirmée**. `dry_run` : aucun appel d'écriture, renvoie le résultat et les risques.

## Règles et risques (décidés par le serveur)
- **Disque** : CD/DVD et lecteur cloud-init refusés ; `iothread` seulement sur `virtio` ou `scsi` avec `virtio-scsi-single` ; `ssd` pas sur `virtio` ; `mbps` ne se combine pas avec `mbps_rd` / `mbps_wr`, ni `iops` avec `iops_rd` / `iops_wr`. `confirm` exigé pour `cache=unsafe`, `cache=writeback` (perte de données possible) et `backup=0` (disque exclu des sauvegardes).
- **Carte réseau** : `mtu` et `queues` seulement sur une carte `virtio` (VM) ; `queues` refusé sur un conteneur ; `mtu` de 1 à 65520 (VM) ou de 64 à 65535 (conteneur) ; `trunks` : VLAN de 1 à 4094, plages dans l'ordre, sans doublon, chiffres ASCII. `link_down=true` exige `confirm` (la machine perd ce réseau) ; `link_down=false` retire l'option.
- **CPU** : `cpuunits` 1 à 262144, `cpulimit` 0 à 128, `affinity` (ex. `0,5,8-11`, refusée si un cœur dépasse ceux du nœud, relus par `GET /nodes/{n}/status`), `hugepages` `any`, `2` ou `1024`. `confirm` exigé pour `hugepages` (la machine ne démarre pas sans pages réservées) et `affinity`.
- Un nombre n'est jamais un booléen ni un texte (`"5"`, `true` refusés), un booléen n'est jamais un nombre.

## Non géré (volontairement)
Drapeaux du processeur (`cpu=…,flags=…`), `bps` en octets, rafales (`*_max`), `serial`, `wwn`, `product`, `vendor`, options des disques de conteneur (`rootfs`, `mpN`), `affinity` d'un conteneur.

## Validé en réel (2026-11-13, VM 115 arrêtée, tout remis à l'identique)
- **Disque `scsi0`**, par l'interface : `cache=none`, `discard=on`, `iothread=1`, `ssd=1`, `mbps_rd=50` écrits et relus par Proxmox (`format=raw` conservé) ; par l'API : `iops_rd` / `iops_wr`, `cache=unsafe` avec `confirm`, retour au défaut par `clear` ; refus constatés (`backup=0` et `cache=unsafe` sans `confirm` : 400, `mbps` avec `mbps_rd` : 422) ; l'aperçu `dry_run` n'écrit rien.
- **Carte réseau `net0`** (ajoutée pour l'essai puis retirée), par l'interface : `rate=20`, `mtu=1500`, `queues=2`, `trunks=10;20-30` écrits, MAC conservée ; par l'API : `link_down` (confirm exigé, puis retiré avec `false`), refus (`mtu` 70000, plage de VLAN à l'envers, demande vide), retour au défaut par `clear`.
- **CPU**, par l'interface : `cpuunits=2000` et `cpulimit=0.5` écrits ; le flux « case Risque : J'accepte » est vu à l'écran.
- **Trouvé en réel : `affinity` ET `hugepages` sont réservés à `root@pam`** : Proxmox répond 500 « only root can set 'affinity' config » (et `'hugepages'`) au jeton de Kaji. Kaji répond donc **403** avec le message fixe « Proxmox réserve cette option à root@pam (affinity, hugepages) : elle est refusée au token de Kaji » (jamais le message brut) et **ne propose plus ces deux champs** dans la fenêtre du processeur ; l'API les valide toujours (cœurs du nœud, format) mais Proxmox tranche.
- **Jamais essayé en réel** : une VM en marche (changement « en attente »), un conteneur (carte `lxc`), `aio`, `ro`, `replicate`, `detect_zeroes`, `queues` sur un modèle non virtio (refusé par Kaji avant tout envoi), une machine protégée (tests seulement). Tests : `backend/tests/test_hw_options.py` (faux Proxmox strict qui applique la configuration, vérifie le `digest` et refuse toute option hors schéma).
