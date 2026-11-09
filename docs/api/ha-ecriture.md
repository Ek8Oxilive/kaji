# Haute disponibilité en écriture (M8-2)

Préfixe `/api/connections/{conn_id}/ha`. Lecture : `docs/api/ha.md`. Droit requis chez Proxmox pour **toutes** ces routes : `Sys.Console` sur `/` (schéma d'API officiel). Sans lui : « Droits insuffisants » (502).
Les groupes HA n'existent plus : seules les **règles** (`node-affinity`, `resource-affinity`) existent.

| Route | Corps / paramètres | Effet |
|---|---|---|
| `POST /resources` | `sid` (`vm:ID` / `ct:ID`), `state`, `max_restart` (0-10), `max_relocate` (0-10), `failback`, `comment` | Ajoute une machine à la HA |
| `PUT /resources/{sid}` | mêmes champs sans `sid`, `clear` (`comment`, `max_restart`, `max_relocate`, `failback`) | Modifie ; `digest` relu et envoyé (refus si la configuration a bougé) |
| `DELETE /resources/{sid}` | verrous en **query** | Retire de la HA (la machine n'est pas touchée) ; envoie `purge=0` |
| `POST /resources/{sid}/migrate` | `node` | Migration demandée à la HA (asynchrone) |
| `POST /resources/{sid}/relocate` | `node` | Relocalisation (arrêt, déplacement, redémarrage), asynchrone |
| `POST /rules` | `rule`, `type`, `resources[]`, `nodes[{node, priority}]`, `strict`, `affinity`, `disable`, `comment` | Crée une règle |
| `PUT /rules/{rule}` | `type` (identique à l'existant), mêmes champs, `clear` (`comment`, `disable`, `strict`) | Modifie |
| `DELETE /rules/{rule}` | verrous en query | Supprime la règle |

Chaque corps accepte aussi les **verrous** : `confirm`, `acknowledge_live`, `acknowledge_cut_access`, `type_name`, `dry_run` (tous booléens stricts, sauf `type_name`).

## Verrous (décidés par le serveur sur l'état relu chez Proxmox)
- **Interdit, même confirmé (403)** : une machine de `KAJI_PROTECTED_VMIDS` (105, 108, 116 = Kaji) ne peut ni entrer en HA, ni être modifiée, migrée, relocalisée, ni figurer dans une règle. Migrer une machine **entraînant** une protégée par une affinité positive active est refusé aussi. Seul **retirer** une protégée de la HA reste permis (sens sûr).
- **Coupure possible (409)** : cluster à moins de 3 nœuds. Il faut `acknowledge_cut_access=true` **et** `type_name="COUPURE POSSIBLE"`. Concerne tout ce qui active ou déplace de la HA (créer, modifier une ressource active, migrer, relocaliser, créer ou modifier une règle active). Retirer, ou créer / modifier du désactivé (`state` `ignored` / `disabled`, règle `disable`), ne l'est pas.
- **Effet immédiat (409)** : modifier, migrer, relocaliser ou retirer ce que la HA gère déjà, ou créer ce qui sera géré tout de suite : `acknowledge_live=true`.
- `dry_run=true` : renvoie `locks` (`cut`, `live`, `inert`), `phrase`, `params` (ou `remove`), et pour migrer / relocaliser `from` et `comigrated` (ressources en affinité positive qui partiraient avec). N'écrit rien et n'exige pas `confirm`.
- `confirm=true` obligatoire (400 sinon), strict.

## Contrôles avant d'écrire
Machine inconnue ou de mauvais type (404), modèle (422), déjà en HA (409) ; ressource ou règle inconnue (404) ; règle au nom déjà pris (409) ; ressources d'une règle absentes de la HA (422) ; nœuds inconnus (422) ; type de règle non modifiable (422) ; `resource-affinity` : `affinity` obligatoire, au moins 2 ressources, ni `nodes` ni `strict` ; nœud cible inconnu, hors ligne ou égal au nœud actuel ; retrait d'une ressource encore citée par une règle (409, aucune règle n'est modifiée en douce).
Champs en liste blanche, textes sans caractère de contrôle (500 caractères max.) ; un champ inconnu n'est jamais transmis. Après chaque écriture, l'état est **relu** : si Proxmox ne l'a pas appliqué, 502.

## Audit
Actions `ha-resource-create|update|delete`, `ha-rule-create|update|delete`, `ha-migrate`, `ha-relocate`, refus compris. Le commentaire n'est jamais copié dans l'audit (« défini »).

## Réponses
Création / modification : `{created|changed, removed, locks}`. Migrer / relocaliser : `{requested, from, blocking[{sid, cause}], comigrated[], locks}` — la HA décide ensuite, le suivi se fait par l'état HA.

## Validation
Faux Proxmox strict (`backend/tests/test_ha_write.py`). **Rien n'a été écrit sur le cluster réel** : le cluster n'a que 2 nœuds (activer la HA arme le chien de garde). Les paramètres viennent du schéma d'API officiel de Proxmox (`apidoc.js`).
