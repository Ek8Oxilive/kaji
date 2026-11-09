# Télécharger un modèle de conteneur du catalogue officiel (lot #147)

> **Non validé en réel** (PC B, faux Proxmox strict). Fichiers : `routers/aplinfo.py`, `tests/test_aplinfo.py`, `components/TemplateCatalogDialog.tsx`
> (assistant de création LXC et tiroir d'un stockage de modèles), `lib/types/modeles-lxc.ts`. La liste (`downloadable`) et les modèles présents
> (`local`) existent déjà : `GET /nodes/{node}/templates` (`routers/resources.py`).

| Route | Corps | Rôle |
|---|---|---|
| `POST /api/connections/{id}/nodes/{node}/aplinfo` | `{storage, template}` | télécharge un modèle du catalogue vers un stockage ; `202 {upid, node, storage, template}` (tâche à suivre avec `/tasks/{node}/{upid}`) |

Droit Proxmox : `Datastore.AllocateTemplate` sur `/storage/{storage}`. Audit : `template-download` (succès, refus, erreurs).

## Garde-fous (tous côté serveur, dans cet ordre, aucun appel d'écriture avant la fin des contrôles)
1. `storage` (`[A-Za-z][A-Za-z0-9._-]{0,63}`) et `template` (`[A-Za-z0-9][A-Za-z0-9._+-]{0,254}`, sans `..`) validés par `fullmatch` : sinon **422, sans aucun appel à Proxmox**.
2. **Aucune URL, aucune somme de contrôle** : le corps ne transmet que `storage` et `template` (champs inconnus ignorés). Proxmox vérifie lui-même.
3. Le nom doit figurer dans le catalogue **relu chez Proxmox** (`GET /nodes/{node}/aplinfo`, type `lxc`) : sinon **422**.
4. Le stockage doit accepter `vztmpl` et être actif sur ce nœud (relu : `GET /nodes/{node}/storage?content=vztmpl`) : sinon **422**.
5. Modèle déjà présent sur ce stockage (`{storage}:vztmpl/{template}` relu) : **409**.

## Interface
Bouton « Télécharger un modèle… » à l'étape Modèle de l'assistant LXC (stockage au choix parmi ceux du nœud) et « Télécharger un modèle de conteneur »
dans le tiroir d'un stockage qui accepte les modèles (stockage fixé). Recherche, filtre par section (`system`, `turnkeylinux`, `mail`…), « Déjà présent »
sur le stockage choisi, progression par `runTask` (30 min max). La liste est tronquée à 300 entrées côté `GET …/templates` ; le serveur, lui, valide sur
le catalogue **complet**.

## Non validé en réel (essais du ticket, PC A)
- l'acceptation par Proxmox de `storage` + `template` sur `POST /nodes/{node}/aplinfo` et la durée réelle du téléchargement ;
- la forme exacte du catalogue (`type`, `template`, `section`) : tirée des schémas, jamais observée ;
- le nom de fichier des modèles présents (`volid` = `{storage}:vztmpl/{template}`) : supposé identique au nom du catalogue ;
- un nœud sans accès Internet (catalogue vide ou erreur) : message affiché, non essayé ;
- l'interface n'a pas été ouverte dans un navigateur (seul `npm run build` la valide).
