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

## Option : ouvrir la session avec le token permanent de Kaji (décision d'Enzo, 2026-11-13)

Raisonnement du propriétaire : Kaji remplace l'interface de Proxmox ; s'il est compromis, c'est aussi grave que si Proxmox l'était. La protection se joue donc sur l'accès à Kaji (`KAJI_SETUP_TOKEN`, HTTPS, épinglage du certificat, verrous d'écriture), pas sur un token au rabais.

- **Désactivée par défaut.** Activation : `KAJI_ADMIN_USE_KAJI_TOKEN=true` dans le `.env` de Kaji + redémarrage, **et** le propriétaire donne lui-même les droits d'administration au token de Kaji dans Proxmox (aucun agent ne le fait).
- `GET …/admin-session/kaji-token` : `{ "allowed": bool }`. `POST …/admin-session/kaji-token` : ouvre la session (30 min, mêmes prolongations, même âge maximal) avec le token de la connexion ; vérifié auprès de Proxmox (`/access/permissions`) avant d'être gardé ; 403 si l'option est désactivée ; audit `admin-session-open` « token permanent de Kaji (option activée) », jamais le secret.
- Les verrous des écritures (identifiant retapé, `COUPURE POSSIBLE`, `dry_run`, comptes protégés) ne changent pas. Bouton « Ouvrir avec le jeton de Kaji » de la page « Accès » (visible seulement si l'option est activée).

## Session par ticket (mot de passe) : lot #407
`POST …/admin-session/ticket` : `{ username: "root@pam", password, code? }`. C'est la **seule façon d'écrire la double authentification** : Proxmox interdit les jetons d'API sur `POST/PUT/DELETE /access/tfa/…` (`allowtoken: 0`, constaté en réel le 2026-11-13).
- Kaji appelle `POST /access/ticket` **sans aucune authentification** (cette route interdit les jetons), puis garde le **ticket** et le jeton CSRF **en mémoire seulement** (30 min, mêmes prolongations et même âge maximal que les autres sessions). Les appels suivants envoient le cookie `PVEAuthCookie` (encodé) et, pour toute écriture, `CSRFPreventionToken`.
- **Le mot de passe n'est jamais gardé** (ni mémoire de session, ni base, ni audit, ni réponse) : il ne sert qu'à obtenir le ticket. Il est saisi par le propriétaire dans la fenêtre « Ouvrir avec un mot de passe… » ; aucun agent n'en saisit jamais.
- Compte à double authentification : sans `code`, 409 ; avec `code` (6 à 8 chiffres), Kaji répond au défi (`tfa-challenge`, `password=totp:<code>`). Un second défi renvoyé n'ouvre aucune session.
- Refus de Proxmox (400, 401, 403) : message FIXE « Identifiants refusés… », jamais celui de Proxmox ; 5 essais par minute (429 ensuite) ; 422 sans appel Proxmox pour une saisie invalide (compte `nom@realm`, mot de passe sans caractère de contrôle, code numérique ASCII) ; réponse illisible (ticket ou CSRF) : 502, rien d'ouvert.
- L'état de la session porte `kind` (`token` ou `ticket`). Les verrous d'écriture ne changent pas ; le compte de la session ne peut toujours pas être modifié par elle-même.
- **Jamais essayée en réel** : elle demande le mot de passe d'un compte, à taper par Enzo.
