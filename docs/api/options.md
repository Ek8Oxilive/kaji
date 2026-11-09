# Options d'une VM ou d'un conteneur (onglet « Options » de Proxmox)

> **Rien de ceci n'a été validé en réel** : écrit et testé avec un faux Proxmox qui n'accepte que les paramètres du schéma réel de
> `PUT /nodes/{node}/qemu/{vmid}/config` (relevé par PC A). Les essais réels sont à faire dans le bac à sable (VM 115).

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/guests/{node}/qemu/{vmid}/options` | Options actuelles, décomposées en champs, et changements en attente (`pending`) |
| `PATCH …/options` | Modifier ou retirer des options (liste blanche) |

Fichiers : `routers/options.py`, `optionspec.py`, interface `components/OptionsTab.tsx` (onglet « Options » de la page Machine, VM seulement).
Ce n'est **pas** la route `/config` du matériel : la validation et les risques diffèrent. Les conteneurs LXC sont décrits plus bas (lot #145).

## Lecture

`options` contient, pour chaque réglage, sa valeur ou `null` s'il n'est pas défini (Proxmox applique alors sa valeur par défaut) :
`onboot`, `tablet`, `protection`, `numa`, `localtime`, `acpi`, `kvm`, `freeze` (booléens) ; `startup` (`order`, `up`, `down`) ; `ostype` ;
`agent` (`enabled`, `fstrim_cloned_disks`) ; `hotplug` (liste) ; `description`. `pending` liste les changements en attente (réglages gérés
ici seulement), `reboot_required` vaut `true` s'il y en a. **Aucune autre clé de la configuration n'est renvoyée** (`hookscript`, `args`, `lock`…).

## Modification (`PATCH`)

Corps (tous les champs sont facultatifs, au moins un est obligatoire ; **tout autre champ est ignoré et jamais transmis**) :

| Champ | Validation |
|---|---|
| `onboot`, `tablet`, `protection`, `numa`, `localtime`, `acpi`, `kvm`, `freeze` | booléen JSON strict (pas `"true"`, pas `1`) ; envoyé en `0`/`1` |
| `startup` | `{order, up, down}` : entiers, `order` 0–9999, `up` et `down` 0–86400 s ; au moins un champ. Les valeurs non fournies sont **conservées** (relues chez Proxmox) |
| `ostype` | liste blanche : `other, wxp, w2k, w2k3, w2k8, wvista, win7, win8, win10, win11, l24, l26, solaris` |
| `agent` | `{enabled, fstrim_cloned_disks}` (booléens stricts) ; les **autres propriétés** déjà présentes (`type`, `freeze-fs-on-backup`…) sont conservées telles quelles ; si l'une est illisible, la modification est **refusée** plutôt que de la perdre |
| `hotplug` | liste de `network, disk, cpu, memory, usb, cloudinit`, sans doublon ; liste vide : `0` |
| `description` | 8192 caractères au plus, sans caractère de contrôle (le saut de ligne est permis) |
| `clear` | réglages à **retirer** (`delete=`) : uniquement les 13 ci-dessus ; un réglage ne peut pas être modifié et retiré à la fois (422) |
| `confirm` | booléen strict, jamais transmis à Proxmox |

Le `digest` de la configuration relue est transmis : Proxmox refuse si elle a changé entre-temps. Réponse `200 {"changed": […], "removed": […]}`.
Un corps sans aucun réglage connu : 400, rien n'est appelé.

### Risques : la confirmation est décidée par le serveur

Sans `confirm: true`, **400 « Confirmation requise (…) : raison ; raison »** et rien n'est écrit, d'après l'**état relu chez Proxmox** (jamais une
valeur du navigateur), pour :
- `protection` à faux, ou retirée, **quand la machine est protégée** (elle pourra être supprimée) ;
- `kvm` à faux (machine très lente), `acpi` à faux (arrêt propre impossible), `freeze` à vrai (machine démarrée gelée), si ce n'est pas déjà le cas.

### Protection de Kaji (`KAJI_PROTECTED_VMIDS`)

Pour une machine de cette liste, ces mêmes réglages dangereux sont **refusés (409) même avec `confirm`** : la route ne permet pas de contourner la
protection de Kaji. Les réglages inoffensifs (par exemple `onboot`, ou `protection=true`) restent permis.

### Audit et erreurs

Action `options` (cible `qemu/{vmid}@{node}`) : succès (réglages et valeurs, **sans le texte de la description**), refus et erreur. Configuration
illisible : 502. Erreur de Proxmox : 502 traduit, sans secret.

## Non validé en réel (à essayer dans le bac à sable, VM 115 arrêtée)
- l'acceptation par Proxmox des chaînes construites (`startup=order=1,up=30,down=60`, `agent=enabled=1,fstrim_cloned_disks=1`, `hotplug=disk,network,usb`) ;
- `protection=1` fait refuser la suppression par Proxmox **et** par Kaji ; `protection=0` sans `confirm` : 400 ;
- les changements en attente (`pending`) après un `hotplug` ;
- le `digest` : une configuration modifiée entre la lecture et l'écriture est refusée ;
- la valeur par défaut affichée par l'interface pour un réglage absent (`tablet`, `acpi`, `kvm` à vrai) est une supposition tirée de la documentation de Proxmox.

---

# Options d'un conteneur LXC (lot #145)

> **Non validé en réel**, comme les VM. Fichiers : `routers/options.py` (même fichier), `lxcoptionspec.py`, `components/LxcOptionsTab.tsx`
> (onglet « Options » de la page Machine, conteneurs). Faux Proxmox strict sur `PUT /nodes/{node}/lxc/{vmid}/config`.

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/guests/{node}/lxc/{vmid}/options` | Options actuelles, `unprivileged` (lecture seule) et changements en attente |
| `PATCH …/lxc/{vmid}/options` | Modifier ou retirer des options (liste blanche) |

`options` : `onboot`, `protection`, `console` (booléens) ; `startup` (`order`, `up`, `down`) ; `features` (`nesting`, `fuse`, `keyctl`, `mount` : liste
parmi `nfs`, `cifs`) ; `ostype` ; `cmode` ; `tty` ; `timezone` ; `description`. Valeur `null` : non défini. Aucune autre clé n'est renvoyée
(`hookscript`, `lock`, `lxc.*`, `rootfs`…).

## Modification

Mêmes règles que pour les VM (booléens stricts, champs inconnus ignorés, `clear` → `delete=` en liste blanche, `digest`, corps vide : 400, audit
`options`, protection de Kaji). En plus :

| Champ | Validation |
|---|---|
| `features` | `{nesting, fuse, keyctl, mount}` : booléens stricts, `mount` = liste sans doublon de `nfs`, `cifs` (`[]` retire `mount`). Au moins un champ. Les **autres propriétés** déjà présentes (`mknod`, `force_rw_sys`…) sont **conservées** ; si l'une est illisible, ou si le résultat serait vide, la modification est **refusée** |
| `ostype` | `debian, devuan, ubuntu, centos, fedora, opensuse, archlinux, alpine, gentoo, nixos, unmanaged` |
| `cmode` | `shell`, `console` ou `tty` |
| `tty` | entier de 0 à 6 (pas de texte, pas de booléen) |
| `timezone` | `host` ou un fuseau `Zone` / `Zone/Ville` (lettres, chiffres, `_`, `+`, `-`) ; pas de `..`, d'espace ni de `/` initial |
| `clear` | `onboot, startup, protection, features, ostype, console, cmode, tty, timezone, description` |

- **`unprivileged` et `arch` ne sont pas modifiables : les fournir donne 422** (quel que soit le reste de la demande), sans aucun appel.
- **Confirmation décidée par le serveur** : seulement `protection` retirée d'un conteneur protégé. Un conteneur de `KAJI_PROTECTED_VMIDS` refuse
  de perdre sa protection **même avec `confirm`** (409).
- **`keyctl`, `fuse` et `mount` sont réservés à `root@pam`** (essai réel de PC A, 2026-11-08 : `nesting` passe, `keyctl` et `fuse` donnent « Droits
  insuffisants », `mount` très probablement aussi). Quand Proxmox répond 403 à une écriture qui contient l'un d'eux (même pour le retirer), Kaji
  (ou dont la chaîne `features` renvoyée les contient : un conteneur qui les a déjà, même pour changer `nesting` ; ou `clear: [features]` sur un tel conteneur) répond **403** avec un message fixe (« Proxmox réserve keyctl, fuse et mount à root@pam : le token de Kaji ne peut pas les modifier. Fais-le dans
  l'interface de Proxmox. »), sans valeur saisie ni message brut de Proxmox, et l'audite (`options`, erreur, même texte). Proxmox refuse la demande
  **en entier** : une écriture combinée (démarrage + fuseau + `keyctl`) n'applique rien. Un 403 sur une écriture sans ces trois réglages, ou sur une
  lecture, reste un 502 générique. La **lecture** de ces réglages n'est pas touchée. L'interface les affiche en lecture seule avec une note ;
  `nesting` reste modifiable.

## Non validé en réel (à essayer sur un LXC jetable, par exemple 118)
- l'acceptation par Proxmox de `features=nesting=1,fuse=0,keyctl=1,mount=nfs;cifs`, de `startup=order=1,up=2,down=3` et de `timezone=host` ;
- le 403 explicite sur `keyctl` / `fuse` (lot #164 : faux Proxmox seulement) et le refus de `mount` (supposé, jamais observé) ;
- les valeurs par défaut affichées pour un réglage absent (`console` actif, tous les `features` désactivés) : tirées de la documentation, pas observées ;
- l'interface n'a pas été ouverte dans un navigateur (seul `npm run build` la valide).
