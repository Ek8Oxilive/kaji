# Realms d'authentification (M6, lot #379)

Préfixe `/api/connections/{conn_id}/access`. Équivalent de Datacenter → Permissions → Realms. Bouton **« Realms… »** du panneau « Session administrateur » de la page « Accès » (la liste des realms existait déjà en lecture, `GET /realms`).
Schéma lu sur `apidoc.js` de Proxmox 9 (`/access/domains`). Validation et liste blanche par type : `backend/app/realmspec.py`.

| Route | Droit | Effet |
|---|---|---|
| `GET /realms/{realm}` | Kaji : `Sys.Audit` | Configuration d'un realm **sans aucun secret**, plus un `digest` de Kaji |
| `POST /realms` | session administrateur | Crée un realm `ldap`, `ad` ou `openid` |
| `PUT /realms/{realm}` | session administrateur | Modifie ; `clear` retire des réglages |
| `DELETE /realms/{realm}` | session administrateur | Supprime |
| `POST /realms/{realm}/sync` | session administrateur | Synchronise utilisateurs et groupes (LDAP, AD) |

Toute écriture passe par la **session administrateur** (M6-6), comme les utilisateurs et les ACL (à l'origine parce que le jeton de Kaji n'avait pas `Realm.Allocate` ; depuis le 2026-11-13 il a `Administrator`, mais l'écriture reste réservée à cette session et aux administrateurs de Kaji). Sans elle : 401 ou 403.

## Champs par type (un champ d'un autre type = 422)
- **ldap** : `server1` (obligatoire), `server2`, `port`, `mode` (`ldap`, `ldaps`, `ldap+starttls`), `base_dn` (obligatoire), `bind_dn`, `password`, `user_attr` (obligatoire), `user_classes`, `filter`, `group_dn`, `group_filter`, `group_classes`, `group_name_attr`, `sync_attributes`, `verify`, `sslversion`, `case_sensitive`, `check_connection`, `comment`, `default`, `sync_defaults_options` (`scope`, `enable_new`, `remove_vanished`).
- **ad** : comme LDAP sans `base_dn`, `user_attr`, `user_classes`, `group_dn`, `group_classes`, `group_name_attr` ; avec `domain` (obligatoire) ; `server1` obligatoire.
- **openid** : `issuer_url` et `client_id` (obligatoires), `client_key`, `username_claim`, `scopes`, `prompt`, `acr_values`, `autocreate`, `groups_autocreate`, `groups_claim`, `groups_overwrite`, `query_userinfo`, `comment`, `default`.
- **pam** et **pve** : intégrés, **ni créés ni supprimés**, seuls `comment` et `default` se modifient.

Validation : `server1` / `server2` : nom ou IP, adresses locales littérales refusées ; `issuer_url` : `https://` seulement, sans identifiants ni paramètres, hôte non local ; `port` entier 1 à 65535 ; booléens stricts ; TLS : `tlsv1_2` et `tlsv1_3` seulement (les anciennes versions que Proxmox accepte sont refusées) ; DN et filtres : pas de caractère de contrôle ; identifiant du realm : lettre puis lettres, chiffres, `. _ -`, 32 caractères au plus.
**Non exposés volontairement** : `capath`, `cert`, `certkey` (chemins de fichiers du nœud), `tfa` du realm, `full` et `purge` de la synchronisation (obsolètes), `secure` (obsolète).

## Secrets
`password` (liaison LDAP) et `client_key` (OpenID) : écriture seule. Jamais relus (Proxmox ne les relit pas), renvoyés, journalisés (« défini ») ni dans une erreur ; l'aperçu les masque.

## Verrous (décidés par le serveur)
- **Création / modification / suppression** : `confirm=true` et l'identifiant du realm retapé (`type_name`, ou `name` pour `DELETE`), 400 sinon. `dry_run` renvoie les paramètres (secrets masqués) et les verrous sans rien écrire.
- **Coupure possible** : modifier un réglage qui touche la connexion (`server1`, `server2`, `port`, `mode`, `base_dn`, `bind_dn`, `password`, `user_attr`, `domain`, `verify`, `sslversion`, `case_sensitive`, `issuer_url`, `client_id`, `client_key`, `username_claim`, `scopes`, `prompt`, `acr_values`, `autocreate`, ou en retirer un) **quand le realm a des comptes**, supprimer un realm qui a des comptes ou qui est le realm par défaut, et une synchronisation qui retire des comptes ou des droits, exigent en plus `acknowledge_cut_access=true` et `phrase="COUPURE POSSIBLE"` (409 sinon). Les comptes sont comptés par Kaji (`GET /access/users`).
- **Jamais supprimés** : `pam`, `pve` (403) et tout realm qui porte le compte de Kaji ou celui de la session administrateur (403).
- **Synchronisation** : réservée aux realms `ldap` et `ad` (422 sinon). **Simulation par défaut** (`dry_run=true` : Proxmox n'écrit rien) ; une vraie synchronisation exige `confirm` + identifiant retapé ; `remove_vanished` (`acl`, `properties`, `entry`) exige la phrase. Réponse : `upid` de la tâche, suivie dans la barre de tâches.
- `digest` de Kaji : périmé = 409 ; relecture après chaque écriture (502 si Proxmox n'a pas appliqué).

## Audit
`realm-create`, `realm-update`, `realm-delete`, `realm-sync`, refus compris, sans secret.

## Validation
Faux Proxmox strict (`backend/tests/test_realms_write.py` : clés autorisées par type, motifs du schéma, secrets non relus, comptes par realm). **Jamais écrit en réel** : un realm mal réglé peut verrouiller la connexion (la création d'un realm LDAP jetable a été refusée par le garde-fou de l'outil le 2026-11-13, l'aperçu `dry_run` répond bien). Pas de serveur LDAP, Active Directory ni OpenID sur le cluster.
**Hypothèses non vérifiées** : que Proxmox refuse un champ d'un autre type (le faux le suppose), le format exact de `sync-defaults-options` relu, le droit exact demandé par `GET /access/domains/{realm}`.
