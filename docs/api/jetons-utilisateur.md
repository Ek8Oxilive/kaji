# Jeton Proxmox personnel de chaque utilisateur de Kaji (J2, option A du cadrage, ticket #440)

Aujourd'hui tous les utilisateurs de Kaji agissent auprès de Proxmox avec **le même jeton** : le journal de Proxmox ne dit pas *qui* a fait quoi et les droits réels sont ceux du jeton, pas ceux de la personne. Avec l'**option A** retenue le 2026-11-14, chaque utilisateur enregistre **son** jeton pour chaque connexion : Proxmox applique **ses** droits et son journal le **nomme**.

Routes sous `/api/me/proxmox-tokens`, **ouvertes à tous les rôles** de Kaji (chacun ne gère que le sien) ; le serveur revérifie tout.

| Route | Rôle |
|---|---|
| `GET /api/me/proxmox-tokens` | `{enabled, problem, required, max_days, connections: [{conn_id, name, state, pve_user, token_id, expires_at, days_left, privsep, verified}]}`. `state` : `none`, `ok`, `expiring` (≤ 7 jours), `expired`, `refused`. **Jamais de secret.** |
| `PUT /api/me/proxmox-tokens/{conn_id}` | Enregistre (ou remplace) : `{pve_user, token_id, secret, expires_at?, privsep}`. **Contrôlé auprès de Proxmox avant d'être gardé.** Renvoie l'entrée de la liste. |
| `DELETE /api/me/proxmox-tokens/{conn_id}` | Retire le jeton **de Kaji** (il reste valable chez Proxmox : le supprimer là-bas si besoin). 204, 404 s'il n'y en a pas. |

## Ce que fait Kaji d'un jeton personnel
- Dès que l'utilisateur en a un pour une connexion, **toutes ses requêtes vers Proxmox** (lectures, actions, consoles) partent avec ce jeton : `get_client_factory` (`app/deps.py`) choisit le jeton selon la session. Les **tâches de fond** (planificateur, alertes) gardent le jeton partagé : ticket du jeton de service (#441).
- Sans jeton personnel : le jeton **partagé** de la connexion, comme avant, **sauf** si `KAJI_REQUIRE_USER_TOKEN=true` : accès refusé (403) avec « Aucun jeton Proxmox personnel enregistré… ».
- Les sessions par ticket (mot de passe) et les appels anonymes n'utilisent **jamais** un jeton personnel. Un test de connexion avec des identifiants **saisis** à l'écran n'est pas remplacé par le jeton personnel de la connexion du même nom.
- **Flux temps réel** (`/events`) : commun à tous tant qu'ils utilisent le jeton partagé ; un utilisateur qui a **son** jeton a **son propre flux** (sinon l'état vu avec ses droits serait diffusé aux autres).

## Contrôles à l'enregistrement (refus 422 sans jamais recopier une valeur saisie)
- Formats : `pve_user` = `nom@realm`, `token_id` commence par une lettre, secret de 8 à 200 caractères sans espace.
- **Jamais `root@pam`** (règle du dépôt) ; **jamais le jeton partagé** de la connexion ; **privilèges séparés obligatoires** (`privsep` déclaré, et relu chez Proxmox quand c'est possible).
- Kaji appelle Proxmox **avec le jeton lui-même** : `GET /version` (401 → « Proxmox refuse ce jeton ») puis `GET /access/users/{userid}/token/{tokenid}`. Si Proxmox répond : `privsep` doit valoir 1 et `expire` doit être non nul (**un jeton sans expiration est refusé**) ; l'entrée est marquée `verified: true`. Si Proxmox ne laisse pas le jeton se décrire (403…) ou répond de façon inattendue : `expires_at` est **obligatoire**, le jeton est accepté avec `verified: false` (« déclaré, non contrôlé »).
- Expiration : future, et **au plus `KAJI_USER_TOKEN_MAX_DAYS` jours** (90 par défaut) ; la plus proche des dates (déclarée, Proxmox) l'emporte. **Kaji cesse d'utiliser le jeton à cette date**, même si Proxmox l'accepte encore (403 « a expiré »).

## Jeton refusé ou clé changée
- Proxmox répond **401** à un jeton personnel : message dédié (« Proxmox refuse ton jeton personnel… », 502), le jeton est marqué `refused`, **les appels suivants sont bloqués (403) sans toucher à Proxmox** jusqu'à ce qu'il soit enregistré de nouveau.
- `KAJI_TOKEN_KEY` absente ou changée : 503 « Les jetons personnels sont illisibles… » (pas de repli silencieux sur le jeton partagé).
- Supprimer un compte de Kaji ou une connexion **supprime ses jetons personnels**.

## Stockage et clé séparée (`app/tokenkey.py`)
- Table `user_tokens` (une ligne par utilisateur et par connexion). Le secret est chiffré (Fernet, dérivation HKDF **à étiquette propre**) avec **`KAJI_TOKEN_KEY`**, distincte de `KAJI_SECRET_KEY` (refusée si identique ou courte). `KAJI_TOKEN_KEY_FILE` : la clé dans un **fichier** hors de `.env` et hors de la sauvegarde de la base.
- **La base seule, ou la base avec `.env`/`KAJI_SECRET_KEY`, ne permet pas de lire un jeton personnel** si la clé séparée est ailleurs (test automatisé).
- **Rotation** : `KAJI_TOKEN_KEY` = nouvelle, `KAJI_TOKEN_KEY_PREVIOUS` = ancienne, redémarrage, puis `docker compose exec backend python -m app.admin_cli rotate-token-key --yes` (tout ou rien, relecture avec la seule nouvelle clé, audit `token-key-rotated`, `--drop-unreadable` pour supprimer les jetons qu'aucune clé ne lit). `verify` et `restore` relisent aussi ces jetons avec la clé séparée.
- Audit : `user-token-set` et `user-token-removed` (compte et identifiant du jeton, date d'expiration, « contrôlé par Proxmox : oui/non), **jamais le secret** ; les refus sont audités aussi.

## Réglages (`.env`)
| Variable | Rôle |
|---|---|
| `KAJI_TOKEN_KEY` / `KAJI_TOKEN_KEY_FILE` | clé séparée (au moins 32 caractères aléatoires) ; sans elle, la fonction est désactivée (`enabled: false`) |
| `KAJI_TOKEN_KEY_PREVIOUS` | l'ancienne clé, le temps d'une rotation |
| `KAJI_REQUIRE_USER_TOKEN` | `true` : pas de jeton personnel, pas d'accès à Proxmox (défaut `false`) |
| `KAJI_USER_TOKEN_MAX_DAYS` | durée maximale acceptée à l'enregistrement (défaut 90) |

## Validé en réel, et ce qui ne l'a pas été
**Essai réel du 2026-11-20** (PC B, Kaji déployé, bac à sable : VM 115 `kaji-sandbox`, compte `kajitest-perso@pve` et jeton `essai` jetables, tout supprimé ensuite ; le secret n'a été lu qu'en mémoire par l'agent, avec l'accord du propriétaire) :
- **Journal nominatif : validé.** Démarrer puis arrêter la VM 115 par Kaji avec le jeton personnel crée des tâches Proxmox au nom de `kajitest-perso@pve` (`qmstart` / `qmstop`, identifiant de tâche `…:qmstart:115:kajitest-perso@pve!essai:`), alors que les anciennes tâches sont au nom de `kaji@pve`. Le journal d'accès (`/var/log/pveproxy/access.log`) nomme `kajitest-perso@pve!essai` pour chaque lecture. L'audit de Kaji reprend le même identifiant de tâche.
- **Contrôle « vérifié » : validé, avec un droit de plus.** Avec un rôle sur la VM seulement, Proxmox ne laisse pas le jeton se décrire : l'enregistrement est accepté en `verified: false` (« déclaré, non contrôlé »). Avec `PVEUserAdmin` sur `/access` pour le compte ET le jeton, `GET /access/users/{u}/token/{t}` est lisible et l'entrée passe en `verified: true`.
- **Intersection des droits : validée.** Compte `PVEVMUser` + jeton `PVEAuditor` : démarrage refusé ; compte `PVEAuditor` + jeton `PVEVMUser` : refusé ; les deux `PVEVMUser` : accepté. Le droit effectif est le plus faible des deux.
- **Interface** : la fenêtre « Mon jeton Proxmox » a été utilisée dans un navigateur sur le Kaji déployé (enregistrement, état « Actif », retrait). Constat non investigué : dans une fenêtre de 739 px de large, le bouton « Compte » de l'en-tête n'était pas visible pour l'automate de test (il l'était à 1400 px).

**Non validé en réel** :
- le montage de `KAJI_TOKEN_KEY_FILE` dans Docker (pas de Docker sur le poste de l'agent, et le CT 116 est interdit aux agents) ;
- une écriture autre que démarrer / arrêter (par exemple une modification de configuration) avec un jeton personnel ;
- le comportement sur plusieurs connexions Proxmox.

Tout le reste est vérifié avec un faux Proxmox strict qui authentifie chaque jeton et note qui appelle (`backend/tests/test_user_tokens.py`).
