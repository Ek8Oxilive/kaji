# Utilisateurs de Kaji et rôles (M6, lot #409)

Préfixe `/api/kaji-users`. Qui peut se connecter à **Kaji** (pas à Proxmox : le jeton de Kaji auprès de Proxmox est le même pour tous) et ce qu'il a le droit de faire. Fenêtre « Gérer les utilisateurs… » du dialogue **Compte** (administrateurs seulement).

## Rôles (`backend/app/roles.py`)
| Rôle | Peut |
|---|---|
| `admin` | tout, y compris gérer les utilisateurs de Kaji |
| `operator` | lire ; démarrer, arrêter (forcé), éteindre, redémarrer une machine ; réinitialiser, suspendre, reprendre, hiberner une VM ; **créer** un snapshot. Rien d'autre |
| `viewer` | lire seulement |

- **Décidé par le serveur à CHAQUE requête** (`_session_of`, donc toutes les routes authentifiées), jamais par l'interface. Refus : 403 « Ton rôle ne permet pas cette action », audité (`role-refused`, rôle et route, sans corps de requête).
- **Tout ce qui n'est pas explicitement permis est refusé** : une route ajoutée plus tard est réservée aux administrateurs tant qu'elle n'est pas déclarée dans `roles.py`. Un rôle inconnu (base abîmée) vaut `viewer`.
- Refusé à l'opérateur et au lecteur : consoles (REST et WebSocket), migration, clone, disques, réglages, suppression, restauration d'un snapshot, droits, session administrateur, connexions.
- Toujours permis à tous (`/api/auth/*`) : se déconnecter, changer son propre mot de passe.
- Premier compte (écran de première configuration) et comptes existants (**migration n° 3**, testée depuis une base de l'ancienne version) : `admin`.

## Routes (administrateurs seulement, aussi en lecture)
| Route | Effet |
|---|---|
| `GET /api/kaji-users` | Liste (jamais de mot de passe ni de haché) |
| `POST /api/kaji-users` | Crée : `username` (3 à 64, `[A-Za-z0-9._-]`, insensible à la casse pour l'unicité), `password` (12 caractères au moins), `role` |
| `PUT /api/kaji-users/{id}` | Change le rôle et/ou réinitialise le mot de passe (révoque ses sessions) |
| `DELETE /api/kaji-users/{id}?confirm=true&name=…` | Supprime (nom retapé) ; ses sessions et sa session administrateur Proxmox disparaissent |

Garde-fous : on ne se supprime pas et on ne change pas son propre rôle ; il reste toujours au moins un administrateur ; aucun mot de passe n'est renvoyé ni journalisé ; audit `kaji-user-create|update|delete`.

## Validation
`backend/tests/test_roles.py` (politique en fonction pure, API avec plusieurs comptes réels, migration), mutations tuées. **Pas vu en réel** : voir `docs/REPRISE.md`. **Limite** : les rôles protègent l'accès à Kaji ; quiconque a un compte administrateur de Kaji agit avec le jeton de Kaji sur Proxmox.
