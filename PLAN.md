# Kaji : plan de développement (v2)

## Objectif
Alternative moderne à l'UI Proxmox : supervision, création/gestion des VM et LXC, et paramétrage complet du cluster (stockage, réseau, sauvegardes, utilisateurs/ACL, firewall, HA/réplication). Usage perso homelab.

**But précisé : ne perdre aucune fonctionnalité de l'interface de Proxmox VE.** Le suivi fonction par fonction est dans `docs/parite-proxmox.md`.

Stack : FastAPI (backend, `httpx` async) + React/Vite/Tailwind (frontend) + Docker Compose.

## Principes transverses (valables pour toutes les phases)
- **Auth obligatoire** sur le dashboard (login + session/JWT), HTTPS via reverse proxy. Le token Proxmox a des droits larges : le dashboard est la cible.
- **Secrets** : seul `KAJI_SECRET_KEY` est dans `.env` (hors git, `.env.example` versionné). Les connexions Proxmox (hôte, utilisateur, token) sont saisies dans l'UI et stockées **chiffrées** (Fernet) en SQLite.
- **Journal d'audit** de toutes les actions d'écriture (qui, quoi, quand, résultat).
- **Garde-fous** : confirmation sur toute action destructrice ; sur réseau/firewall, mode « appliquer avec rollback » (annulation auto si la connexion est perdue) ou au minimum aperçu du diff avant application.
- **Environnement de test** : Proxmox imbriqué (VM de test) ou mock d'API. Rien de risqué n'est testé sur la prod.
- **Pattern d'écriture** : toute action Proxmox asynchrone renvoie un UPID, suivi via un mécanisme de tâches commun (écrit une seule fois en M2, réutilisé partout).

## Évolution possible
- Second mode de connexion : login Proxmox direct (ticket, sans stocker de token), pour des permissions par utilisateur.

## Jalons

### M0 : Cadrage et socle
- [x] Repo git (`/backend`, `/frontend`), `.gitignore`, `.env.example`
- [x] Environnement de test : cluster Proxmox perso réel, joint via Tailscale, avec des droits limités machine par machine (pas d'environnement jetable)
- [x] Token API dédié (saisi dans l'UI), droits documentés

### M1 : Backend lecture + auth
- [x] FastAPI, module client Proxmox (httpx async, SSL self-signed), instancié à la demande par connexion
- [x] Base SQLite + chiffrement des tokens (clé dérivée de `KAJI_SECRET_KEY`)
- [x] Premier lancement : création du compte admin du dashboard (hash en base, plus de variable `.env`)
- [x] Gestion des connexions : ajouter / tester / modifier / supprimer un cluster (hôte, utilisateur, token), multi-cluster
- [x] Auth du dashboard (login + session/JWT)
- [x] Routes : cluster/statut, nœuds, ressources VM/LXC unifiées
- Fin : après création du compte admin et ajout d'une connexion, `curl` authentifié renvoie la liste des VM/LXC

### M2 : Actions et tâches
- [x] Start / stop / shutdown / reboot
- [x] Suivi UPID (statut, log), journal d'audit
- Fin : démarrer/arrêter une VM de test par l'API et suivre la tâche

### M3 : Frontend de base
- [x] Layout, sidebar, login
- [x] **Thèmes commutables** : « Sombre moderne » et « Glass » (panneaux translucides), choix mémorisé dans le navigateur ; architecture à variables CSS pour en ajouter d'autres (ex. clair minimal) sans toucher aux composants
- [x] Écran de première configuration et écran « Connexions » (sélecteur de cluster)
- [x] Vue cartes VM/LXC (statut, CPU/RAM), actions rapides, toasts
- [x] **Temps réel** : un seul interrogateur Proxmox par connexion côté backend, diffusé aux navigateurs en SSE (repli en polling si besoin). Moins de charge sur Proxmox, mises à jour plus vives.
- [x] **Données côté navigateur** : cache et rafraîchissement avec TanStack Query ; une requête agrégée (nœuds + VM/LXC + stockages) au lieu de nombreux petits appels
- [x] **Fluidité perçue** : squelettes de chargement, mises à jour optimistes (l'état change au clic, retour arrière si Proxmox refuse), transitions et jauges animées
- [x] **Navigation rapide** : palette de commandes (Ctrl+K) pour trouver une VM, un nœud ou une action
- Contrainte connue : Proxmox rafraîchit ses statistiques environ toutes les 10 s ; la fluidité vient des transitions et des actions instantanées, pas d'une résolution à la seconde
- Fin : dashboard en direct sur l'environnement de test, sans rechargement de page, avec un retour visuel immédiat à chaque action

### M4 : Cycle de vie des VM/LXC
- [ ] Wizard de création VM (nom/OS, hardware, réseau, stockage, ISO) — **API et assistant livrés** (4 étapes) ; création réelle à tester dans un pool dédié (bac à sable) pour ne jamais créer hors de celui-ci
- [x] Création LXC depuis un modèle déjà présent (non privilégié par défaut ; téléchargement de modèle non géré)
- [x] Clonage (complet ou lié depuis un modèle, vers un autre nœud ou stockage)
- [x] Cloud-init (VM) : utilisateur, mot de passe, clés SSH, IP, DNS, lecteur ; `cicustom` (snippets) volontairement non géré
- [ ] **Édition du matériel (VM et LXC)**, comme dans l'UI Proxmox : panneau « Matériel » par machine, changements en attente signalés (redémarrage requis) — **niveau A livré** (avec listes de bridges/VNets et d'ISO), niveau B à faire
  - Niveau A (faible risque) : CPU (cœurs, sockets, type), RAM, agrandir un disque (jamais réduire), réseau (bridge, VLAN, firewall, MAC conservée), monter/éjecter un ISO
  - Niveau B (risque moyen à élevé) : ajouter / supprimer un disque ou une carte réseau, déplacer un disque vers un autre stockage, ordre de boot — **B1 et B2 livrés** (cartes réseau, ordre de boot, ajout / détachement / rattachement / suppression / déplacement de disques) ; déplacement de disque et ajout de carte non validés en réel (un seul stockage de disques ; droit SDN.Use manquant)
  - Niveau C (reporté) : passthrough PCI/USB, TPM, arguments QEMU
  - Garde-fous : liste blanche de paramètres validés côté serveur (aucune clé libre transmise à Proxmox), suppression d'un disque confirmée en retapant le nom de la machine, agrandissement de disque confirmé (irréversible), audit de chaque changement
  - Tests réels limités à des modifications réversibles sur les machines désignées ; les opérations irréversibles (agrandir/supprimer un disque) ne sont testées qu'avec un faux Proxmox
- [x] **Pages de détail** : un clic sur une machine ou un nœud ouvre une page (adresse propre, bouton retour) ; la page Machine remplace le tiroir « Matériel » et réunit matériel, snapshots, cloud-init et sauvegardes — routage, page Machine et page Nœud livrés ; graphiques d'historique non faits
- [x] Snapshots : créer, lister, supprimer, restaurer (restauration confirmée en retapant le nom de la machine)
- [x] Suppression de machine : arrêtée, nom retapé, disques listés, protégeable par `KAJI_PROTECTED_VMIDS`
- [x] Migration entre nœuds (vérifications préalables, à froid, à chaud pour une VM, redémarrage pour un LXC)
- **Jalon MVP : fin de M4**

### M5 : Stockage et sauvegardes
- [ ] Stockage : usage, ajout NFS/LVM/ZFS/dir/CIFS/iSCSI/CephFS/RBD/PBS, contenu (ISO, templates), **téléverser et télécharger depuis une URL** (ISO, modèles)
- [ ] Sauvegardes : jobs vzdump, planification, rétention, lancement manuel, restauration

### M6 : Utilisateurs et ACL
- [x] **Accès en lecture seule** : « droits de Kaji » (chaque fonction a-t-elle son droit ?), utilisateurs, rôles, ACL visibles, realms — API et page « Accès » livrées ; statut « droit manquant » vu seulement sur faux Proxmox
- [x] **Commandes de correction** (lot A1) : pour un droit manquant, Kaji affiche les commandes `pveum` à copier ; il n'exécute rien
- [ ] Profil de droits recommandé (lot A2) : attend d'avoir éprouvé chaque privilège en bac à sable
- [ ] Écriture des droits : **cadrée** dans `docs/m6-ecriture.md` (rien n'est développé ; décision du propriétaire attendue : commandes à copier d'abord, écriture bornée seulement si un besoin réel apparaît)
- [ ] Tokens API (création, révocation) : voir le cadrage ci-dessus

### M7 : Réseau et firewall (risque élevé)
- [ ] Interfaces, bridges, bonds, VLAN : modifications en attente, aperçu du diff, application avec rollback
- [ ] Firewall : règles cluster / nœud / VM, security groups, IPSets, activation progressive

### M8 : HA et réplication
- [ ] Ressources HA, groupes, règles
- [ ] Jobs de réplication (ZFS)

### M9 : Console et déploiement
- [ ] Console web (noVNC, xterm.js, shell du nœud, via vncproxy / termproxy + proxy WebSocket)
- [ ] Dockerfiles (backend, frontend/Nginx), `docker-compose.yml`, doc de déploiement

### M10 : Gestion du cluster (banc d'essai imbriqué obligatoire)
- [ ] Création, jonction de nœuds, corosync. Nécessaire pour la parité avec Proxmox ; à tester uniquement sur le banc d'essai imbriqué (une erreur peut casser le quorum).

### M11 : Système des nœuds
- [ ] Mises à jour (apt) et dépôts, firmware, certificats (personnalisés, ACME), DNS, hôtes, fuseau horaire, heure
- [ ] Journal système, services, redémarrer / éteindre un nœud
- [ ] Disques : liste, SMART, initialiser GPT, effacer, LVM, LVM-thin, répertoire, ZFS

### M12 : Ceph (banc d'essai imbriqué obligatoire)
- [ ] État, configuration, moniteurs, gestionnaires, OSD, pools, CephFS, journaux

### M13 : Supervision
- [ ] Graphiques d'historique (CPU, RAM, réseau, disque) pour nœuds et machines
- [ ] Journal des tâches (cluster, nœud, machine) et barre de tâches
- [ ] Étiquettes (tags), notes, vues par dossier / pool / stockage
- [ ] Notifications (cibles, règles), serveurs de métriques (InfluxDB, Graphite)

### M14 : Options avancées des machines et conteneurs
- [ ] Matériel avancé : passthrough PCI et USB, correspondances de ressources, TPM, disque EFI, port série, audio, hotplug
- [ ] Options (démarrage automatique, ordre de démarrage, QEMU Agent…), fonctionnalités LXC (nesting, FUSE, keyctl)
- [ ] Reset, suspendre, hiberner, convertir en modèle, migration distante, moniteur QEMU
- [ ] Cloud-init avancé (snippets), téléchargement de modèles LXC officiels

### M15 : Options du datacenter et divers
- [ ] Options du datacenter, notes, actions groupées, Wake-on-LAN, langues

## Risques principaux
| Risque | Parade |
|---|---|
| Dashboard compromis = cluster compromis | Auth, HTTPS, réseau local/VPN uniquement, audit |
| Fuite de la base ou de `KAJI_SECRET_KEY` = fuite des tokens | Chiffrement des tokens, permissions strictes sur la base, clé séparée de la base, jamais commitée |
| Config réseau/firewall coupe l'accès | Rollback automatique, tests sur environnement imbriqué |
| Périmètre énorme | Livraison par jalon, MVP = M4, un bloc de config à la fois |
| Console web complexe | Isolée en M9, proxy WebSocket dédié |
| Schémas d'API Proxmox variables selon version | Fixer la version cible, tests contre l'environnement de test |
