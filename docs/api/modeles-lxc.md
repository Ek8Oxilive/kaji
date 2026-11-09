# Télécharger un modèle de conteneur du catalogue officiel (lot #147)

> **Validé en réel le 2026-11-09 (PC A, nœud `enzo2`)** : voir « Validé en réel » en bas de page. Fichiers : `routers/aplinfo.py`, `tests/test_aplinfo.py`, `components/TemplateCatalogDialog.tsx`
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

**Architecture (ticket #205)** : `GET …/templates` renvoie aussi `node_architecture` (`amd64`, `arm64`, `armhf`, `riscv64`, ou `null`), déduite de
`current-kernel.machine` de `GET /nodes/{node}/status` (`x86_64` → `amd64`, `aarch64` → `arm64`) ; statut illisible : `null`, le reste de la réponse n'est pas
touché. Le dialogue ne montre par défaut que les modèles de cette architecture (et ceux sans architecture) ; la case « Afficher aussi les autres
architectures » les rend visibles. Le serveur, lui, ne filtre pas le téléchargement.

## Validé en réel (2026-11-09, PC A, `local` du nœud `enzo2`)
- **Redéploiement nécessaire** : le déploiement du jour n'avait pas la route (404) ; après `git pull` + build du CT 116 (`main` 6f74226), tout marche.
- **Catalogue** : 136 entrées, sections `mail`, `system`, `turnkeylinux` ; champs observés `template`, `os`, `version`, `section`, `architecture`, `description` ;
  la recherche « alpine » filtre (3 résultats). Écart **#205** (corrigé, voir plus haut) : le modèle `arm64` était proposé sur un nœud amd64.
- **Téléchargement** d'`alpine-3.23-default_20261105_amd64.tar.xz` : tâche `download` réussie en **2 s** (3 450 920 octets), `volid` =
  `local:vztmpl/alpine-3.23-default_20261105_amd64.tar.xz` (**identique au nom du catalogue**), bouton passé à « Déjà présent », modèle visible dans l'assistant LXC.
- **409** (« Ce modèle est déjà présent sur ce stockage ») et **422** (`debian-99` : « Ce modèle ne figure pas dans le catalogue officiel de Proxmox » ; `../x` :
  « Nom de modèle invalide » ; stockage inexistant ou `local-lvm` : « Ce stockage n'accepte pas les modèles de conteneur (vztmpl) ou n'est pas actif sur ce
  nœud ») : **aucune tâche créée** chaque fois.
- **Assistant LXC** : le bouton « Télécharger un modèle… » ouvre le même dialogue ; un modèle téléchargé avant l'ouverture figure dans la liste mais **n'est pas
  sélectionné** automatiquement. Audit `template-download` : `started` / `error`, sans secret.
- Suppression du modèle d'essai par `DELETE …/storage/local/files/vztmpl/{nom}?confirm=true&typed={nom}` : réussie (tâche `imgdel`).

## Non validé en réel
- un nœud sans accès Internet (catalogue vide ou erreur) : message affiché, non essayé ;
- le téléchargement depuis le tiroir d'un autre stockage que `local` ; un modèle volumineux (TurnKey, Debian : la durée réelle d'un gros téléchargement n'est pas mesurée).
