# Notifications : cibles et règles, lecture seule (M13, lot #151, étape 1)

> **Non validé en réel** (faux Proxmox strict). Fichiers : `routers/notifications.py`, `notificationspec.py`, `tests/test_notifications.py`, `components/Notifications.tsx` (section de la page Datacenter),
> `lib/types/notifications.ts`. **L'écriture (ajouter, modifier, supprimer, tester une cible ; règles) est l'étape 2** : rien n'est écrit chez Proxmox par cette étape.

Datacenter → Notifications : des **cibles** (sendmail, SMTP, Gotify, webhook) reçoivent les messages ; des **règles** (matchers) décident lesquels partent vers quelle cible. Préfixe :
`/api/connections/{id}/notifications`. Droit Proxmox : `Mapping.Audit` (ou `Mapping.Modify`) sur `/mapping/notifications` (ligne « Lire les cibles et les règles de notification » de la page Accès).

| Route | Rôle | Proxmox |
|---|---|---|
| `GET /targets` | toutes les cibles (nom, type, commentaire, désactivée, origine) | `GET /cluster/notifications/targets` |
| `GET /endpoints` | les cibles de **chaque type** avec leurs réglages ; un type illisible est dans `unavailable`, les autres restent (502 si aucun type n'est lisible) | `GET …/endpoints/{sendmail,smtp,gotify,webhook}` |
| `GET /endpoints/{type}` | les cibles d'un type (`type` hors liste : 422, sans appel) | `GET …/endpoints/{type}` |
| `GET /matchers` | les règles : `mode` (`all` / `any`), `invert_match`, `match_field`, `match_severity`, `match_calendar`, `target` | `GET …/matchers` |
| `GET /matcher-fields` | noms des champs sur lesquels une règle peut porter | `GET …/matcher-fields` |
| `GET /matcher-field-values` | valeurs connues de ces champs (`field`, `value`, `comment`) | `GET …/matcher-field-values` |

`origin` : `builtin` (par défaut de Proxmox, ex. `mail-to-root`, `default-matcher`), `user-created`, `modified-builtin`.

## Aucun secret n'est renvoyé (liste blanche, vérifié par un faux Proxmox qui les renvoie en clair)
- SMTP : le **mot de passe** n'est jamais renvoyé ; Gotify : le **jeton** non plus.
- Webhook : seuls les **noms** des en-têtes (`header_names`) et des secrets (`secret_names`) sont renvoyés, jamais leurs valeurs ; le **corps** n'est pas renvoyé (`body_set: true/false`).
- Adresses (Gotify, webhook) : renvoyées **sans identifiants** (`user:mdp@`), **sans paramètres** (`?token=…`) ni fragment ; un schéma autre que http(s) ou une adresse illisible donne `null`.
- Tout est borné (≤ 200 lignes, textes tronqués, caractères de contrôle retirés) ; un nom de cible ou de règle hors du format `pve-configid` est écarté ; un type de cible inconnu aussi.

## Interface
Page **Datacenter**, section « Notifications » (sous les serveurs de métriques) : tableau des cibles (nom, origine, type, destination en une ligne, état) et tableau des règles (quand, vers quelles
cibles, état). Lecture seule.

## Non validé en réel (à essayer par PC A, lecture seule)
- les noms exacts des champs renvoyés par Proxmox pour chaque type (`mailto-user`, `from-address`, `header`, `secret`, `mode`…) : tirés des schémas du ticket, pas encore lus sur le cluster ;
- le droit `Mapping.Audit` sur `/mapping/notifications` pour le token de Kaji (sinon : « types illisibles » ou 502 avec un message clair) ;
- le format des entrées `header` / `secret` d'un webhook (`name=…,value=<base64>` supposé).
