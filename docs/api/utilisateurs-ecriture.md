# Écrire des utilisateurs, des groupes et des appartenances

Préfixe : `/api/connections/{id}/access`. **Exige une session administrateur ouverte** (`docs/api/admin-session.md`) : tout se fait avec l'identité du token d'administration collé
(403 sans session). Une écriture à la fois ; aucune écriture en masse. Chaque écriture exige `confirm: true` **et** l'identifiant retapé (`type_name`, ou `?name=` pour une suppression).

| Route | Rôle |
|---|---|
| `POST /users` `{userid, comment?, enable?, expire?, password?, confirm, type_name}` | crée un utilisateur du realm **pve** ; sans mot de passe, il ne se connecte que par token ; ne lui donne **aucun droit** |
| `PUT /users/{userid}` `{enable?, comment?, expire?, confirm, type_name}` | active, désactive, change le commentaire ou l'expiration |
| `DELETE /users/{userid}?confirm=true&name=` | supprime l'utilisateur (et ses tokens) |
| `GET /users/{userid}/impact` | lecture seule avant une suppression : groupes, nombre d'entrées d'ACL (utilisateur et tokens), noms des tokens |
| `PUT /users/{userid}/groups` `{group, action: "add"\|"remove", confirm, type_name}` | ajoute ou retire l'utilisateur d'**un** groupe |
| `POST /groups` `{groupid, comment?, confirm, type_name}` | crée un groupe (sans aucun droit) |
| `DELETE /groups/{groupid}?confirm=true&name=` | supprime un groupe **vide et sans ACL** |

## Interdits et garde-fous (vérifiés côté serveur)
- **Realm `pve` seulement** : `bob@pam`, `bob@ldap` ou un identifiant sans realm sont refusés (422) sans appel à Proxmox. Les realms pam, LDAP, AD se gèrent ailleurs.
- **Identités protégées** : `root@pam`, le compte de Kaji et le compte de la session administrateur ne peuvent être ni modifiés, ni supprimés, ni changés de groupe, ni recréés (403).
- **Ajouter quelqu'un à un groupe lui donne les droits du groupe** : refusé (403) si le groupe porte un rôle `Administrator`, un rôle avec `Permissions.Modify`, `User.Modify`, `Group.Allocate` ou `Realm.*`, une entrée sous `/access`, ou un rôle illisible. **Retirer** de n'importe quel groupe reste permis.
- **Groupe encore utilisé** : la suppression est refusée (409) tant qu'il a des membres ou des entrées d'ACL, pour ne pas perdre des droits en silence.
- **Validation** : identifiants et groupes par regex ancrées ; commentaire d'une ligne de 100 caractères sans antislash ; `expire` borné (0 = jamais, 2100 au plus) ; mot de passe de 12 à 128 caractères, sur une ligne, en `SecretStr`.
- **État relu chez Proxmox** avant l'écriture (inconnu → 404, doublon → 409) **et après** : si l'état ne correspond pas, 502 plutôt qu'un faux succès.
- **Audit** (`user-create`, `user-update`, `user-delete`, `group-member-add`, `group-member-remove`, `group-create`, `group-delete`) : succès, refus et erreur, sans secret (le mot de passe est « défini », jamais écrit).

## Limites connues
- Retirer le **dernier** groupe d'un utilisateur envoie `groups=""` : comportement de Proxmox déduit du schéma, non vérifié en réel.
- Les tokens (création, révocation) viennent dans un lot à part.
- Aucun essai réel : il faut un token d'administration.

## Interface et validation réelle (2026-11-13)
- Page « Accès » : avec une session administrateur ouverte, chaque utilisateur du realm `pve` (ni Kaji ni `root@pam`) a un bouton **« Supprimer… »** qui ouvre la fenêtre de suppression déjà réglée, avec l'impact affiché d'emblée (groupes, entrées d'ACL, jetons supprimés avec lui) et le nom à retaper. Les utilisateurs et les groupes se choisissent dans des **listes déroulantes** (`AccountSelect`) au lieu de se taper ; la création garde la saisie libre.
- **Validé en réel** : la suppression d'un utilisateur jetable du realm `pve` par ce bouton (nom retapé, relu chez Proxmox, liste revenue à l'état d'origine). **Jamais essayés en réel** : créer un utilisateur, activer / désactiver, mot de passe, appartenances, groupes et jetons API.

