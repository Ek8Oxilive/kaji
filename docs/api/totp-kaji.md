# Double authentification (TOTP) pour se connecter à Kaji (jalon J2, ticket #444)

Chaque compte de Kaji peut protéger SA connexion par un code à usage unique (application d'authentification : Aegis, FreeOTP, Google Authenticator, 1Password, Bitwarden…), en plus du mot de passe. **Facultatif, par compte** : un compte sans TOTP se connecte comme avant. Ne pas confondre avec la double authentification des utilisateurs **Proxmox** (`docs/api/tfa.md`), qui est un autre sujet.

## Parcours
1. **Activer** (fenêtre « Compte » → « Double authentification… ») : mot de passe demandé, Kaji génère un secret (affiché **une seule fois**, à saisir à la main dans l'application), puis l'utilisateur tape un premier code. Tant qu'il ne l'a pas fait, le TOTP n'est **pas** exigé (un enrôlement abandonné ne verrouille personne). À la confirmation, Kaji affiche **10 codes de secours**, une seule fois.
2. **Se connecter** : le mot de passe ouvre une première étape qui renvoie un **défi** de 5 minutes, pas une session ; le code (ou un code de secours) ouvre la session.
3. **Perte du téléphone** : un code de secours (usage unique), sinon un administrateur retire le TOTP du compte (« Retirer la 2FA… » dans « Gérer les utilisateurs… »).

## Routes
| Route | Rôle |
|---|---|
| `POST /api/auth/login` | mot de passe correct **et TOTP actif** → `{"totp_required": true, "challenge": "…"}` et **aucun cookie** ; sinon comportement inchangé |
| `POST /api/auth/login/totp` `{challenge, code}` | seconde étape : ouvre la session (cookie) ; `code` = 6 chiffres ou code de secours |
| `GET /api/auth/totp` | `{enabled, pending, recovery_remaining}` du compte connecté |
| `POST /api/auth/totp/setup` `{password}` | génère le secret → `{secret, uri}` (une fois) |
| `POST /api/auth/totp/confirm` `{code}` | premier code valide : active et renvoie `recovery_codes` (une fois) |
| `POST /api/auth/totp/recovery` `{password, code}` | nouveaux codes de secours ; exige un code de l'**application** (pas un code de secours) |
| `POST /api/auth/totp/disable` `{password, code}` | désactive SON TOTP ; code de l'application ou de secours |
| `DELETE /api/kaji-users/{id}/totp?confirm=true&name=…` | administrateur : retire le TOTP d'**un autre** compte (nom retapé, sessions du compte révoquées) ; **refusé pour soi-même** (409) |

Les routes de `/api/auth/` sont en libre-service : **tous les rôles** (administrateur, opérateur, lecture seule) peuvent protéger leur compte. La liste `GET /api/kaji-users` indique `totp: true|false` par compte.

## Garanties
- **Un code déjà accepté ne l'est jamais deux fois** (anti-rejeu : dernier pas accepté enregistré par un `UPDATE` conditionnel, donc deux requêtes simultanées avec le même code ne passent pas toutes les deux). Fenêtre de tolérance : un pas de 30 s avant et après.
- **Limiteur** : 5 échecs en 5 minutes bloquent l'adresse **et** le compte (clé distincte) ; compteurs persistants (`login_failures`). Un attaquant qui connaît le mot de passe peut donc **bloquer 5 minutes** un compte en devinant ; il ne peut pas se connecter.
- **Le défi n'ouvre rien tout seul** : signé avec une clé **distincte** de celle des sessions, lié à l'empreinte du mot de passe (changer le mot de passe l'invalide), 5 minutes ; un cookie de session n'est pas un défi et inversement.
- **Secret chiffré au repos** (comme les jetons des connexions, avec `KAJI_SECRET_KEY`) ; **codes de secours stockés sous forme d'empreinte** (SHA-256), jamais en clair ; 80 bits chacun (une force brute sur l'empreinte est hors de portée, donc pas de clé : une rotation de `KAJI_SECRET_KEY` ne les invalide pas).
- **Rien n'est journalisé** : ni secret, ni code, ni code de secours, ni défi (audit : `totp-setup`, `totp-enabled`, `login-totp` en erreur, `totp-recovery-used` avec le nombre restant, `totp-disabled`, `kaji-user-totp-remove`).
- **Pas de contournement par un administrateur pour lui-même** : une session volée ne peut pas désactiver le second facteur de son propre compte sans le mot de passe ET un code.
- Calcul TOTP (RFC 6238, SHA-1, 6 chiffres, 30 s) en bibliothèque standard : **aucune dépendance de plus** ; vérifié avec les vecteurs de la RFC.

## Limites connues
- **Pas de QR code** : le secret se saisit à la main (« saisie manuelle » de toutes les applications) ; un QR demanderait une dépendance de plus. À ajouter si besoin.
- **Pas d'obligation** : aucun réglage ne force le TOTP pour tous les comptes ou pour les administrateurs (suite possible, avec le SSO du ticket #443).
- **Pas de WebAuthn / clé matérielle** pour la connexion à Kaji.
- **Rotation de `KAJI_SECRET_KEY`** : `python -m app.admin_cli rotate-secret-key --yes` (`docs/runbook.md`) ré-chiffre aussi les secrets TOTP (confirmés ou en attente) ; `verify` les relit et signale ceux qu'une clé ne lit pas. Les codes de secours sont des empreintes SHA-256 : la rotation ne les concerne pas. Rotation **sans** la commande : les secrets TOTP deviennent illisibles, un administrateur retire alors le TOTP des comptes concernés (les codes de secours restent valables).
- Une seule instance de Kaji (comme le planificateur) ; l'horloge du serveur doit être à l'heure (sinon les codes sont refusés).

## Tests
`backend/tests/test_totp.py` (68 tests) : vecteurs de la RFC 6238, fenêtre et rejeu, parcours complet par l'API (activation, deux étapes, mauvais code, codes de secours à usage unique, nouveaux codes, désactivation), défi falsifié, expiré, d'un autre compte, invalidé par un changement de mot de passe, limiteur par adresse et par compte, rôles, retrait par un administrateur (et refus pour soi-même), secret chiffré et codes hachés, rien dans l'audit, deux requêtes simultanées avec le même code. 19 mutations tuées (7 survivantes d'abord, comblées).
**Vu dans l'interface** (serveur local de test, compte jetable) : activation (secret affiché, code, 10 codes de secours), état « Activée », connexion en deux étapes, mauvais code refusé (« Code invalide »), bon code accepté, badge « 2FA » dans la liste des utilisateurs, pas de bouton de retrait pour soi-même.
**Pas encore vu** : sur le déploiement réel (CT 116), avec un vrai téléphone, un retrait par un administrateur dans l'interface, l'interface en anglais.
