# Réplication en écriture (M8-3)

Préfixe `/api/connections/{conn_id}/replication`. Lecture : `docs/api/ha.md` (`GET /replication`, état et journal par nœud). Droit requis chez Proxmox : `VM.Replicate` sur `/vms/<vmid>` (page « Accès » : `replication-write`).
**Réplication de stockage de Proxmox = ZFS obligatoire** sur la source et la cible. Le cluster réel n'a pas de ZFS : l'écriture y est bloquée, et `dry_run` explique pourquoi.

| Route | Corps / paramètres | Effet |
|---|---|---|
| `POST /replication` | `guest` (identifiant), `target` (nœud), `schedule`, `rate` (Mo/s, ≥ 1), `comment`, `disable` | Crée un job. L'identifiant `ID-n` est choisi par Kaji (premier `n` libre) |
| `PUT /replication/{job}` | `schedule`, `rate`, `comment`, `disable`, `clear` (`schedule`, `rate`, `comment`, `disable`) | Modifie ; `digest` relu et envoyé |
| `DELETE /replication/{job}` | query : `confirm`, `acknowledge_live`, `keep`, `type_name`, `dry_run` | Marque le job pour suppression |
| `POST /replication/{job}/now` | verrous (`confirm`, `acknowledge_live`, `dry_run`) | `schedule_now` sur le nœud **source** du job |

Verrous : `confirm=true` strict (400 sinon) ; `dry_run=true` n'écrit rien et n'exige pas `confirm`.

## Verrous et contrôles
- **Bloqueurs (409)**, annoncés par `dry_run` (`blockers[]`, `blocked`) : aucun stockage ZFS sur le cluster ; un disque de la machine (hors CD/DVD) sur un stockage non ZFS ou inconnu. Proxmox refuserait : Kaji le dit avant.
- **Machine protégée** (`KAJI_PROTECTED_VMIDS`, dont Kaji) : pas de nouveau job ni de lancement immédiat (403, même en `dry_run`). Modifier ou supprimer un job existant reste permis.
- **Création** : machine connue (404), pas un modèle (422), cible = autre nœud que celui de la machine, en ligne (422), pas déjà répliquée vers cette cible (409), au plus 16 jobs par machine.
- **Effet direct (409)** : modifier, supprimer un job existant ou le lancer maintenant exige `acknowledge_live=true`. Créer est sans verrou (la première synchronisation suit la planification).
- **Suppression** : Proxmox ne retire pas le job tout de suite, il le marque (`remove_job`) et le supprime au prochain passage sur le nœud source. Sans `keep=true`, les **copies sur le nœud cible sont détruites** : `type_name` doit alors être le nom exact du job (400 sinon). Un job marqué ne peut plus être modifié, lancé ni supprimé de nouveau (409). `force` n'est pas exposé.
- Planification : calendrier systemd en liste blanche de caractères (≤ 128), jamais vide. Champs inconnus (`source`, `remove_job`, `type`, `id`…) jamais transmis. Commentaire sans caractère de contrôle (≤ 500).
- Après chaque écriture, l'état est relu (502 si Proxmox n'a pas appliqué).

## Audit
`repl-create`, `repl-update`, `repl-delete`, `repl-now`, refus compris. Le commentaire n'est jamais copié dans l'audit (« défini »).

## Validation
Faux Proxmox strict (`backend/tests/test_repl_write.py`), 32 mutations tuées. **Jamais écrit en réel** : pas de ZFS sur le cluster ; seul `dry_run` y est utilisable (il annonce « aucun stockage ZFS »).
