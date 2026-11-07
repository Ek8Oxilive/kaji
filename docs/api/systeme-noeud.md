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
Dernières lignes du journal système : `{ "lines": [{ "n": 1, "text": "…" }] }`. `limit` de 1 à 500, `since` ancré `^AAAA-MM-JJ$`.
Droit `Sys.Syslog` ; sans lui : `502 « Droits insuffisants pour cette opération »`.

## Droits de Kaji (page Accès)
Deux fonctions ajoutées : `node-syslog` (`Sys.Syslog` sur `/nodes`) et `node-updates` (`Sys.Modify` sur `/nodes`), avec leur commande `pveum` à copier.
Attention : `Sys.Modify` autorise aussi des modifications du nœud ; ne l'accorde que si tu veux voir les mises à jour dans Kaji.
