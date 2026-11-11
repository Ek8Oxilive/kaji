# Barre de tâches permanente (lecture seule)

Bande en bas de chaque page (sauf la page « Tâches », qui montre déjà tout), comme celle de l'interface de Proxmox.

- **Aucune route nouvelle** : elle lit `GET /api/connections/{id}/tasks?limit=6` (voir `taches.md`), tous nœuds confondus, les plus récentes d'abord.
- Affiche « N en cours » ou « Aucune tâche en cours », le nombre d'échecs récents, puis les 6 dernières tâches (état en couleur **et** en mot, nom lisible, machine, nœud, durée).
- Un clic sur une tâche ouvre son journal (le même tiroir que la page « Tâches », suivi en direct tant qu'elle tourne).
- Rafraîchie toutes les 3 s quand une tâche tourne, toutes les 15 s sinon ; en pause quand l'onglet du navigateur est caché.
- Repliable (▾ / ▸) ; le choix est gardé dans le navigateur (`localStorage`, sans effet si le stockage est refusé).
- « Toutes les tâches » ouvre la page « Tâches » (filtres, recherche, plus de lignes).
- Aucune écriture : Kaji n'annule ni ne supprime aucune tâche.
