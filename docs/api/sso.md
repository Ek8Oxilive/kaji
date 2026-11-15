# SSO par OpenID Connect (jalon J2, ticket #443)

Se connecter à Kaji par le fournisseur d'identité de l'entreprise (Keycloak, Entra ID, Authentik, Okta…), en **OpenID Connect, flux « Authorization Code » avec PKCE**. **Désactivé tant que `KAJI_OIDC_ISSUER` est vide.** Le **mot de passe local reste le repli** (compte administrateur) : un fournisseur en panne ne bloque personne.

## Réglages (`.env`, voir `.env.example` et `docs/installation-lab.md`)
| Variable | Rôle |
|---|---|
| `KAJI_OIDC_ISSUER` | adresse **https** du fournisseur ; active le SSO |
| `KAJI_OIDC_CLIENT_ID`, `KAJI_OIDC_CLIENT_SECRET` | le client déclaré chez le fournisseur ; le secret reste dans `.env`, jamais renvoyé ni journalisé |
| `KAJI_OIDC_REDIRECT_URI` | adresse de retour **exacte**, en https, terminée par `/api/auth/oidc/callback` ; la même chez le fournisseur |
| `KAJI_OIDC_SCOPES` | `openid profile` par défaut (`openid` est toujours ajouté) |
| `KAJI_OIDC_USERNAME_CLAIM` | champ du jeton qui désigne le compte de Kaji (`preferred_username` par défaut) |
| `KAJI_OIDC_AUTO_CREATE`, `KAJI_OIDC_DEFAULT_ROLE` | créer un compte à la première connexion, avec le rôle des groupes (voir ci-dessous), sinon ce rôle par défaut (`viewer` ou `operator`) ; **administrateur seulement par groupe** ; `false` par défaut |
| `KAJI_OIDC_ALLOW_ADMIN` | `true` (défaut) : un administrateur existant peut se connecter par le SSO ; `false` : administrateurs réservés au mot de passe local (même s'ils étaient déjà reliés) |
| `KAJI_OIDC_GROUPS_CLAIM` | champ de l'ID token qui liste les groupes (défaut `groups` ; ajouter le périmètre `groups` chez le fournisseur) |
| `KAJI_OIDC_ADMIN_GROUP`, `KAJI_OIDC_OPERATOR_GROUP` | nom **exact** du groupe dont les membres sont administrateurs (ou opérateurs) de Kaji ; vides (défaut) : aucun rôle n'est modifié |

**Groupes → rôle** (`app/rolemap.py`, identique à l'annuaire, `docs/api/ldap.md`) : seulement si un groupe est renseigné ; à **chaque connexion** le rôle est recalculé (administrateur si `ALLOW_ADMIN`, sinon opérateur, sinon rôle par défaut) ; correspondance exacte, jamais « contient » ; le **dernier administrateur n'est jamais rétrogradé** ; chaque changement est audité (`role-sync`). **Un membre du groupe administrateur est administrateur de Kaji, donc de Proxmox.**
| `KAJI_OIDC_LABEL` | texte du bouton |

**Une configuration invalide empêche Kaji de démarrer** (adresse non https, identifiant du client absent, adresse de retour mal formée, rôle `admin`…) : un SSO à moitié réglé ouvrirait une porte mal comprise. Seule la boucle locale (`http://localhost`, `127.0.0.1`) est tolérée en http, pour les essais.

## Routes (publiques : il n'y a pas encore de session)
| Route | Rôle |
|---|---|
| `GET /api/auth/oidc/status` | `{enabled, label}` : l'écran de connexion y lit s'il doit montrer le bouton |
| `GET /api/auth/oidc/login` | 404 si désactivé ; sinon pose un cookie d'état signé et **redirige (303)** vers le fournisseur |
| `GET /api/auth/oidc/callback?code&state` | vérifie, ouvre la session et redirige vers `/` ; **tout refus** redirige vers `/?sso=erreur` (ou `/?sso=trop` si l'adresse est bloquée) |

## Ce qui est vérifié (une seule vérification en échec = connexion refusée)
1. **État** (anti-CSRF) : cookie signé (HttpOnly, SameSite=Lax, 10 minutes, usage unique) comparé à celui que renvoie le fournisseur, en temps constant.
2. **PKCE (S256)** : l'échange du code envoie le `code_verifier` que seul ce navigateur connaît.
3. **Signature** de l'ID token par la clé publique du fournisseur (JWKS, avec une relecture au plus par minute si la clé a tourné) ; algorithmes **asymétriques seulement** : `none` et `HS*` (confusion de clé) sont refusés.
4. **Émetteur** exact, **audience** = notre client (et `azp` si plusieurs), **expiration** (1 minute de tolérance), **nonce**, `sub` présent.
5. **Découverte** : l'émetteur annoncé doit être celui configuré ; les points d'accès sont en https ; mise en cache 10 minutes.
6. **Limiteur** : 5 refus par 5 minutes bloquent l'adresse, avant tout appel au fournisseur.

## Quel compte de Kaji ?
- **Déjà relié** : `(émetteur, sub)` retrouve le compte, **même si le nom a changé chez le fournisseur**.
- **Premier passage** : `KAJI_OIDC_USERNAME_CLAIM` doit désigner un compte de Kaji **existant** (3 à 64 caractères : lettres, chiffres, `.`, `_`, `-`) qui n'est relié à **personne d'autre** ; le lien est posé et ne bouge plus. **Un nom d'utilisateur repris par quelqu'un d'autre ne donne donc jamais accès au compte.**
- **Sinon** : refus, sauf `KAJI_OIDC_AUTO_CREATE=true` : compte neuf au rôle par défaut, avec un **mot de passe que personne ne connaît**.
- Le **rôle** est celui du compte de Kaji (pas un champ du jeton) ; le périmètre (`docs/api/roles-perimetre.md`) s'applique comme pour une connexion par mot de passe.
- Une adresse e-mail (`a@b.com`) **ne peut pas** servir de nom de compte (le `@` n'est pas permis) : utiliser `preferred_username` ou un champ personnalisé.

## Audit
`login-sso` : succès (« connexion par le fournisseur d'identité ») et refus avec un **motif court** (`état invalide`, `jeton refusé…`, `aucun compte de Kaji pour cette personne`…). Jamais un code, un jeton, un secret, un `sub` ni un message du fournisseur.

## Limites connues
- **Aucun essai avec un vrai fournisseur** : tout est testé contre un faux fournisseur local (`tests/test_sso.py`, 64 tests : vrais jetons RSA, PKCE vérifié par le faux fournisseur). Le critère « une personne se connecte par le SSO de l'entreprise » **attend un fournisseur de test**.
- **Une session déjà ouverte survit** à la désactivation du compte chez le fournisseur jusqu'à son expiration (12 h par défaut, `KAJI_SESSION_HOURS`) ; un administrateur peut la couper (« Déconnecter toutes les sessions », ou la suppression du compte). Le fournisseur refuse en revanche toute **nouvelle** connexion d'un compte désactivé ou retiré.
- **Le second facteur est celui du fournisseur** : le TOTP de Kaji n'est pas redemandé après un SSO réussi.
- Pas de rôles tirés des groupes du fournisseur (le rôle se gère dans Kaji) ; pas de déconnexion unique (pas de « logout » côté fournisseur) ; pas de LDAP / AD direct (passer par un fournisseur OIDC qui s'y adosse).
- Une seule instance de Kaji : l'état de la connexion est un cookie, mais les caches (découverte, clés) sont en mémoire.

## Tests
`backend/tests/test_sso.py` : désactivé par défaut ; configuration (10 cas invalides, démarrage refusé) ; départ (PKCE, état et nonce frais, cookie) ; parcours complet (liaison, renommage, nom repris refusé, création automatique au rôle mini, mot de passe inconnu, champ de nom invalide) ; état (mauvais, absent, falsifié, expiré, rejeu, erreur du fournisseur sans recopier son message) ; ID token (nonce, audience, émetteur, expiration, `sub`, clé étrangère, `none`, `HS256`, rotation et clé inconnue, relecture limitée) ; fournisseur en panne ou hostile ; limiteur ; secrets absents de l'audit et des réponses. **Mutations** sur chaque vérification de sécurité (émetteur, algorithmes, nonce, audience, `azp`, `sub`, expiration, PKCE, état, liaison, création automatique, rôle, limiteur) : **toutes détectées**, sauf une mutation sans effet sur le comportement (un argument de décodage ajouté en trop) ; 4 lacunes de test d'abord, comblées.
**Jamais vu** : un vrai fournisseur, le bouton dans le navigateur (le frontend compile ; pas de vérification visuelle).
