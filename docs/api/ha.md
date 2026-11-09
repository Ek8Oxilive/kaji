# Haute disponibilité et réplication (M8-1, lecture seule)

Préfixe `/api/connections/{conn_id}`. Rien n'est écrit : les écritures (M8-2 HA, M8-3 réplication) viendront avec leurs verrous.

| Route | Contenu |
|---|---|
| `GET /ha/status` | Quorum, maître, LRM, chien de garde (`fencing`, `armed_state`), services HA (`sid`, `state`, `request_state`) |
| `GET /ha/resources` | Ressources HA : `sid` (`vm:100`, `ct:101`), `state`, `max_restart`, `max_relocate`, `failback`, `comment` |
| `GET /ha/rules` | Règles HA : `node-affinity` (`nodes` avec priorité, `strict`) et `resource-affinity` (`affinity` positive/négative) |
| `GET /replication` | Jobs de réplication : `id` (`100-0`), `guest`, `source`, `target`, `schedule`, `rate`, `disable`, `comment` |
| `GET /nodes/{node}/replication` | État des jobs dont le nœud est la source : `last_sync`, `next_sync`, `duration`, `fail_count`, `error` |
| `GET /nodes/{node}/replication/{job}/log?limit=` | Journal d'un job (texte borné) |

Mise en forme en liste blanche : identifiants validés (`vm:ID`, `ct:ID`, `ID-N`, noms de nœud), textes bornés sans caractère de contrôle, entrées étrangères écartées.

## Particularités du cluster réel (constatées en lecture, 2026-11-09)
- **2 nœuds** (`enzo`, `enzo2`) : quorum fragile. Activer la HA arme un chien de garde ; si un nœud tombe, l'autre perd le quorum et redémarre de lui-même. Les écritures HA exigeront donc une phrase de confirmation.
- Les **groupes HA** n'existent plus (`/cluster/ha/groups` répond « migrated to rules ») : seules les **règles** existent.
- Aucune ressource HA, aucune règle, aucun job de réplication. **Pas de stockage ZFS** (seulement `local` et `local-lvm`) : la réplication ne peut pas être créée sur ce cluster.
- Page « Haute dispo » du menu : état, ressources, règles, jobs.
