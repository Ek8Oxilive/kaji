# Tokens d'API : lister, créer, révoquer

Préfixe : `/api/connections/{id}/access/users/{userid}/tokens`. **Exige une session administrateur** (`docs/api/admin-session.md`) : tout se fait avec l'identité du token d'administration collé (403 sans session).
Une écriture à la fois, `confirm: true` **et l'identifiant complet `utilisateur!token` retapé**.

| Route | Rôle |
|---|---|
| `GET /` | tokens de l'utilisateur : `[{tokenid, privsep, expire, comment}]`. **Jamais de secret** |
| `POST /` `{userid, tokenid, comment?, expire?, privsep: true, confirm, type_name}` | crée un token ; renvoie **une seule fois** `{created, secret, privsep, expire, warning}` |
| `DELETE /{tokenid}?confirm=true&name=utilisateur!token` | révoque le token (immédiat, irréversible) |

## Le secret
- Renvoyé **uniquement** dans la réponse de la création (`secret`, forme UUID vérifiée). Il n'est ni journalisé, ni conservé, ni relisible : Proxmox ne le redonne jamais, et la liste ne le reprend jamais, même si Proxmox en renvoyait un par erreur.
- Si la réponse de Proxmox est illisible, ou si le token n'apparaît pas ensuite dans la liste (ou sans privilèges séparés), **aucun secret n'est relayé** (502).
- L'interface l'affiche dans une fenêtre qu'on ne ferme qu'après avoir confirmé l'avoir noté.

## Garde-fous (côté serveur)
- **Privilèges séparés obligatoires** : `privsep` doit être vrai (422 sinon). Un token sans séparation hériterait de **tous** les droits de son utilisateur ; Kaji ne les crée jamais. Le token créé n'a aucun droit tant qu'une ACL (`docs/api/acl-ecriture.md`) ne lui en donne pas.
- Utilisateurs du realm **`pve`** seulement ; `root@pam`, le compte de Kaji et celui de la session administrateur n'ont ni création ni **révocation** (403) : on ne peut pas révoquer le token de Kaji.
- Doublon → 409 ; utilisateur inconnu → 404 ; au plus **20 tokens** par utilisateur (409 au-delà).
- Nom de token : lettre puis lettres, chiffres, `.` `_` `-` (2 à 64) ; commentaire d'une ligne de 100 caractères ; `expire` de 0 à 2100.
- L'utilisateur du corps doit être celui de l'adresse (422).
- État relu avant et après l'écriture (502 si Proxmox n'a pas appliqué).
- Audit `token-create` et `token-revoke` (succès, refus, erreur), sans secret.

## Limites
Aucun essai réel (il faut un token d'administration). Les tokens existants de l'utilisateur de Kaji ou de `root@pam` restent gérables dans l'interface de Proxmox.
