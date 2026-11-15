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
- **Expiration obligatoire (jalon J2, ticket #442)** : `expire` doit être donné, **dans le futur**, et au plus `KAJI_TOKEN_CREATE_MAX_DAYS` jours (365 par défaut ; `0` = facultative, comme avant). Refusé en 422 **avant tout appel à Proxmox** et audité (`Expiration obligatoire…`, `L'expiration doit être dans le futur`, `Expiration trop lointaine…`). Le formulaire de la page « Accès » demande un nombre de jours (90 proposés).
- **Privilèges séparés obligatoires** : `privsep` doit être vrai (422 sinon). Un token sans séparation hériterait de **tous** les droits de son utilisateur ; Kaji ne les crée jamais. Le token créé n'a aucun droit tant qu'une ACL (`docs/api/acl-ecriture.md`) ne lui en donne pas.
- Utilisateurs du realm **`pve`** seulement ; `root@pam`, le compte de Kaji et celui de la session administrateur n'ont ni création ni **révocation** (403) : on ne peut pas révoquer le token de Kaji.
- Doublon → 409 ; utilisateur inconnu → 404 ; au plus **20 tokens** par utilisateur (409 au-delà).
- Nom de token : lettre puis lettres, chiffres, `.` `_` `-` (2 à 64) ; commentaire d'une ligne de 100 caractères ; `expire` : secondes depuis 1970, plafonnées à l'an 2100 (et, par défaut, à un an d'ici : voir plus haut).
- L'utilisateur du corps doit être celui de l'adresse (422).
- État relu avant et après l'écriture (502 si Proxmox n'a pas appliqué).
- Audit `token-create` et `token-revoke` (succès, refus, erreur), sans secret.

## Limites
Essai réel (création d'un jeton chez Proxmox) : voir `docs/REPRISE.md` ; il faut une session administrateur et un utilisateur `pve` jetable. L'ouverture de la session administrateur **par mot de passe** (pour les opérations interdites aux jetons, comme la double authentification) est tapée par le propriétaire. Les tokens existants de l'utilisateur de Kaji ou de `root@pam` restent gérables dans l'interface de Proxmox.
