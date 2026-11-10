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
- `dry_run=true` : renvoie `locks` (`cut`, `live`, `inert`), `phrase`, `params` (ou `remove`), et pour migrer / relocaliser `from`, `comigrated` (ressources en affinité positive qui partiraient avec) et `ignored` (voir ci-dessous). N'écrit rien et n'exige pas `confirm`.
- `confirm=true` obligatoire (400 sinon), strict.

## Contrôles avant d'écrire
Machine inconnue ou de mauvais type (404), modèle (422), déjà en HA (409) ; ressource ou règle inconnue (404) ; règle au nom déjà pris (409) ; ressources d'une règle absentes de la HA (422) ; nœuds inconnus (422) ; type de règle non modifiable (422) ; `resource-affinity` : `affinity` obligatoire, au moins 2 ressources, ni `nodes` ni `strict` ; nœud cible inconnu, hors ligne ou égal au nœud actuel ; retrait d'une ressource encore citée par une règle (409, aucune règle n'est modifiée en douce).
Champs en liste blanche ; **commentaires : ASCII imprimable seulement** (500 caractères max.) : constaté en réel, Proxmox altère les accents d'un commentaire de règle HA (« è » revient en `U+FFFD`), Kaji refuse donc ces caractères (422) ; un champ inconnu n'est jamais transmis. Après chaque écriture, l'état est **relu** : si Proxmox ne l'a pas appliqué, 502.

## Audit
Actions `ha-resource-create|update|delete`, `ha-rule-create|update|delete`, `ha-migrate`, `ha-relocate`, refus compris. Le commentaire n'est jamais copié dans l'audit (« défini »).

## Réponses
Création / modification : `{created|changed, removed, locks}`. Migrer / relocaliser : `{requested, from, blocking[{sid, cause}], comigrated[], ignored[], locks}` — la HA décide ensuite, le suivi se fait par l'état HA.

## Validé en réel par l'interface web (2026-11-09, VM jetable 117, tout remis à l'identique)
Ajouter une machine (`stopped`), modifier (déplacements max., commentaire), créer puis modifier une règle `node-affinity` (nœuds, priorités, stricte), migrer `enzo` → `enzo2`, supprimer la règle, retirer la ressource ; verrous et phrase `COUPURE POSSIBLE` vus à l'écran. **Constaté** : le commentaire accentué d'une règle est altéré par Proxmox (corrigé : ASCII seulement) ; une **relocalisation vers `enzo` est ignorée par la HA tant qu'une règle stricte préfère `enzo2`** (la demande est acceptée, rien ne bouge, Kaji ne le signale pas encore).

## Validation
Faux Proxmox strict (`backend/tests/test_ha_write.py`). **Rien n'a été écrit sur le cluster réel** : le cluster n'a que 2 nœuds (activer la HA arme le chien de garde). Les paramètres viennent du schéma d'API officiel de Proxmox (`apidoc.js`).

## Demande ignorée par une règle stricte
Quand une règle `node-affinity` **stricte et active** vise la machine (ou une machine qui partirait avec elle) et n'autorise pas le nœud demandé, la HA **ignore** la demande : Proxmox répond 200, rien ne bouge. Kaji ne bloque pas (c'est le comportement de Proxmox) mais **le signale** : `ignored[{rule, resources[], nodes[]}]` dans l'aperçu (`dry_run`) et dans la réponse, affiché en rouge dans la fenêtre Migrer / Relocaliser (avant et après l'envoi). Une règle non stricte, désactivée, ou qui autorise le nœud cible n'est pas signalée. L'audit ajoute les noms des règles à l'entrée `started`.
