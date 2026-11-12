# Section « Réplication » sur la page d'un nœud

Frontend seul, **aucune route nouvelle** : la section filtre `GET /api/connections/{id}/replication` sur les jobs dont le nœud est la **source ou la cible**, et lit l'état de chaque job (dernière et prochaine synchro, échecs) sur son nœud source avec `GET /api/connections/{id}/nodes/{node}/replication`.

| Bouton | Fenêtre | Écriture |
|---|---|---|
| Nouveau job… | `ReplDialog` (nouveau) | `POST /replication` (voir `replication-ecriture.md`) |
| Modifier / Lancer maintenant / Supprimer | `ReplDialog` | `PUT`, `POST …/now`, `DELETE` du job |

Les aperçus `dry_run`, les verrous et le nom retapé sont ceux de la page « HA » (même fenêtre). Sans stockage ZFS (cas du cluster réel), « Nouveau job… » liste les bloqueurs et « Appliquer » reste grisé.
