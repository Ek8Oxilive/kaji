# Actions groupées d'un nœud et Wake-on-LAN (M15, lot #230)

Préfixe `/api/connections/{conn_id}`. Droits chez Proxmox : `VM.PowerMgmt` (démarrer, arrêter), `VM.Migrate` (migrer) sur `/vms`, `Sys.PowerMgmt` sur `/nodes/<nœud>` (Wake-on-LAN). Page « Nœud » : boutons **Actions groupées…** et **Réveiller le nœud…**.

## `POST /nodes/{node}/bulk`
Corps : `action` (`startall` | `stopall` | `migrateall`), **`vmids`** (liste explicite, 1 à 50 identifiants : Kaji n'envoie jamais « toutes les machines »), `confirm`, `type_name`, `dry_run`, et selon l'action :

| Action | Champs | Envoyé à Proxmox (`POST /nodes/{node}/<action>`) |
|---|---|---|
| `startall` | — | `vms=<liste>`, `force=1` (la liste est explicite, `onboot` ignoré) ; seules les machines **arrêtées** sont envoyées |
| `stopall` | `force_stop` (défaut non), `timeout` (10 à 7200 s, défaut 180) | `vms`, `force-stop=0/1`, `timeout` ; seules les machines **en marche** |
| `migrateall` | `target` (nœud en ligne, différent de la source), `with_local_disks`, `max_workers` (1 à 8), `accept_running` | `vms`, `target`, `maxworkers`, `with-local-disks=0/1` |

**Garde-fous (serveur)** : chaque identifiant est relu dans `/cluster/resources` (présent sur ce nœud, pas un modèle, sinon 422, rien n'est envoyé) ; une machine de `KAJI_PROTECTED_VMIDS` est **refusée (422) pour un arrêt ou une migration**, même confirmée ; rien à faire (tout déjà dans l'état demandé) = 409 ; `confirm` obligatoire ; **arrêt et migration : nom du nœud retapé** (démarrer : confirmation seule) ; migration de machines en marche : `accept_running` (migration à chaud, conteneurs redémarrés) ; nœud hors ligne ou inconnu : 409 / 404 ; état du cluster illisible : refus. Champs inconnus ignorés, doublons écartés. Audit `node-startall` / `node-stopall` / `node-migrateall` (refus, erreur, démarrage), sans secret.

**`dry_run: true`** : ne contacte pas Proxmox en écriture ; renvoie le plan : `apply`, `skipped` (avec la raison), `protected`, `running`, `target_ok`, `blocked` (message ou `null`), `needs_accept_running`.

Réponse (202 côté Proxmox, 200 ici) : `{node, action, upid, vmids}`. La progression est dans la page « Tâches ».

## `POST /nodes/{node}/wakeonlan`
Corps : `confirm`, `type_name` (nom du nœud retapé). Seulement pour un nœud connu du cluster et **hors ligne** (409 s'il est en ligne). Aucun paramètre envoyé à Proxmox : l'adresse MAC est celle déclarée dans la configuration du nœud (`wakeonlan`). Audit `node-wakeonlan`. Réponse 202 `{node, action: "wakeonlan"}`.

## Pas testé en réel
Voir le compte rendu de la PR : les noms de paramètres Proxmox sont ceux du schéma de `PVE::API2::Nodes` ; ce qui a réellement été vu sur le cluster y est listé.
