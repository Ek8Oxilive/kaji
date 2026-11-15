# Connexion par annuaire LDAP / Active Directory (#443, jalon J2)

Les personnes d'un annuaire d'entreprise se connectent à Kaji avec **le mot de passe de l'annuaire**, sans que Kaji le garde. Désactivée tant que `KAJI_LDAP_URL` est vide ; le mot de passe local reste le repli.

| Route | Rôle |
|---|---|
| `GET /api/auth/ldap/status` | `{enabled, label}` pour l'écran de connexion (publique ; aucune adresse ni secret) |
| `POST /api/auth/ldap/login` | `{username, password}` → session (cookie) ou, si le compte de Kaji a le TOTP, `{totp_required, challenge}` puis `POST /api/auth/login/totp` |

## Réglages (`.env`)
| Variable | Rôle |
|---|---|
| `KAJI_LDAP_URL` | `ldaps://annuaire:636`, ou `ldap://annuaire` avec `KAJI_LDAP_START_TLS=true` |
| `KAJI_LDAP_CA_FILE` | autorité privée de l'annuaire (le certificat est **toujours** vérifié) |
| `KAJI_LDAP_BASE_DN` | où chercher les personnes |
| `KAJI_LDAP_BIND_DN` / `KAJI_LDAP_BIND_PASSWORD` | compte de **lecture seule** qui retrouve l'entrée (jamais un administrateur de l'annuaire) |
| `KAJI_LDAP_USER_FILTER` | contient `{username}` ; défaut `(&(objectClass=person)(uid={username}))` ; Active Directory : `(&(objectClass=user)(sAMAccountName={username}))` |
| `KAJI_LDAP_USERNAME_ATTR` | attribut qui porte l'identifiant (`uid`, ou `sAMAccountName` pour AD) |
| `KAJI_LDAP_AUTO_CREATE`, `KAJI_LDAP_DEFAULT_ROLE` | crée à la première connexion un compte avec le rôle des groupes (voir plus bas), sinon `operator` ou `viewer` ; **administrateur seulement par groupe** |
| `KAJI_LDAP_ALLOW_ADMIN` | `true` (défaut) : un administrateur peut se connecter par l'annuaire ; `false` : administrateurs réservés au mot de passe local |
| `KAJI_LDAP_GROUPS_ATTR` | attribut qui liste les groupes de la personne (défaut `memberOf`, groupes **directs** seulement) |
| `KAJI_LDAP_ADMIN_GROUP`, `KAJI_LDAP_OPERATOR_GROUP` | DN **exact** du groupe dont les membres sont administrateurs (ou opérateurs) de Kaji ; vides (défaut) : aucun rôle n'est modifié |
| `KAJI_LDAP_LABEL`, `KAJI_LDAP_TIMEOUT` | texte de la case de l'écran de connexion ; délai en secondes |

## Comment ça se passe
1. Le nom est contrôlé (`[A-Za-z0-9][A-Za-z0-9._-]{2,63}`) et le mot de passe n'est ni vide ni contenant un octet nul : **un mot de passe vide est refusé avant tout appel**, car beaucoup d'annuaires acceptent une liaison sans mot de passe comme une liaison anonyme réussie.
2. Le compte de lecture cherche l'entrée avec le nom **échappé** (RFC 4515). Il faut **exactement une** entrée, dont l'attribut d'identifiant a **une seule valeur** égale au nom : sinon refus (jamais « la première »).
3. Le mot de passe est vérifié par une **liaison au DN de la personne** ; il n'est ni gardé, ni audité, ni renvoyé.
4. Le compte de Kaji : déjà relié par `(annuaire, DN)` ; sinon un compte existant du même nom et relié à personne (un administrateur aussi, sauf `ALLOW_ADMIN=false` : l'annuaire est alors la source de confiance pour son identité) ; sinon, avec `AUTO_CREATE`, un compte neuf. Le mot de passe local reste possible comme secours.
5. **Groupes → rôle** (`app/rolemap.py`), seulement si `ADMIN_GROUP` ou `OPERATOR_GROUP` est renseigné : à **chaque connexion**, le rôle du compte est recalculé d'après les groupes de l'entrée : administrateur (si `ALLOW_ADMIN`), sinon opérateur, sinon rôle par défaut. Correspondance **exacte** (casse et espaces autour de `,` et `=` ignorés, jamais « contient »). Le **dernier administrateur n'est jamais rétrogradé**. Chaque changement est audité (`role-sync`). Retirer quelqu'un du groupe lui retire le rôle à sa connexion suivante (une session ouverte garde l'ancien jusqu'à sa fin). **Un membre du groupe administrateur est administrateur de Kaji, donc de Proxmox.**

## Garde-fous
- Chiffrement obligatoire : `ldap://` sans STARTTLS est refusé ; STARTTLS est négocié **avant** toute liaison.
- Même réponse (401, « Identifiants invalides ») pour un inconnu, un mauvais mot de passe, un annuaire éteint ou un compte de lecture refusé ; le motif court va à l'audit (`login-ldap`), jamais une valeur reçue.
- Limiteur : 5 échecs par adresse et par 5 minutes (pas par identifiant : cela permettrait de verrouiller les comptes de l'annuaire à distance).
- Le TOTP de Kaji est encore demandé si le compte l'a activé.

## Limites connues
- **Jamais essayée avec un vrai annuaire** : seuls un annuaire simulé (`ldap3` en mode MOCK) et un faux `Connection` pour STARTTLS ont servi (`tests/test_ldap_login.py`).
- Le lien se fait par DN (insensible à la casse) : renommer ou déplacer l'entrée dans l'annuaire coupe le lien ; il se refait par le nom si le compte de Kaji n'est relié à personne d'autre.
- Les groupes **imbriqués** ne sont pas résolus (`memberOf` ne liste que les groupes directs) : mets le groupe d'administrateurs en appartenance directe, ou donne l'attribut d'un autre champ.
- Une session déjà ouverte survit à la désactivation du compte dans l'annuaire, ou au retrait d'un groupe, jusqu'à son expiration (`KAJI_SESSION_HOURS`).
- Un compte absent de tout groupe reçoit le rôle par défaut (il n'est pas refusé).
