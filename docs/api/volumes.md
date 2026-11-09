# Volumes d'un stockage : protéger, supprimer, élaguer

Préfixe : `/api/connections/{id}/nodes/{node}/storage/{storage}`. Droits Proxmox : `Datastore.Allocate` sur le stockage (ou `Datastore.AllocateSpace` + `VM.Backup`
pour les sauvegardes). Audit : `backup-protect`, `backup-unprotect`, `file-delete`, `storage-prune` (refus compris).

| Route | Rôle |
|---|---|
| `PUT /backups/{fichier}/protect` `{protected}` | protège une sauvegarde (plus de suppression ni d'élagage) ou retire la protection. Réversible, sans confirmation |
| `DELETE /files/{kind}/{nom}?confirm=true&typed={nom}` | supprime définitivement une ISO, un modèle, un snippet ou une image (`kind` : `iso`, `vztmpl`, `snippets`, `import`) |
| `POST /prune/preview` | **aperçu** de l'élagage calculé par Proxmox, rien n'est supprimé |
| `POST /prune` | exécute l'élagage (tâche, `upid`) |

## Garde-fous
- **Volume relu chez Proxmox** à chaque action (jamais une valeur du navigateur) : introuvable → 404, type inattendu → 409.
- **Suppression d'un fichier** : `confirm=true` et nom exact retapé. Les disques de machines (`images`, `rootdir`) et les sauvegardes sont **refusés** par cette route (404/422), même avec toutes les confirmations : ils ont leurs propres routes.
  Kaji ne vérifie **pas** si une machine utilise encore le fichier (ISO montée, par exemple).
- **Protection** : fichier vzdump seulement (`vzdump-qemu|lxc-…`), comme la suppression de sauvegarde ; les sauvegardes d'un PBS ne se protègent pas d'ici.
- **Élagage en deux temps** :
  1. `POST /prune/preview` `{retention?, vmid?, guest_type?}` → `{items:[{volid, vmid, type, date, mark}], counts, remove}`. `mark` : `keep`, `remove`, `protected`, `renamed` (nom non standard : ignorée). Sans `retention`, Proxmox applique les règles du stockage.
  2. `POST /prune` avec les **mêmes** champs plus `confirm: true`, `type_name` (nom du stockage retapé) et `expected_remove` (le nombre vu dans l'aperçu). L'aperçu est **recalculé** à l'appel : si le nombre a changé → 409, rien n'est supprimé ; s'il est nul → 422.
  Un `mark` inconnu ne compte jamais comme « à supprimer » ; les sauvegardes protégées ne sont jamais touchées. Aperçu et exécution envoient exactement les mêmes paramètres à Proxmox.
- `retention` : `keep_all` (exclut les autres règles), `keep_last`, `keep_hourly`, `keep_daily`, `keep_weekly`, `keep_monthly`, `keep_yearly` (1 à 9999). Vide ou contradictoire → 422.
- L'élagage n'est pas proposé pour un stockage PBS (il se règle sur le PBS).

## Copier un fichier (lot #148) : `POST /copy/{kind}/{name}`
Préfixe `/api/connections/{conn_id}/nodes/{node}/storage/{storage}`. Corps : `{target_storage, target_node?, target_name?, dry_run?}`. Types : `iso`, `vztmpl`, `snippets`, `import`, `backup` (fichier vzdump) ; **pas** `images` ni `rootdir` (422, ils ont leurs propres routes). Réponse : `{upid, source, target, target_node, node}`.

**API de Proxmox expérimentale** : la doc officielle de `POST /nodes/{node}/storage/{storage}/content/{volume}` dit « Copy a volume. This is experimental code - do not use. » et l'interface de Proxmox n'offre pas cette fonction. Kaji la propose avec toutes les protections ci-dessous ; son comportement réel est décrit plus bas.
- **Rien n'est écrasé** : la source est relue (404 si absente, type inattendu refusé), le nœud de destination doit exister (`/nodes`), le stockage de destination doit accepter ce type de contenu et être actif (relus), et **un fichier de même nom déjà présent = 409** sans aucun appel d'écriture. La destination identique à la source = 422. Une liste illisible = 502, jamais « rien n'existe ».
- Noms : `FILE_NAME` pour les fichiers, format vzdump pour les sauvegardes, stockage `^[A-Za-z][A-Za-z0-9._-]{0,63}$`, nœud validé : **aucune requête vers Proxmox** avant ces contrôles (un nom invalide ne se retrouve jamais dans un chemin).
- Paramètres envoyés : `target` (volid complet de destination) et `target_node` **seulement** pour un autre nœud (Proxmox refuse sinon). Un champ inconnu n'est jamais transmis. La source n'est **jamais** supprimée.
- `dry_run=true` : renvoie la source et la cible sans écrire. Audit `volume-copy` (succès et refus). Droit côté Proxmox : `Datastore.AllocateSpace` sur le stockage de destination.
