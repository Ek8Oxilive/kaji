# Moniteur QEMU d'une VM, en lecture seule (lot #273)

> **Non validé en réel au moment du code** (faux Proxmox strict) ; essais réels : voir « Validé en réel » plus bas une fois faits. Fichiers :
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

## Non validé en réel
- l'acceptation par Proxmox de `POST …/monitor` avec le token de Kaji (droit `VM.Monitor`, éventuelle restriction `root@pam`) ;
- la sortie réelle de chaque commande (les noms de commandes viennent de la documentation de QEMU) ;
- l'interface n'a pas été ouverte dans un navigateur au moment du code.
