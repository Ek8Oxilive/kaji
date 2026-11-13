# Images OCI (M14, lot #405)

Préfixe `/api/connections/{conn_id}/nodes/{node}`. Proxmox 9 sait faire télécharger une image OCI par le nœud dans un stockage de modèles. Bouton **« Télécharger une image OCI… »** du tiroir d'un stockage qui accepte les modèles de conteneur (page « Stockage »).
Schéma lu sur `apidoc.js` de Proxmox 9 : `allowtoken: 1` pour les deux routes. Validation : `backend/app/ocispec.py` (motifs du schéma, compilés en ASCII).

| Route | Droit | Effet |
|---|---|---|
| `GET /oci/tags?reference=` | `Sys.AccessNetwork` sur le nœud | Étiquettes d'un dépôt (`[registre/]dépôt`, **sans** étiquette) : requête faite par le nœud, rien n'est téléchargé |
| `POST /storage/{storage}/oci-pull` | `Datastore.AllocateTemplate` sur le stockage et `Sys.AccessNetwork` sur le nœud | `{ reference, filename?, confirm }` : le nœud télécharge l'image (tâche longue, `upid` suivi par l'interface) |

- **`confirm=true` exigé** (400 sinon) : le nœud sort sur Internet.
- **Registre local refusé** (422) : `localhost`, `*.localhost`, boucle locale, adresse non spécifiée, lien local, multicast, réservée (le réseau privé est accepté, comme pour les URL de téléchargement). Le premier segment est un registre s'il contient « . » ou « : » ou vaut `localhost` (convention de Docker).
- Référence : `[registre/]dépôt:étiquette` selon le motif de Proxmox ; nom de fichier facultatif : 101 caractères, pas de `..`. Aucun identifiant de registre n'est géré : **images publiques seulement**.
- Une image déjà présente est refusée par Proxmox. Étiquettes renvoyées : valides seulement, 500 au plus. Audit `storage-oci-pull` (stockage, référence, nœud, `upid`) ; le nom de fichier choisi n'y figure pas.

## Validation
Faux Proxmox strict (`backend/tests/test_oci.py` : seuls `reference` et `filename` acceptés, motifs, registres locaux, étiquettes hostiles, erreurs sans fuite, 401), 48 tests, 9 mutations tuées (1 équivalente).
**Essai réel** : voir `docs/REPRISE.md`. **Non couvert** : créer un conteneur « application » depuis l'image (l'assistant de création liste les modèles `vztmpl`, pas les images OCI).
