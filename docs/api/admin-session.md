# Session administrateur (socle de l'écriture des droits)

Préfixe : `/api/connections/{id}/admin-session`. **Cette fonction n'écrit aucun droit.** Elle garde en mémoire, le temps d'une session, un token
d'administration collé par le propriétaire, pour que les futurs lots d'écriture (utilisateurs, ACL, tokens) puissent agir avec cette identité.
Le token **permanent** de Kaji reste sans `Permissions.Modify` ni `User.Modify` : un Kaji compromis au repos ne peut pas se donner de droits
(voir `docs/m6-ecriture.md`, décisions du propriétaire : option D, token collé, 30 minutes).

| Route | Rôle |
|---|---|
| `GET /` | état : `{active: false}` ou `{active, user, token_id, seconds_left, expires_at, renewals}` |
| `POST /` `{user, token_id, secret}` | ouvre la session (201). Le token est **vérifié auprès de Proxmox** (`GET /access/permissions`) avant d'être gardé |
| `POST /renew` | prolonge de 30 minutes ; 404 si aucune session ; 409 à l'âge maximal |
| `DELETE /` | ferme la session (204, idempotent) |
| `GET /whoami` | droits effectifs de la session, lus **avec l'identité du token collé** : `{can_modify_permissions, modify_paths, paths}` ; 403 sans session |

## Garde-fous
- **Mémoire seulement** : le secret n'est jamais écrit en base, dans l'audit, dans un journal, ni renvoyé (`SecretStr`, `repr` masqué). Un redémarrage de Kaji ferme toutes les sessions. Kaji tourne avec **un seul worker** (voir `Dockerfile`) : l'état n'est pas partagé entre processus.
- **Durée** : 30 minutes, prolongeable par pas de 30 minutes, **jamais plus de 4 heures** depuis l'ouverture.
- **Liée à la session de connexion de Kaji** (`jti`), pas seulement à l'utilisateur : une déconnexion, « se déconnecter partout » ou un changement de mot de passe **ferment** la session administrateur ; une nouvelle connexion ne l'hérite pas. Liée aussi à **une connexion Proxmox** : elle ne sert pas pour un autre cluster.
- **Token distinct** : un token identique à celui de la connexion (même compte et même nom) est refusé (422).
- **Formats stricts** (regex ancrées) : compte `user@realm`, nom de token commençant par une lettre, secret = UUID. Aucune valeur saisie n'est renvoyée dans une erreur.
- **Limite d'essais** : 5 ouvertures par minute et par utilisateur de Kaji (429 au-delà, même avec un bon token).
- **Audit** (sans secret) : `admin-session-open`, `admin-session-renew`, `admin-session-close`, refus compris.
- Pour les futurs lots : la dépendance `require_admin` refuse (403) toute route d'écriture de droits sans session active pour la connexion ; `admin_client` fournit un client Proxmox qui agit avec l'identité de la session.

## À savoir
- **Transport** : si Kaji est servi en `http` sur le réseau local, le token collé circule en clair. L'interface l'affiche ; le mieux est de servir Kaji en `https` (proxy inverse).
- **Créer le token** (dans Proxmox, pour l'occasion, puis le supprimer) : un token **sans séparation de privilèges** d'un compte qui a `Permissions.Modify` sur les chemins visés. Plus ces chemins sont étroits (ex. `/pool/kaji-test`), plus le risque est borné ; `can_modify_permissions` et `modify_paths` montrent ce que le token peut réellement.
