# Alimentation avancée d'une VM et conversion en modèle (lot #146)

> **Validé en réel le 2026-11-09 (PC A, VM 115 et clone 117)** : voir « Validé en réel » en bas de page, avec les écarts (#201 à #204, #206).
> Fichiers : `routers/power.py`, `tests/test_power.py`, `components/PowerActions.tsx`
> (page Machine), `lib/types/alimentation-vm.ts`. Les routes ont la forme de la route générique `{action}` de `actions.py` (`ORDER = 90`) :
> `power.py` garde l'ordre par défaut et passe avant (un test vérifie qu'aucune n'est masquée).

Préfixe : `/api/connections/{id}/guests/{node}`. Droits Proxmox : `VM.PowerMgmt` sur `/vms/{vmid}` (reset, suspend, resume) ; en plus
`VM.Config.Disk` et `Datastore.AllocateSpace` pour l'hibernation ; `VM.Allocate` pour le modèle. L'état de la machine est **relu chez Proxmox**
(`status/current`) à chaque action ; un refus n'émet **aucune** écriture. Corps JSON : champs inconnus ignorés, booléens stricts (`"true"` → 422).

| Route | Corps | Conditions | Appel Proxmox |
|---|---|---|---|
| `GET /qemu/{vmid}/power` | — | lecture : `{status, qmpstatus, paused}` (liste blanche) | `GET …/status/current` |
| `POST /qemu/{vmid}/reset` | `{confirm: true}` | VM en marche, pas en pause | `POST …/status/reset` |
| `POST /qemu/{vmid}/suspend` | — | VM en marche, pas en pause | `POST …/status/suspend` |
| `POST /qemu/{vmid}/hibernate` | `{confirm: true, statestorage?}` | VM en marche, pas en pause ; `statestorage` = identifiant de stockage valide (`fullmatch`, sinon 422) | `POST …/status/suspend` avec `todisk=1` |
| `POST /qemu/{vmid}/resume` | — | `status` ou `qmpstatus` = `paused` / `suspended` | `POST …/status/resume` |
| `POST /{qemu\|lxc}/{vmid}/template` | `{confirm: true, name}` | voir ci-dessous | `POST …/template` |

Réponse : `202 {upid, node, action}` (`upid` vaut `null` pour un LXC : Proxmox ne renvoie pas de tâche). Audit : `reset`, `suspend`, `hibernate`, `resume`,
`guest-template` (succès, refus et erreurs).

## Convertir en modèle : irréversible
Refus, dans cet ordre, **sans aucun appel d'écriture** : machine de `KAJI_PROTECTED_VMIDS` (403, même confirmée) · `confirm` absent (400) ·
machine non arrêtée, relue chez Proxmox (409 ; état illisible : 502) · verrouillée par Proxmox (`lock` : VM hibernée sur disque, sauvegarde, migration ; 409) · déjà un modèle (409) · option `protection` (409) · nom retapé différent du nom réel, casse et espaces
compris (400 ; `name` pour une VM, `hostname` pour un LXC). Chez Proxmox, les disques d'une VM sont **renommés `base-…`** et la machine ne démarre plus
(elle se clone).

## Démarrer un modèle (route générique `…/{type}/{vmid}/start`, `routers/actions.py`)
Avant un `start`, Kaji relit la config (`GET …/config`) : si `template` vaut `1`, **409** « Une machine modèle ne démarre pas : clone-la, puis démarre la
copie », **aucune écriture**, audit `start` en erreur (« machine modèle »). Config illisible : le démarrage n'est pas bloqué, Proxmox tranche. Les autres
actions (`shutdown`, `reboot`, `stop`) ne lisent rien de plus. Ticket #204.

**Déjà en marche (ticket #291)** : avant la config, un `start` relit aussi l'état (`GET …/status/current`). Machine `running` : **409** « La machine est déjà en
marche » ; VM en pause (`running` + `qmpstatus` `paused` ou `suspended`) : **409** « La VM est en pause : reprends-la au lieu de la démarrer ». **Aucune écriture**, audit
`start` en erreur (« machine déjà en marche » / « machine en pause »). Arrêtée, hibernée (verrou `suspended`), état vide ou illisible : le démarrage passe. Avant ce correctif,
Kaji répondait 202 puis la tâche échouait chez Proxmox (« already running », constaté en réel le 2026-11-12).
**Validé en réel le 2026-11-12** (VM 115) : démarrée (202), second démarrage 409 « La machine est déjà en marche », VM suspendue puis démarrage 409 « La VM est en pause : reprends-la… », reprise, arrêt.

## Interface
Page Machine : « Suspendre », « Hiberner », « Réinitialiser » (VM en marche), « Reprendre » (VM en pause), « Convertir en modèle… » (machine arrêtée, VM ou
LXC, nom à retaper). **Une VM suspendue est `paused` dans la liste des machines** (alors que `/power` dit `running` + `qmpstatus: paused`) : la carte affiche
« En pause » et l'écran propose **Reprendre** et **Forcer** (ni Redémarrer ni Éteindre) ; les cartes de la liste, la page du nœud, le filtre d'état et la
palette gèrent aussi `paused` (ticket #201). La liste de Proxmox met 6 à 10 s à changer d'état : la page se rafraîchit à 0, 4, 9 et 15 s après une action.
Les fenêtres de confirmation sont rendues dans `document.body` (portail) : dans la carte d'en-tête, leurs boutons passaient sous la carte Notes (#202) ;
Entrée dans le champ du nom valide. Le texte de la conversion distingue VM (« disques ») et conteneur (« volume », #206). 

**Dans les cartes de la liste (lot #318, frontend seul)** : chaque carte d'une VM en marche, en pause ou d'une machine arrêtée a un repli « Plus d'actions » qui réutilise `PowerActions` (`fromList`) : suspendre, hiberner, réinitialiser (VM en marche), reprendre (VM en pause), convertir en modèle (machine arrêtée), avec les mêmes confirmations et garde-fous serveur. L'état vient de la liste : **aucune lecture `/power` par carte** (pas de requête de plus toutes les 8 s par machine). Un clic sur le repli n'ouvre pas la page de la machine.

La page d'un **modèle** a une zone « Zone dangereuse » avec **Supprimer le modèle** (même fenêtre et même nom à retaper que pour une machine ordinaire,
`DELETE …/guests/{node}/{type}/{vmid}`, #203).

## Validé en réel (2026-11-09, PC A, VM 115 sans système et clone jetable 117, LXC jetable 119)
- **États observés** : VM suspendue = `GET …/power` renvoie `{"status":"running","qmpstatus":"paused","paused":true}` ; en revanche la **liste des machines**
  (`GET /guests`) renvoie `status: "paused"`, d'où l'écart **#201** (l'interface n'affiche alors aucun bouton, « Reprendre » introuvable : la reprise a
  été faite par l'API). VM hibernée : `status` et `qmpstatus` = `stopped` (verrou `suspended` non exposé par Kaji).
- **suspend** (confirmation, `qmsuspend`), **resume** (`qmresume`, API), **reset** (confirmation, `qmreset`, la VM reste en marche) : réussis.
- **hibernate** avec `confirm` : **réussi** (tâche `qmsuspend` ok, VM arrêtée) alors qu'on attendait un refus faute d'agent invité ; « Démarrer » a consommé
  l'état (`qmstart` ok). Aucun volume d'état résiduel (`vm-115-state-*`) après le démarrage.
- **Refus sans tâche** : `reset` / `hibernate` sans `confirm` ou `confirm: false` : 400 ; `reset` et `suspend` sur une VM arrêtée : 409 (« La VM doit être en
  marche (et non en pause) pour être réinitialisée / suspendue »).
- **Conversion en modèle** : refus sans `confirm` (400), nom de casse différente, vide ou absent (400 « Le nom de la machine ne correspond pas »), machine en
  marche (409), déjà un modèle (409 « La machine est déjà un modèle »), chaque fois sans tâche. Conversion VM 117 : `qmtemplate` ok, disque
  `local-lvm:base-117-disk-0`, badge « Modèle ». **LXC 119** : toast « convertie en modèle » sans erreur, disque `base-119-disk-0`, tâche `vztemplate` ok.
  `template: true` n'apparaît dans `/guests` qu'une dizaine de secondes après la tâche.
- **Démarrer un modèle** : Kaji l'acceptait (202) et Proxmox échouait (« you can't start a vm if it's a template ») : **corrigé (#204)**, voir « Démarrer un modèle » plus haut.
- **Écarts d'interface** : fenêtre de conversion dont les boutons sont masqués sous la carte Notes (**#202**) ; pas de bouton « Supprimer » sur un modèle
  (**#203**, suppression faite par `DELETE …/guests/{node}/{type}/{vmid}?confirm=true&name=…`) ; texte « disques d'une VM » pour un LXC (**#206**).
- Audit : `start`, `suspend`, `resume`, `reset`, `hibernate`, `stop`, `guest-template` (refus en erreur, succès en `started`), sans secret.

## Non validé en réel
- refus de la conversion sur une VM verrouillée (`lock: suspended` après hibernation) : non essayé (risque de convertir la 115 de façon irréversible si le
  contrôle échouait ; Kaji n'expose pas le verrou) ;
- les machines de `KAJI_PROTECTED_VMIDS` (105, 108, 116) : couvertes par les tests seulement ;
- l'hibernation d'une VM avec un vrai système et un stockage d'état choisi (`statestorage`).
