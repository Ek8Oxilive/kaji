# Écrire une entrée d'ACL (ajouter, retirer)

Préfixe : `/api/connections/{id}/access/acl`. **Exige une session administrateur ouverte** (`docs/api/admin-session.md`) : toutes les lectures et l'écriture se font avec
l'identité du token d'administration collé, jamais directement avec le token permanent de Kaji (403 sans session ; la session peut s'ouvrir avec ce jeton si `KAJI_ADMIN_USE_KAJI_TOKEN` est activée, voir `docs/api/admin-session.md`). Une seule entrée à la fois ; aucune écriture en masse.

| Route | Rôle |
|---|---|
| `POST /preview` | **n'écrit rien** : `{allowed, reason, entry_exists, would_change, existing_entries, role_privs, effective_before, estimate_after, note}` |
| `PUT /` | ajoute ou retire **une** entrée ; exige `confirm: true` et `type_name` = l'identifiant retapé |

Corps (aperçu et écriture) : `{action: "add"|"remove", path, kind: "user"|"group"|"token", ugid, role, propagate}` ; l'écriture ajoute `{confirm, type_name}`.
Réponse de l'écriture : `{applied: true, action, path, ugid, role}`. Proxmox est **relu après l'écriture** : si l'état ne correspond pas, la route répond 502 au lieu d'affirmer un succès.

## Interdits absolus (vérifiés côté serveur, même avec toutes les confirmations)
- **Chemins** en liste blanche : `/pool/<id>`, `/vms/<vmid>`, `/storage/<id>`, `/nodes/<nœud>`. Jamais `/`, `/access…`, `/sdn…`, ni un chemin « parent » (`/vms`, `/pool`, `/storage`, `/nodes`). Refus 422, **sans aucun appel à Proxmox**.
- **Rôles** (relus chez Proxmox au moment de l'action) : jamais `Administrator` ni un rôle qui porte `Permissions.Modify`, `User.Modify`, `Group.Allocate`, `Realm.Allocate` ou `Realm.AllocateUser` (403). Un rôle inconnu est refusé. **Retirer** une entrée est permis pour tout rôle (retirer un droit ne l'augmente jamais).
- **Identités protégées** : `root@pam`, le compte et le token de Kaji, le compte et le token de la session administrateur, **tout token d'un de ces comptes**, et **tout groupe qui en contient un membre** (403), en ajout comme en retrait.
- **Identifiants** : formats stricts (`user@realm`, groupe, `user@realm!jeton`) ; une liste séparée par des virgules est refusée (une cible à la fois).
- **Confirmation** : `confirm=true` **et** l'identifiant retapé, vérifiés avant toute lecture chez Proxmox (400).
- Doublon : ajouter une entrée existante → 409 ; retirer une entrée absente → 404.

## Aperçu
Proxmox ne simule pas une écriture. L'aperçu montre les entrées déjà présentes pour cet identifiant et ce chemin, les privilèges du rôle, les droits effectifs actuels de l'utilisateur ou du token sur le chemin
(`GET /access/permissions`, héritage compris) et une **estimation** après un ajout (union des deux). Pour un groupe, les droits effectifs ne sont pas calculés. Pour un retrait, pas d'estimation.

## Audit
`acl-add` et `acl-remove` (succès, refus et erreur) : « ajouter PVEAuditor pour eve@pve sur /pool/kaji-test (propagate=1) ». Aucun secret : ni le token d'administration, ni celui de Kaji.
