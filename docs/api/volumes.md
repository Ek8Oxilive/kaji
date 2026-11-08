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
