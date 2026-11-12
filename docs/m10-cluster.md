# M10 : gestion du cluster, cadrage de l'écriture (option B retenue le 2026-11-12)

**Livré (M10-1)** : lecture (`docs/api/cluster.md`) et page « Cluster » avec des commandes à copier. **Livré (M10-2, décision d'Enzo du 2026-11-12 « fais M10 » = option B)** : créer, joindre et retirer un nœud par l'API avec verrous (`docs/api/cluster-ecriture.md`), validés sur faux Proxmox seulement ; les commandes à copier restent affichées.

## Ce que fait Proxmox (Datacenter → Cluster) et ce que couvre Kaji
| Fonction Proxmox | Kaji |
|---|---|
| Informations du cluster (nom, version de configuration, nœuds, quorum) | ✅ lecture |
| Tableau des nœuds (ID, nom, votes, liens 0 à 7) | ✅ lecture (+ état et empreinte) |
| Join Information (adresse, empreinte) | ✅ lecture, intégrée aux commandes |
| QDevice (état) | ✅ lecture ; l'installation est en ligne de commande chez Proxmox aussi (`pvecm qdevice setup`) |
| Créer un cluster (nom, liens) | commande à copier (`pvecm create`) |
| Joindre un cluster (information, mot de passe, liens) | commande à copier (`pvecm add`) |
| Retirer un nœud | commande à copier (`pvecm delnode`) : Proxmox n'a pas de bouton non plus |

API Proxmox d'écriture : `POST /cluster/config` (créer), `POST /cluster/config/join` (joindre : exige `hostname`, `fingerprint` et le **mot de passe root** du nœud contacté), `DELETE /cluster/config/nodes/{node}`.

## Pourquoi Kaji n'écrit pas (recommandation)
1. **Mot de passe root** : joindre un cluster l'exige ; Kaji ne manipule jamais de mot de passe d'un nœud (règle du projet).
2. **Risque de casser le quorum** et de perdre l'accès à tout le cluster ; **joindre écrase `/etc/pve` du nouveau nœud** (il ne doit héberger aucune machine).
3. **Aucun banc d'essai** : le cluster réel n'a pas la RAM pour un Proxmox imbriqué (2 à 3 VM Proxmox). Une écriture ne serait testée que sur un faux Proxmox.
4. Ce sont des opérations rares (une fois dans la vie du cluster).

## Décisions à prendre par Enzo
- **A. Rester aux commandes à copier (recommandé, livré).**
- **B. Écriture par l'API avec verrous** (`dry_run`, phrase `COUPURE POSSIBLE`, nœud à joindre sans machine, aucune manipulation du mot de passe : saisi une fois par l'utilisateur, non journalisé), validée seulement sur faux Proxmox : à faire si un banc d'essai devient possible.
- **C. Ne jamais l'implémenter.**

Décision d'Enzo : **B** (2026-11-12). Les commandes à copier (A) restent comme autre voie.
