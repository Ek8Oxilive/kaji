# Réglages du SSO et de l'annuaire depuis l'interface (#443, jalon J2)

Le menu **Compte → Authentification…** (administrateurs) règle la connexion à Kaji par le SSO (OpenID Connect, `docs/api/sso.md`) ou par un annuaire LDAP / Active Directory (`docs/api/ldap.md`) **sans toucher au `.env`**.

| Route | Rôle |
|---|---|
| `GET /api/auth-settings` | l'état des deux fournisseurs : `enabled`, `source` (`database`, `env`, `none`), valeurs effectives non secrètes, `secrets` (défini ou non), `problems` |
| `PUT /api/auth-settings/{ldap\|oidc}` | `{values, secrets, clear_secrets, confirm, dry_run}` : fusionne avec l'existant ; `dry_run` valide sans rien écrire ; l'écriture exige `confirm` |
| `DELETE /api/auth-settings/{provider}?confirm=true` | retire les réglages de la base : le `.env` s'applique de nouveau |
| `POST /api/auth-settings/{provider}/test` | `{ok, detail}` : lie le compte de lecture (annuaire) ou lit la découverte (SSO). **Corps facultatif `{values, secrets}`** : essaie les valeurs saisies dans la fenêtre par-dessus l'existant, **sans rien enregistrer ni auditer** ; un secret non retapé est remplacé par celui qui est enregistré. Sans corps : la configuration effective |

## Règles
- **La base prime sur le `.env`** ; sans ligne en base, le `.env` s'applique tel quel (une installation existante ne change pas).
- **Réservé aux administrateurs, même en lecture** (l'adresse de l'annuaire et le DN du compte de lecture ne sont pas pour tout le monde) : `app/roles.py`, `ADMIN_ONLY_PREFIXES`.
- **Secrets en écriture seule** (mot de passe du compte de lecture, secret du client SSO) : chiffrés avec `KAJI_SECRET_KEY` dans `auth_settings.secret_enc`, jamais renvoyés, jamais journalisés ; l'API dit seulement « défini ». Ils suivent la rotation de la clé (`rotate-secret-key`) et la vérification des sauvegardes (`verify`).
- **Chaque champ est validé** : type, bornes, texte sans caractère de contrôle, `default_role` limité à `operator` / `viewer` (jamais administrateur), `ca_file` chemin absolu sans `..`, `url` en `ldap(s)://`. Une configuration que le fournisseur concerné refuse (SSO : mêmes contrôles qu'au démarrage ; annuaire : chiffrement obligatoire, base, compte de lecture, filtre avec `{username}`) n'est **jamais enregistrée**. Les messages disent quel réglage, jamais la valeur.
- **Audit** (`auth-settings`) : les NOMS des réglages changés (« bind_password (secret défini) »), jamais une valeur.
- **Aucun verrouillage possible** : le mot de passe local reste toujours là (secours si le fournisseur est indisponible).
- **Administrateurs et groupes** : « Autoriser les administrateurs » (`allow_admin`, vrai par défaut) ; « Groupe administrateur » et « Groupe opérateur » font suivre le rôle aux groupes à chaque connexion (`docs/api/ldap.md`, `docs/api/sso.md`) ; vides, aucun rôle n'est modifié.
- Le test de connexion n'envoie **jamais le mot de passe d'une personne** ; ses réponses sont des textes courts et fixes.

## Limites connues
- **Jamais essayé avec un vrai annuaire ni un vrai fournisseur** : annuaire simulé (`ldap3` MOCK) et faux fournisseur seulement.
- Les messages de refus du serveur sont en français (comme les autres messages dynamiques).
- Le test d'un annuaire ou d'un fournisseur est une requête sortante vers l'adresse saisie par l'administrateur (sonde réseau possible par un administrateur, qui peut déjà tout faire).
- Les réglages de la base ne sont pas relus par `oidc.check_config()` au démarrage (ils sont validés à l'enregistrement).
