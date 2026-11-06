# PUD : Proxmox Unified Dashboard (plan v2)

## Objectif
Alternative moderne à l'UI Proxmox : supervision, création/gestion des VM et LXC, et paramétrage complet du cluster (stockage, réseau, sauvegardes, utilisateurs/ACL, firewall, HA/réplication). Usage perso homelab.

Stack : FastAPI (backend, `httpx` async) + React/Vite/Tailwind (frontend) + Docker Compose.

## Principes transverses (valables pour toutes les phases)
- **Auth obligatoire** sur le dashboard (login + session/JWT), HTTPS via reverse proxy. Le token Proxmox a des droits larges : le dashboard est la cible.
- **Secrets** : seul `PUD_SECRET_KEY` est dans `.env` (hors git, `.env.example` versionné). Les connexions Proxmox (hôte, utilisateur, token) sont saisies dans l'UI et stockées **chiffrées** (Fernet) en SQLite.
- **Journal d'audit** de toutes les actions d'écriture (qui, quoi, quand, résultat).
- **Garde-fous** : confirmation sur toute action destructrice ; sur réseau/firewall, mode « appliquer avec rollback » (annulation auto si la connexion est perdue) ou au minimum aperçu du diff avant application.
- **Environnement de test** : Proxmox imbriqué (VM de test) ou mock d'API. Rien de risqué n'est testé sur la prod.
- **Pattern d'écriture** : toute action Proxmox asynchrone renvoie un UPID, suivi via un mécanisme de tâches commun (écrit une seule fois en M2, réutilisé partout).

## Évolution possible
- Second mode de connexion : login Proxmox direct (ticket, sans stocker de token), pour des permissions par utilisateur.

## Jalons

### M0 : Cadrage et socle
- [x] Repo git (`/backend`, `/frontend`), `.gitignore`, `.env.example`
- [ ] Environnement de test Proxmox (imbriqué ou mock)
- [ ] Token API dédié (saisi dans l'UI), droits documentés

### M1 : Backend lecture + auth
- [ ] FastAPI, module client Proxmox (httpx async, SSL self-signed), instancié à la demande par connexion
- [ ] Base SQLite + chiffrement des tokens (clé dérivée de `PUD_SECRET_KEY`)
- [ ] Premier lancement : création du compte admin du dashboard (hash en base, plus de variable `.env`)
- [ ] Gestion des connexions : ajouter / tester / modifier / supprimer un cluster (hôte, utilisateur, token), multi-cluster
- [ ] Auth du dashboard (login + session/JWT)
- [ ] Routes : cluster/statut, nœuds, ressources VM/LXC unifiées
- Fin : après création du compte admin et ajout d'une connexion, `curl` authentifié renvoie la liste des VM/LXC

### M2 : Actions et tâches
- [ ] Start / stop / shutdown / reboot
- [ ] Suivi UPID (statut, log), journal d'audit
- Fin : démarrer/arrêter une VM de test par l'API et suivre la tâche

### M3 : Frontend de base
- [ ] Layout, sidebar, mode sombre, login
- [ ] Écran de première configuration et écran « Connexions » (sélecteur de cluster)
- [ ] Vue cartes VM/LXC (statut, CPU/RAM), actions rapides, toasts
- [ ] Polling (WebSocket/SSE plus tard si nécessaire)
- Fin : dashboard en direct sur l'environnement de test

### M4 : Cycle de vie des VM/LXC
- [ ] Wizard de création VM (nom/OS, hardware, réseau, stockage, ISO)
- [ ] Création LXC depuis template
- [ ] Clonage depuis template, cloud-init
- [ ] Édition de config, resize disque, snapshots, suppression
- [ ] Migration entre nœuds
- **Jalon MVP : fin de M4**

### M5 : Stockage et sauvegardes
- [ ] Stockage : usage, ajout NFS/LVM/ZFS/dir, contenu (ISO, templates), upload ISO
- [ ] Sauvegardes : jobs vzdump, planification, rétention, lancement manuel, restauration

### M6 : Utilisateurs et ACL
- [ ] Users, groupes, rôles, permissions par chemin, realms
- [ ] Tokens API (création, révocation)

### M7 : Réseau et firewall (risque élevé)
- [ ] Interfaces, bridges, bonds, VLAN : modifications en attente, aperçu du diff, application avec rollback
- [ ] Firewall : règles cluster / nœud / VM, security groups, IPSets, activation progressive

### M8 : HA et réplication
- [ ] Ressources HA, groupes, règles
- [ ] Jobs de réplication (ZFS)

### M9 : Console et déploiement
- [ ] Console web (noVNC / xterm.js via vncproxy + proxy WebSocket)
- [ ] Dockerfiles (backend, frontend/Nginx), `docker-compose.yml`, doc de déploiement

### M10 (optionnel) : Gestion du cluster
- [ ] Création, jonction de nœuds, corosync. À faire seulement si le besoin se confirme ; l'UI Proxmox native reste plus sûre pour cela.

## Risques principaux
| Risque | Parade |
|---|---|
| Dashboard compromis = cluster compromis | Auth, HTTPS, réseau local/VPN uniquement, audit |
| Fuite de la base ou de `PUD_SECRET_KEY` = fuite des tokens | Chiffrement des tokens, permissions strictes sur la base, clé séparée de la base, jamais commitée |
| Config réseau/firewall coupe l'accès | Rollback automatique, tests sur environnement imbriqué |
| Périmètre énorme | Livraison par jalon, MVP = M4, un bloc de config à la fois |
| Console web complexe | Isolée en M9, proxy WebSocket dédié |
| Schémas d'API Proxmox variables selon version | Fixer la version cible, tests contre l'environnement de test |
