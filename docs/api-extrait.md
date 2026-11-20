# API de Kaji : extrait

> Retour au [README](../README.md).

Kaji expose environ **360 routes**. Ce tableau n'en montre qu'une partie (les premières) ; la liste complète, avec le rôle de chaque fichier, est dans [docs/CARTE.md](CARTE.md), et chaque fonction a sa fiche dans [`docs/api/`](api/). Toutes les routes, sauf 5 (`/api/health` et quatre de `/api/auth/`), demandent une session ; les écritures sont **réservées aux administrateurs**, sauf les actions d'alimentation et les snapshots (rôle `operator`).

| Route | Rôle |
|---|---|
| `POST /api/auth/setup` · `login` · `logout` · `GET /api/auth/me` | Compte admin et session. `logout` **révoque** la session côté serveur. |
| `POST /api/auth/logout-all` | Révoque toutes les sessions du compte |
| `POST /api/auth/password` | Change le mot de passe (l'actuel est exigé) ; révoque les autres sessions |
| `GET/POST /api/connections` | Lister / ajouter un cluster Proxmox |
| `GET/PATCH/DELETE /api/connections/{id}` | Voir / modifier / supprimer (le token n'est jamais renvoyé) |
| `POST /api/connections/test` | Tester des identifiants avant de les enregistrer |
| `POST /api/connections/{id}/test` | Tester une connexion enregistrée |
| `GET /api/connections/{id}/cluster/status` | Nom du cluster, quorum, nœuds en ligne ou non |
| `GET /api/connections/{id}/nodes` | Nœuds : CPU, RAM, disque, uptime |
| `GET /api/connections/{id}/guests` | Liste unifiée des VM (qemu) et LXC, filtrable par `?node=` |
| `GET /api/connections/{id}/storages` | Stockages et usage |
| `GET /api/connections/{id}/events` | Flux temps réel (SSE) : un instantané de l'état du cluster (statut, nœuds, machines) à chaque changement. Un seul interrogateur Proxmox par cluster, partagé par tous les navigateurs ; il s'arrête quand le dernier part. |
| `POST /api/connections/{id}/guests/{node}/{qemu\|lxc}/{vmid}/{action}` | `start`, `shutdown`, `reboot`, `stop`. Renvoie l'UPID de la tâche. `stop` (coupure brutale) exige `{"confirm": true}`. |
| `GET /api/connections/{id}/tasks/{node}/{upid}` | État d'une tâche (`ok` si terminée avec succès) ; `/log` pour son journal |
| `GET /api/connections/{id}/guests/{node}/{type}/{vmid}/config` | Matériel décomposé (CPU, RAM, disques, cartes réseau) et changements en attente |
| `PATCH …/config` | Modifie CPU (cœurs, sockets, type), RAM, balloon, swap (LXC), réseau (bridge, VLAN, firewall ; la MAC est conservée), ISO monté ou éjecté. Seuls des champs validés sont acceptés. |
| `POST …/guests/{node}/{type}/{vmid}/nets` · `DELETE …/nets/{netN}?confirm=true` | Ajouter une carte réseau (index libre choisi, MAC attribuée par Proxmox, IP DHCP/statique pour un LXC) / la retirer (la MAC est perdue, confirmation exigée) |
| `PATCH …/config` avec `boot` | Ordre de démarrage d'une VM (`["scsi0","ide2","net0"]`) |
| `POST …/guests/{node}/{type}/{vmid}/disks` | Ajoute un disque (VM : bus et stockage ; LXC : point de montage avec chemin validé) |
| `POST …/disks/{key}/detach` | Détache un disque : il devient « non utilisé », **données conservées** |
| `POST …/disks/unusedN/reattach` | Rattache un disque non utilisé |
| `DELETE …/disks/unusedN?confirm=true&name=<machine>` | Détruit **définitivement** un disque non utilisé ; exige le nom exact de la machine |
| `POST …/disks/{key}/move` | Déplace un disque vers un autre stockage (`confirm` exigé, ancien emplacement conservé sauf `delete_source`) |
| `POST …/guests/{node}/{type}/{vmid}/clone` | Clone une VM ou un LXC (complet, ou lié si la source est un modèle) ; nom, identifiant (libre par défaut), nœud et stockage de destination, pool |
| `DELETE …/guests/{node}/{type}/{vmid}?confirm=true&name=<machine>` | Supprime **définitivement** une machine et ses disques. Exige : machine arrêtée, nom exact, non protégée (par Proxmox ni par `KAJI_PROTECTED_VMIDS`). Options `purge`, `destroy_unreferenced`. |
| `GET …/guests/{node}/{type}/{vmid}/migrate` | Vérifications préalables de Proxmox : nœuds possibles, disques locaux, ressources bloquantes (repli sur les nœuds en ligne si indisponibles) |
| `POST …/guests/{node}/{type}/{vmid}/migrate` | Migre la machine vers un autre nœud ; une machine en marche exige `confirm` (VM : à chaud ; LXC : arrêt, migration, redémarrage) |
| `POST …/resize` | Agrandit un disque de N Go (irréversible, exige `{"confirm": true}`) |
| `GET\|POST …/guests/{node}/{type}/{vmid}/snapshots` | Lister / créer un snapshot (avec la mémoire pour une VM en marche) |
| `DELETE …/snapshots/{name}?confirm=true` | Supprimer un snapshot (confirmation exigée) |
| `POST …/snapshots/{name}/rollback` | Restaurer la machine à ce snapshot, exige `{"confirm": true}` (tout ce qui a changé depuis est perdu) |
| `GET /api/connections/{id}/nodes/{node}/bridges` | Réseaux sélectionnables pour une carte réseau : bridges locaux et VNets SDN (la liste reste utilisable si le SDN est absent ou illisible) |
| `POST /api/connections/{id}/nodes/{node}/qemu` | Crée une VM (nom, mémoire, CPU, disque, réseau, ISO, pool, type d'OS ; Windows 11 reçoit UEFI, TPM et disque EFI). Chaque champ est validé ; l'identifiant est choisi automatiquement si absent. |
| `POST /api/connections/{id}/nodes/{node}/lxc` | Crée un conteneur LXC depuis un modèle déjà présent (non privilégié par défaut). Mot de passe root et clés SSH facultatifs : **jamais journalisés**, jamais renvoyés. |
| `GET\|PATCH …/guests/{node}/qemu/{vmid}/cloudinit` | Cloud-init d'une VM : utilisateur, mot de passe (**jamais relu ni journalisé**), clés SSH (envoyées encodées en URL comme l'exige Proxmox), IP, DNS, domaine ; `clear` supprime des réglages |
| `POST\|DELETE …/cloudinit/drive` | Ajoute (bus IDE libre) ou retire le lecteur cloud-init, sans toucher aux réglages |
| `GET /api/connections/{id}/nextid` · `/pools` · `/nodes/{node}/storages?content=` | Prochain identifiant libre, pools, stockages d'un nœud acceptant un type de contenu |
| `GET /api/connections/{id}/nodes/{node}/templates` | Modèles de conteneur : déjà présents sur les stockages du nœud, et catalogue téléchargeable (avec l'architecture) |
| `GET /api/connections/{id}/nodes/{node}/isos` | Images ISO disponibles sur les stockages actifs du nœud |
| `GET /api/audit` | Journal d'audit des actions (qui, quoi, quand, résultat) |

> **Droits Proxmox (M2).** Les actions demandent plus que la lecture seule. Pour limiter les risques, donne le rôle `PVEVMAdmin` au token **uniquement sur les machines concernées** (`pveum aclmod /vms/<vmid> -user kaji@pve -role PVEVMAdmin`) et garde `PVEAuditor` sur `/`.
