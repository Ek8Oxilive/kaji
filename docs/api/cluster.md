# Cluster en lecture (M10-1)

Une seule route, `GET /api/connections/{conn_id}/cluster/config`, droit `Sys.Audit` sur `/` (le droit « voir » de la page « Accès » suffit). **Lecture seule** : Kaji ne crée, ne joint ni ne retire aucun nœud (`docs/m10-cluster.md`).

Elle agrège cinq appels Proxmox : `/cluster/status`, `/cluster/config/nodes`, `/cluster/config/totem`, `/cluster/config/qdevice`, `/cluster/config/join`. Une sous-requête qui échoue (droit manquant, nœud isolé sans `corosync.conf`) n'empêche pas les autres : son message court est dans `errors`.

| Champ | Contenu |
|---|---|
| `cluster` | `name`, `quorate`, `version` (de la configuration corosync), `nodes_total`, `clustered` (faux = nœud isolé) |
| `nodes[]` | une ligne par nœud : `name`, `nodeid`, `online`, `ip`, `local` (nœud interrogé), `votes`, `links[{link, addr}]` (liens corosync 0 à 7), `fingerprint` (empreinte SHA-256 du certificat) |
| `totem` | `cluster_name`, `config_version`, `ip_version`, `link_mode`, `secauth`, `transport`, `links[]` ; `null` si absent |
| `qdevice` | `configured`, `info{clé: court texte}` (20 au plus) |
| `join` | `preferred_node`, `address`, `fingerprint`, `nodes` : équivalent du bouton « Join Information » de Proxmox |
| `errors` | `{partie: message}` |

Mise en forme **en liste blanche** : le schéma officiel de `nodes`, `totem` et `qdevice` est vide, seuls des champs connus et validés (noms, adresses, empreinte, bornes) sortent. Aucune clé d'authentification corosync n'est lue ni renvoyée. Aucune valeur de Proxmox n'est jamais copiée telle quelle dans une erreur.

Page « Cluster » du menu : informations, nœuds, QDevice, et trois commandes **à copier** (`pvecm create`, `pvecm add … --fingerprint …`, `pvecm delnode`), préremplies avec le nom et l'information de jonction.

## Constaté en réel (2026-11-09, cluster `Enzo-Cluster`, 2 nœuds)
- `/cluster/config/nodes` renvoie `name`, `nodeid`, `quorum_votes`, `ring0_addr` mais **ni empreinte ni `pve_addr`** : Kaji prend l'empreinte du certificat de chaque nœud dans la liste de jonction (`/cluster/config/join` → `nodelist`).
- `/cluster/config/totem` : `cluster_name`, `config_version`, `ip_version`, `link_mode`, `secauth`, `interface` (liens). `/cluster/config/qdevice` : objet vide sans QDevice.
- Pas de QDevice, un seul lien (`link0`), quorum atteint ; la page affiche ces valeurs telles que Proxmox les donne.
