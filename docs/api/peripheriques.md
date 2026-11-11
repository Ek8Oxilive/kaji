# Périphériques d'une VM : affichage, ports série, audio, RNG, watchdog (lot #225)

> **Validé en réel le 2026-11-10** sur la VM 115 (arrêtée), par l'interface : `vga=vmware`, `serial0=socket`, `audio0` (`ich9-intel-hda`), `rng0` (`/dev/urandom`), `watchdog` (`i6300esb`) écrits en une demande, relus à l'identique, puis tous retirés (`delete`) : état d'origine. Refus constatés : port série hôte (422), type d'affichage hors liste (422), `vga: none` sans `confirm` (400), demande vide (400), conteneur (405). Un champ `source` envoyé au RNG est ignoré (la source reste `/dev/urandom`).
> Fichiers : `routers/devices.py`, `devicespec.py`, `tests/test_devices.py`, `components/DevicesTab.tsx`, `lib/types/peripheriques.ts`. Passthrough PCI / USB : voir `docs/api/passthrough.md` ; TPM et disque EFI : lot suivant.

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

## Pas encore essayé en réel
- `vga` avec `memory` et `clipboard`, `audio0` avec `driver`, `rng0` avec `max_bytes` / `period`, `watchdog` avec `action`, `serial1` à `serial3` ;
- appliquer `vga: none` ou `vga: serialN` avec `confirm` (console graphique perdue : volontairement non essayé sur la VM d'essai) ;
- relecture d'un réglage posé par root avec une source de l'hôte (aucun sur ce cluster : testé seulement avec le faux Proxmox) ;
- le comportement d'une VM **en marche** (les changements s'appliquent au prochain démarrage ; la VM 115 est restée arrêtée).

## Constaté en réel (2026-11-10)
- Proxmox accepte les formats `vga=type=vmware`, `serial0=socket`, `audio0=device=ich9-intel-hda`, `rng0=source=/dev/urandom`, `watchdog=model=i6300esb` et `delete=vga,audio0,rng0,watchdog,serial0` ; le token de Kaji a le droit de les écrire.
- Après l'écriture, la relecture donne `vga` = `vmware` et les autres réglages à l'identique ; VM arrêtée : le changement est direct, `pending` reste vide.
- Interface ouverte et utilisée dans le navigateur (onglet, formulaire, enregistrement, relecture).

