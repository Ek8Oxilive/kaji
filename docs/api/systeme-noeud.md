# Système d'un nœud (M11, lecture seule)

Deux routes, toutes protégées par la session Kaji. Aucune écriture : Kaji n'envoie que des `GET` à Proxmox.

## `GET /api/connections/{id}/nodes/{node}/system`
Rubriques lues en parallèle : `status`, `time`, `dns`, `services`, `updates`, `versions`, `repositories`, `certificates`, `disks`, `subscription`.
Chacune vaut `{ "state": "ok" | "forbidden" | "error", "data": … }` : un droit manquant (`forbidden`) n'empêche pas les autres.
`502` seulement si **toutes** les rubriques échouent (Proxmox injoignable).

| Rubrique | Proxmox | Droit nécessaire |
|---|---|---|
| status, time, dns, services, versions, repositories, certificates, disks, subscription | `/nodes/{n}/status`, `time`, `dns`, `services`, `apt/versions`, `apt/repositories`, `certificates/info`, `disks/list`, `subscription` | `Sys.Audit` |
| updates | `/nodes/{n}/apt/update` | **`Sys.Modify`** (exigé par Proxmox même pour lire la liste) |

Garde-fous : champs en liste blanche, textes bornés, noms de service et de disque validés (`fullmatch`). Les certificats sont renvoyés **sans leur PEM** ;
l'abonnement ne montre que son état (ni clé, ni identifiant de serveur) ; les numéros de série des disques ne sont pas repris.

## `GET /api/connections/{id}/nodes/{node}/syslog?limit=100&since=AAAA-MM-JJ`
Fin du journal système (Proxmox le lit depuis son début : Kaji demande d’abord le `total`, puis les dernières lignes) : `{ "lines": [{ "n": 1, "text": "…" }], "total": 586900 }`. `limit` de 1 à 500, `since` ancré `^AAAA-MM-JJ$`.
Droit `Sys.Syslog` ; sans lui : `502 « Droits insuffisants pour cette opération »`.

## Droits de Kaji (page Accès)
Deux fonctions ajoutées : `node-syslog` (`Sys.Syslog` sur `/nodes`) et `node-updates` (`Sys.Modify` sur `/nodes`), avec leur commande `pveum` à copier.
Attention : `Sys.Modify` autorise aussi des modifications du nœud ; ne l'accorde que si tu veux voir les mises à jour dans Kaji.

## `POST /api/connections/{id}/nodes/{node}/services/{service}/{action}` (écriture)
`action` : `start`, `stop`, `restart`, `reload`. Corps : `{ "confirm": true, "type_name": "…" }`. Réponse `202 {upid, node}` (tâche Proxmox à suivre).
Droit `Sys.Modify` sur `/nodes` (fonction `node-services` de la page Accès). Garde-fous, **vérifiés côté serveur** avant tout appel à Proxmox, et audités (succès, refus, erreur) :

| Règle | Réponse |
|---|---|
| Service hors liste blanche (`chrony`, `cron`, `ksmtuned`, `postfix`, `pvefw-logger`, `pveproxy`, `pvedaemon`, `pvestatd`, `pvescheduler`, `pve-firewall`, `proxmox-firewall`, `pve-ha-crm`, `pve-ha-lrm`, `sshd`, `lxcfs`, `pve-lxc-syscalld`, `qmeventd`, `systemd-journald`, `spiceproxy`, `corosync`, `pve-cluster`) | 404 |
| Nom de service ou de nœud mal formé (motif ancré) | 422 |
| `stop` de `corosync`, `pve-cluster`, `pveproxy`, `pvedaemon`, `sshd`, `systemd-journald`, `lxcfs` : jamais depuis Kaji | 422 |
| `stop`, `restart`, `reload` sans `confirm: true` (`start` n'en a pas besoin) | 400 |
| `restart` ou `reload` de `corosync` / `pve-cluster` sans `type_name` égal au nom du service | 400 |

`GET …/system` ajoute par service : `manageable`, `risk` (`normal`, `sensitive`, `vital`), `stoppable`.

## Redémarrer / éteindre un nœud (écriture)
Droit `Sys.PowerMgmt` sur `/nodes` (fonction `node-power`).

`GET …/nodes/{node}/power` (lecture seule) : conséquences lues auprès de Proxmox : `running_guests`, `protected_running`, `quorum_loss`, `nodes_online_after`.

`POST …/nodes/{node}/power` — `{ "action": "reboot" | "shutdown", "confirm": true, "type_name": "<nœud>", "accept_guests": false, "accept_quorum_loss": false }` → `202 {node, action}` (Proxmox ne renvoie pas de tâche). Garde-fous serveur, audités :

| Règle | Réponse |
|---|---|
| État du cluster illisible (fail closed) | 502 |
| Nœud inconnu / déjà hors ligne | 404 / 409 |
| Pas de `confirm` ou `type_name` ≠ nom exact du nœud | 400 |
| Machine **protégée** (`KAJI_PROTECTED_VMIDS`) en marche sur le nœud : jamais, même avec les acceptations | 422 |
| Machines en marche sans `accept_guests` | 409 |
| Les nœuds restants perdraient le quorum (`nœuds restants × 2 ≤ total`) sans `accept_quorum_loss` | 409 |
