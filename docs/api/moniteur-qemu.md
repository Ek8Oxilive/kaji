# Moniteur QEMU d'une VM, en lecture seule (lot #273)

> **Essai réel le 2026-11-11 (PC B, Proxmox 9.1.9, VM 115) : Proxmox refuse le moniteur au token de Kaji** (voir « Constaté en réel »). Les garde-fous de Kaji sont validés ; la fonction elle-même ne marche pas avec ce token. Fichiers :
> `routers/monitor.py`, `monitorspec.py`, `tests/test_monitor.py`, `components/MonitorTab.tsx` (onglet « Moniteur » de la page Machine, VM seulement),
> `lib/types/moniteur.ts`. La route a la forme de la route générique `{action}` de `actions.py` (`ORDER = 90`) : `monitor.py` garde l'ordre par défaut et passe avant.

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/guests/{node}/qemu/{vmid}/monitor` | commandes autorisées (liste blanche, avec libellé) ; n'appelle pas Proxmox |
| `POST …/qemu/{vmid}/monitor` `{command}` | exécute une commande autorisée ; `200 {command, output, truncated}` ; écrit `POST /nodes/{node}/qemu/{vmid}/monitor` |

Droit Proxmox : `VM.Monitor` sur `/vms/{vmid}`. Audit : `qemu-monitor` (**la commande**, jamais la sortie ; refus et erreurs compris).

## Garde-fous
- **Aucune commande libre.** La commande (espaces normalisés) doit figurer **exactement** dans la liste blanche de `monitorspec.py` : des commandes `info …` **sans
  argument** (status, version, name, uuid, kvm, cpus, hotpluggable-cpus, numa, memory-devices, balloon, block, blockstats, network, pci, usb, chardev, vnc,
  iothreads, migrate, snapshots, roms). Sinon **422**, audit « commande hors liste blanche » (la valeur refusée n'est pas recopiée), **aucun appel à Proxmox**.
  Absentes volontairement : `quit`, `stop`, `cont`, `system_*`, `drive_*`, `device_*`, `migrate` (hors `info`), `savevm`, `loadvm`, `human-monitor-command`,
  `object_add`, `info registers`, `info mtree`, `info qtree`, `info mem`, `info tlb`, `info qom-tree`…
- La VM doit être **en marche** (`status/current` relu chez Proxmox ; une VM suspendue est `running` + `paused` : elle répond) ; sinon **409**, état illisible : **502**.
- Corps : `command` seul, 100 caractères au plus ; champs inconnus ignorés, jamais transmis.
- Sortie nettoyée : caractères de contrôle retirés, `\r\n` normalisés, **tronquée à 65 536 caractères** (`truncated: true`).
- Conteneur LXC : pas de moniteur (la route générique répond 422).

## Interface
Onglet « Moniteur » (VM) : liste des commandes autorisées (« info status — État d'exécution »), bouton Exécuter (grisé si la VM n'est pas en marche), sortie en
lecture seule.

## Constaté en réel (2026-11-11, Proxmox 9.1.9, VM 115 démarrée puis arrêtée de force)
- **Proxmox répond 403 aux 21 commandes** (`POST /nodes/enzo/qemu/115/monitor`), alors que le token a `PVEVMAdmin` sur `/vms`, `Sys.Modify` et `Sys.Console` sur `/`.
  **`VM.Monitor` n'existe plus** : aucun des 22 rôles, `Administrator` compris, ne le contient. Le moniteur semble donc réservé à `root@pam`, comme `keyctl` et `fuse`
  d'un conteneur. Kaji répond **403** avec le message fixe « Proxmox refuse le moniteur QEMU au token de Kaji … Utilise `qm monitor` sur le nœud, dans la console. »
  (sans le message brut de Proxmox) ; audit `qemu-monitor` en erreur avec le même texte. Un 403 sur la lecture de l'état reste un 502 générique.
- **Garde-fous de Kaji validés** (par l'API, VM arrêtée) : 422 pour `quit`, `system_powerdown`, `info block;quit`, `info registers`, commande vide, `drive_del scsi0`,
  `human-monitor-command` (audit « commande hors liste blanche », aucun appel à Proxmox) ; 409 VM arrêtée ; 422 pour un conteneur ; liste de 21 commandes ;
  onglet : avertissement « La VM doit être en marche » et bouton grisé quand la VM est arrêtée ; VM en marche : l'erreur s'affiche dans l'onglet.
- **Jamais vu en réel** : la sortie d'une commande (aucune n'a réussi). Les noms de commandes viennent de la documentation de QEMU.
- Pour que la fonction serve, il faudrait un token `root@pam` : **à ne pas faire** (règle du dépôt : pas de token `root@pam`). À garder tel quel, ou à retirer si Enzo préfère.


## Commande à copier (frontend seul, décision d'Enzo du 2026-11-12 : on GARDE le moniteur)
Proxmox 9 refuse le moniteur au token de Kaji (403). L'onglet « Moniteur » affiche donc, sous la liste de commandes, ce qui se lance dans la **console du nœud** (page Nœud, droit `Sys.Console`, avec les droits du nœud) : `qm monitor <vmid>` (ouvre le moniteur interactif, invite `qm>`) puis la commande choisie à taper dedans (`quit` pour sortir). **Constaté en réel par Enzo le 2026-11-13 : `echo '<commande>' | qm monitor <vmid>` ouvre le moniteur mais n'affiche AUCUNE réponse : ce one-liner a été retiré. La saisie dans le moniteur interactif est validée : `info status` répond `VM status: running` (et `ERROR: VM <id> not running` si la VM est arrêtée).** La commande vient de la liste blanche `info …` du serveur et l'identifiant est celui de la machine ouverte ; rien n'est envoyé d'ici, aucune route nouvelle.
