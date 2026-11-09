# Alimentation avancée d'une VM et conversion en modèle (lot #146)

> **Non validé en réel** (PC B, faux Proxmox strict). Fichiers : `routers/power.py`, `tests/test_power.py`, `components/PowerActions.tsx`
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

## Interface
Page Machine : « Suspendre », « Hiberner », « Réinitialiser » (VM en marche), « Reprendre » (VM en pause, état relu toutes les 8 s), « Convertir en
modèle… » (machine arrêtée, VM ou LXC, nom à retaper). Pas encore dans le menu des cartes de la liste (l'état « en pause » y est inconnu).

## Non validé en réel (essais du ticket, PC A, VM 115 et clone 117)
- reset, suspend, resume, hibernate : les noms exacts d'états (`qmpstatus` `paused`/`suspended`) sont tirés de la documentation, jamais observés ;
  une VM sans agent invité refusera sans doute l'hibernation (à noter) ;
- l'état d'une VM hibernée sur disque (Proxmox : arrêtée avec verrou `suspended`) : « Reprendre » ne la concerne pas, elle se démarre ;
- conversion : renommage `base-…`, refus du démarrage ensuite, retour `null` d'un LXC ;
- l'interface n'a pas été ouverte dans un navigateur (seul `npm run build` la valide).
