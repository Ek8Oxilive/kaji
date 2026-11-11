# Périphériques d'une VM : affichage, ports série, audio, RNG, watchdog (lot #225)

> **Non validé en réel** (PC B, faux Proxmox strict). Fichiers : `routers/devices.py`, `devicespec.py`, `tests/test_devices.py`, `components/DevicesTab.tsx`
> (onglet « Périphériques » de la page Machine, VM seulement), `lib/types/peripheriques.ts`. Passthrough PCI/USB, TPM et disque EFI : lot suivant.

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/guests/{node}/qemu/{vmid}/devices` | périphériques actuels décomposés en champs + changements en attente (`pending`) |
| `PATCH …/qemu/{vmid}/devices` | modifier ou retirer des périphériques (liste blanche) ; écrit `PUT …/qemu/{vmid}/config` |

Droit Proxmox : `VM.Config.HWType` sur `/vms/{vmid}` (carte d'affichage, audio, watchdog, RNG, ports série). Audit : `devices` (succès, refus, erreurs). Les
changements s'appliquent **au prochain démarrage** de la VM.

## Champs
| Champ | Validation | Paramètre Proxmox |
|---|---|---|
| `vga` | `{type, memory, clipboard}` ; `type` ∈ `std, vmware, virtio, virtio-gl, qxl, qxl2-4, cirrus, serial0-3, none` ; `memory` entier strict 4 à 512 ; `clipboard` = `vnc`. Fusionné avec l'existant ; les **propriétés inconnues sont conservées** (refus si l'une est illisible) | `vga=type=…,memory=…,clipboard=vnc` |
| `serial0` … `serial3` | **`"socket"` seulement** : jamais un `/dev/…` de l'hôte | `serialN=socket` |
| `audio` | `{device, driver?}` ; `device` ∈ `ich9-intel-hda, intel-hda, AC97` ; `driver` ∈ `spice, none` | `audio0=device=…,driver=…` |
| `rng` | `{max_bytes?, period?}` ; entiers stricts 0 à 1 000 000 et 1 à 3 600 000 ; **la source est toujours `/dev/urandom`** (`source` envoyé est ignoré) | `rng0=source=/dev/urandom,max_bytes=…,period=…` |
| `watchdog` | `{model, action?}` ; `model` ∈ `i6300esb, ib700` ; `action` ∈ `reset, shutdown, poweroff, pause, debug, none` | `watchdog=model=…,action=…` |
| `clear` | `vga, audio0, rng0, watchdog, serial0-3` | `delete=…` |

## Garde-fous
- Champs inconnus ignorés ; booléens et entiers **stricts** (`"32"` → 422) ; requête sans réglage : 400 ; réglage à la fois modifié et retiré : 422.
- **Périphérique d'hôte posé par root** (`serialN=/dev/ttyS0`, `rng0` sur `/dev/hwrng`) : affiché en lecture seule (`device`, chemin **jamais renvoyé**), **ni réécrit ni retiré** par Kaji (422, « à modifier dans Proxmox »).
- **Confirmation décidée par le serveur** (état relu) : `vga: none` ou `serial0-3` (la console noVNC n'affichera plus rien), sauf si la carte est déjà ainsi.
- **Machine de `KAJI_PROTECTED_VMIDS`** : toute modification refusée (409), même confirmée ; la lecture reste permise.
- `digest` relu et renvoyé (refus de Proxmox si la configuration a changé entre-temps) ; config illisible : 502 ; erreur Proxmox traduite sans fuite.

## Non validé en réel (essais du ticket #225, VM 115 arrêtée)
- l'acceptation par Proxmox de chaque format (`vga=type=vmware,memory=32,clipboard=vnc`, `audio0`, `rng0` avec `source=/dev/urandom`, `watchdog`, `serialN=socket`) ;
- le droit réellement requis (`VM.Config.HWType`) et d'éventuelles restrictions `root@pam` (rng, série) pour le token de Kaji : un 403 sera traduit en 502 générique ;
- la forme de `vga` renvoyée par `GET …/config` (courte `std` ou longue) et les valeurs par défaut affichées ;
- l'interface n'a pas été ouverte dans un navigateur (seul `npm run build` la valide).
