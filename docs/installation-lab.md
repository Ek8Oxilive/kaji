# Installer Kaji en lab

Guide pour installer Kaji sur une machine neuve et le brancher sur un cluster Proxmox VE **de test ou de lab**. Il suffit de le suivre dans l'ordre. Durée : 30 à 45 minutes.

> **Ce que ce guide ne couvre pas : la production.** Kaji est une « V1 candidate » pour un lab interne non exposé (`docs/cadrage-prod-entreprise.md`, jalon J1). Aujourd'hui **tout le monde partage un seul jeton Proxmox** (les actions apparaissent sous le même nom dans le journal de Proxmox), il n'y a **ni SSO ni double authentification** pour se connecter à Kaji, et **aucune relecture de sécurité par un tiers** n'a été faite. N'expose jamais Kaji sur Internet.

> **Honnêteté sur ce guide.** Il a été écrit à partir du code et de l'installation du propriétaire, **mais jamais rejoué de zéro par quelqu'un d'autre** : c'est le but du ticket #428. **Si une étape ne marche pas comme écrit, ouvre un ticket** avec la commande et le message obtenu : c'est exactement ce qu'on cherche.

## 0. Ce que tu vas obtenir
Trois conteneurs Docker sur **une** machine : `backend` (FastAPI, base SQLite), `web` (nginx : interface et relais de `/api`) et, si tu le demandes, `tls` (Caddy : HTTPS). Kaji parle à l'API de ton Proxmox avec **un jeton** (pas de mot de passe stocké).

Quelques fonctions restent réservées à `root@pam` par Proxmox lui-même (moniteur QEMU, `affinity`, `hugepages`, `keyctl` / `fuse` / `mount` d'un conteneur, création et jonction de cluster) : elles resteront dans l'interface de Proxmox quelle que soit la maturité de Kaji.

## 1. Prérequis
| Quoi | Détail |
|---|---|
| Une machine pour Kaji | Linux, **Docker Engine et Docker Compose v2** (`docker compose version`), `git`, `python3` (seulement pour générer des secrets), 1 Go de RAM libre. Un conteneur LXC ou une VM sur le cluster convient ; **ne l'installe pas sur le seul nœud dont dépend ton cluster**. |
| Un cluster Proxmox VE | Joignable depuis cette machine en HTTPS sur le port **8006** (`curl -k https://<nœud>:8006/api2/json/version` répond). Développé et essayé sur Proxmox VE 8 et 9 (cluster de 2 nœuds : voir `docs/statut-fonctions.md` pour ce qui est « validé en réel »). |
| Un accès administrateur à Proxmox | Pour créer l'utilisateur et le jeton de l'étape 2 (shell d'un nœud en `root`, ou l'interface web). |
| Un navigateur | Sur un autre poste que Kaji ou le même. |

## 2. Préparer Proxmox : un utilisateur et un jeton au moindre privilège
Kaji se connecte avec **un jeton API à privilèges séparés**. Principe : **on lui donne seulement ce dont on a besoin, jamais `Administrator`**.

Sur le shell d'un nœud Proxmox, en `root` :
```bash
pveum user add kaji@pve --comment "Kaji (interface web)"
pveum user token add kaji@pve kaji --privsep 1 --comment "jeton de Kaji"
```
La seconde commande **affiche le secret du jeton une seule fois** : copie-le tout de suite dans ton gestionnaire de mots de passe. Ne le colle ni dans un chat, ni dans un fichier du dépôt, ni dans un ticket.

Avec `--privsep 1`, **les droits du jeton sont l'intersection de ceux de l'utilisateur et de ceux du jeton** : donne donc chaque rôle aux deux (`--users` et `--tokens`), sinon le jeton n'a rien.

### 2.1 Lecture seule (point de départ recommandé)
```bash
pveum acl modify / --roles PVEAuditor --users 'kaji@pve' --tokens 'kaji@pve!kaji'
```
Cela couvre les fonctions de lecture (voir le cluster, les stockages, les pools). Branche Kaji comme ça, regarde l'interface, **puis ajoute les droits par fonction** dont tu as besoin.

### 2.2 Ajouter des droits, fonction par fonction
Le tableau ci-dessous est celui de Kaji lui-même (`backend/app/accessspec.py`) ; un test vérifie que ce guide le reproduit sans écart. Pour chaque fonction que tu veux utiliser, accorde les privilèges **sur le chemin indiqué**. Exemple, pour « Démarrer, éteindre, redémarrer une machine » :
```bash
pveum role add Kaji-power -privs "VM.PowerMgmt"
pveum acl modify /vms --roles Kaji-power --users 'kaji@pve' --tokens 'kaji@pve!kaji'
```

| Identifiant | Fonction de Kaji | Droits Proxmox nécessaires (chemin : privilèges) |
|---|---|---|
| `view` | Voir le cluster, les nœuds et les machines | `/` : `Sys.Audit`, `VM.Audit` |
| `storage-view` | Voir les stockages et leur contenu | `/storage` : `Datastore.Audit` |
| `pools` | Voir les pools | `/pool` : `Pool.Audit` |
| `power` | Démarrer, éteindre, redémarrer une machine | `/vms` : `VM.PowerMgmt` |
| `create` | Créer ou supprimer une machine | `/vms` : `VM.Allocate` |
| `hardware` | Modifier le matériel d'une machine | `/vms` : `VM.Config.CPU`, `VM.Config.Memory`, `VM.Config.Disk`, `VM.Config.Network`, `VM.Config.Options` |
| `snapshot` | Créer, restaurer ou supprimer un snapshot | `/vms` : `VM.Snapshot`, `VM.Snapshot.Rollback` |
| `clone` | Cloner une machine | `/vms` : `VM.Clone` |
| `migrate` | Migrer une machine | `/vms` : `VM.Migrate` |
| `backup` | Lancer une sauvegarde | `/vms` : `VM.Backup` ; `/storage` : `Datastore.AllocateSpace` |
| `restore` | Restaurer une sauvegarde vers une nouvelle machine | `/vms` : `VM.Allocate` ; `/storage` : `Datastore.AllocateSpace` |
| `backup-jobs` | Gérer les sauvegardes planifiées | `/` : `Sys.Modify` |
| `console` | Ouvrir la console d'une machine (noVNC, terminal, SPICE) | `/vms` : `VM.Console` |
| `node-console` | Ouvrir la console (shell) d'un nœud | `/nodes` : `Sys.Console` |
| `ha-write` | Gérer la haute disponibilité (ressources, règles, migrer, relocaliser) | `/` : `Sys.Console` |
| `replication-write` | Gérer les jobs de réplication (créer, modifier, supprimer, lancer) | `/vms` : `VM.Replicate` |
| `notifications-write` | Gérer les cibles et les règles de notification, tester une cible | `/mapping/notifications` : `Mapping.Modify` |
| `notifications-read` | Voir les cibles et les règles de notification | `/mapping/notifications` : `Mapping.Audit` |
| `passthrough-write` | Ajouter ou retirer un périphérique PCI, USB ou un répertoire (par correspondance) d'une VM | `/vms` : `VM.Config.HWType` ; `/mapping/pci` : `Mapping.Use` ; `/mapping/usb` : `Mapping.Use` ; `/mapping/dir` : `Mapping.Use` |
| `mappings-write` | Gérer les correspondances de ressources PCI, USB et répertoires | `/mapping/pci` : `Mapping.Modify` ; `/mapping/usb` : `Mapping.Modify` ; `/mapping/dir` : `Mapping.Modify` |
| `mappings-read` | Voir les correspondances de ressources et le matériel PCI / USB des nœuds | `/mapping/pci` : `Mapping.Audit` ; `/mapping/usb` : `Mapping.Audit` ; `/mapping/dir` : `Mapping.Audit` ; `/nodes` : `Sys.Audit` |
| `datacenter-write` | Modifier les options, les notes et les serveurs de métriques du datacenter | `/` : `Sys.Modify` |
| `node-syslog` | Lire le journal système d'un nœud | `/nodes` : `Sys.Syslog` |
| `node-updates` | Voir et rafraîchir les mises à jour disponibles d'un nœud | `/nodes` : `Sys.Modify` |
| `node-services` | Démarrer, arrêter ou redémarrer un service d'un nœud | `/nodes` : `Sys.Modify` |
| `node-power` | Redémarrer ou éteindre un nœud | `/nodes` : `Sys.PowerMgmt` |
| `node-disks-write` | Initialiser, effacer un disque et créer un volume (LVM, LVM-thin, répertoire, ZFS) | `/nodes` : `Sys.Modify` ; `/storage` : `Datastore.Allocate` |
| `node-config` | Modifier le DNS, le fichier hosts et le fuseau horaire d'un nœud | `/nodes` : `Sys.Modify` |
| `node-certs` | Installer ou retirer un certificat personnalisé sur un nœud | `/nodes` : `Sys.Modify` |
| `node-repos` | Activer, désactiver ou ajouter un dépôt de paquets d'un nœud | `/nodes` : `Sys.Modify` |
| `acme` | Gérer les certificats ACME (comptes, domaines, commande) | `/nodes` : `Sys.Modify` ; `/` : `Sys.Modify` |
| `network` | Ajouter une carte réseau sur un bridge ou un VNet | `/sdn/zones` : `SDN.Use` |

Précisions :
- La page **« Accès »** de Kaji (une fois connecté) fait cette comparaison pour toi : pour chaque fonction, `ok`, `missing` ou `unknown`, et **les commandes `pveum` à copier** pour ce qui manque. Kaji n'exécute jamais ces commandes lui-même. Cette page ne couvre que les fonctions du tableau : **le pare-feu, le SDN, Ceph, les utilisateurs et les realms** demandent d'autres droits (voir les fichiers `docs/api/` de chaque fonction). Dans le doute, essaie : un droit manquant donne « Droits insuffisants pour cette opération », sans rien casser.
- Une entrée posée sur un chemin précis **remplace** celle héritée du parent pour le même utilisateur, elle ne s'y ajoute pas.
- **Ne donne jamais `Administrator` ni `Permissions.Modify`** au jeton de Kaji dans un lab partagé : qui compromet Kaji compromet alors l'administration de Proxmox (`docs/securite.md`, ligne « Moyenne »).
- Les opérations de gestion des droits (utilisateurs, jetons, ACL, realms, double authentification) passent par une **session administrateur ponctuelle** ouverte depuis Kaji avec un jeton d'administration collé pour l'occasion, ou le mot de passe d'un compte Proxmox (jamais conservé). L'option `KAJI_ADMIN_USE_KAJI_TOKEN=true`, qui ouvre cette session avec le jeton de Kaji, **ne doit rester à `false`** (valeur par défaut) tant que ce jeton n'est pas administrateur et que tu ne l'as pas décidé.

## 3. Installer Kaji
Sur la machine de Kaji :
```bash
git clone https://github.com/Ek8Oxilive/kaji.git && cd kaji
# Pour une version figée, choisis une étiquette plutôt que main : git tag -l, puis git checkout v1.0.0-rc1
# (les images de base Docker sont épinglées par empreinte : docs/images-et-versions.md)
cp .env.example .env
chmod 600 .env
```

### 3.1 Régler le fichier `.env`
Génère les deux secrets (garde-les dans ton gestionnaire de mots de passe) :
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # → KAJI_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # → KAJI_SETUP_TOKEN
```
Édite `.env` (une valeur par ligne, **sans guillemets**) :

| Variable | À mettre | Pourquoi |
|---|---|---|
| `KAJI_SECRET_KEY` | **obligatoire** : le premier secret (au moins 32 caractères) | Signe les sessions **et chiffre les jetons Proxmox** et les webhooks. Kaji refuse de démarrer avec la valeur d'exemple `changeme`. **La perdre = ressaisir les connexions Proxmox** ; la changer invalide sessions et jetons enregistrés. |
| `KAJI_SETUP_TOKEN` | **recommandé** : le second secret | Sans lui, le premier qui atteint la page crée le compte administrateur. Il ne sert qu'une fois (création du premier compte). |
| `KAJI_COOKIE_SECURE` | `true` (défaut) | Le cookie de session n'est accepté qu'en **HTTPS** ou sur `localhost`. |
| `KAJI_PROTECTED_VMIDS` | par exemple `100,101` | Machines que Kaji refuse de supprimer et sur lesquelles il refuse toute action planifiée. Mets celles qui comptent. |
| `KAJI_ADMIN_USE_KAJI_TOKEN` | **laisse commenté** (donc `false`) | Voir l'étape 2.2. |
| `KAJI_SCHEDULER` | `true` (défaut) | Planificateur d'actions et alertes. **Une seule instance de Kaji** doit tourner, sinon actions et alertes sont doublées. |
| `KAJI_TRUST_PROXY` | laisse `false` | Le `docker-compose.yml` le règle déjà pour le conteneur. |
| `KAJI_AUDIT_RETENTION_DAYS` | `365` (défaut) | Conservation du journal d'audit de Kaji, en jours (`0` = indéfiniment). |
| `KAJI_BIND` | `127.0.0.1` (défaut) | Interface d'écoute de nginx. `0.0.0.0` ouvre tout le réseau : seulement derrière le HTTPS de l'étape 5. |
| `KAJI_PORT` | `8080` (défaut) | Port de nginx. |

Les variables `KAJI_TLS_*` et `KAJI_HTTP_PORT` ne servent qu'à l'étape 5.

### 3.2 Démarrer
```bash
docker compose up -d --build
docker compose ps                                # backend et web : « healthy » / « running »
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/health     # 200
```
Le premier démarrage construit les images (quelques minutes). Si `backend` redémarre en boucle : `docker compose logs backend` (cause la plus fréquente : `KAJI_SECRET_KEY` vide ou d'exemple).

### 3.3 Créer le compte administrateur
Ouvre **http://127.0.0.1:8080** depuis la machine de Kaji (en HTTP, seul `localhost` est accepté tant que le HTTPS n'est pas en place ; depuis un autre poste, fais d'abord l'étape 5 ou un tunnel `ssh -L 8080:127.0.0.1:8080 <machine>`). L'écran de **première configuration** demande un nom, un mot de passe (**12 caractères au moins**) et le jeton `KAJI_SETUP_TOKEN`. Trop d'essais ratés (5 par 5 minutes) bloquent la page un moment.

## 4. Connecter Kaji à Proxmox
Dans Kaji, page **« Connexions »** → ajouter :
| Champ | Valeur |
|---|---|
| Nom | libre |
| Hôte | adresse ou nom d'un nœud (sans `https://` ni chemin) |
| Port | `8006` |
| Utilisateur | `kaji@pve` |
| ID du token | `kaji` (la partie après le `!`) |
| Secret du token | celui de l'étape 2 (Kaji ne le renvoie jamais) |
| Vérifier le certificat SSL | laisse décoché (certificat auto-signé de Proxmox), puis **épingle** le certificat (ci-dessous) |

**Épingler le certificat de Proxmox** (recommandé) : le certificat par défaut de Proxmox n'est signé par aucune autorité publique. Sur la connexion, « Épingler le certificat… » affiche l'empreinte SHA-256 vue par Kaji. **Compare-la** à celle du nœud (`openssl x509 -fingerprint -sha256 -noout -in /etc/pve/local/pve-ssl.pem` sur le nœud), coche la case et confirme. Kaji n'accepte alors **que ce certificat** (voir `docs/api/connexions-tls.md`). Clique ensuite « Tester » (ou « Tester la connexion » dans le formulaire) : la connexion doit répondre.

Ouvre la page **« Accès »** : elle liste les droits du jeton par fonction (étape 2.2). Un `missing` n'est pas une erreur : c'est une fonction que tu n'as pas (encore) autorisée.

## 5. HTTPS (nécessaire dès qu'on utilise Kaji depuis un autre poste)
Option fournie : Caddy devant Kaji, avec sa propre autorité de certification interne.
```bash
# Dans .env :
#   KAJI_COOKIE_SECURE=true
#   KAJI_TLS_SITE=192.168.1.10      ← l'adresse par laquelle tu ouvres Kaji, SANS port
#   KAJI_TLS_NAME=kaji.home         ← facultatif : un nom DNS local en plus ; doit différer de KAJI_TLS_SITE
#   KAJI_BIND=127.0.0.1
docker compose down                  # le réseau Docker change de sous-réseau : il doit être recréé
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.tls.yml cp tls:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```
Réglages facultatifs de Caddy : `KAJI_TLS_PORT` (443 par défaut), `KAJI_HTTP_PORT` (80, simple redirection vers HTTPS) et `KAJI_TLS_BIND` (`0.0.0.0` par défaut : Caddy écoute sur toutes les interfaces ; mets l'adresse de ta carte réseau interne pour le limiter).

Installe `caddy-root.crt` comme **autorité de confiance** dans ton navigateur ou ton système, puis ouvre **`https://<adresse>`** (port 443 ; le port 80 renvoie vers HTTPS). **Même commande (les deux fichiers `-f`) à chaque redémarrage ou mise à jour**, sinon Caddy s'arrête.

Garde l'ancien accès local tant que le HTTPS n'est pas vérifié. Sauvegarde aussi le volume `caddy-data` (clé de l'autorité interne : la perdre te fait réinstaller le certificat dans tous les navigateurs). Avec Tailscale, `tailscale serve` remplace Caddy.

**Symptôme classique d'un cookie refusé** : en HTTP sur le réseau, le formulaire de connexion se revalide puis revient à l'écran de connexion, **sans message** (les journaux montrent `POST /api/auth/login 200`). C'est le cookie `Secure` : passe en HTTPS. En dernier recours, sur un réseau de confiance seulement : `KAJI_COOKIE_SECURE=false`, puis `docker compose up -d --force-recreate backend` (un simple `restart` ne relit pas `.env`).

## 6. Vérifier que tout marche
- `https://<adresse>` s'ouvre, tu te connectes, le tableau de bord liste les nœuds et les machines.
- Page « Connexions » : « Tester » répond, le certificat est épinglé.
- Page « Accès » : les fonctions que tu veux utiliser sont à `ok`.
- Essaie une écriture **réversible** sur une machine jetable : démarrer puis arrêter une VM de test (droit `VM.PowerMgmt`).
- Journal d'audit de Kaji : pas de page dédiée ; connecté, ouvre `https://<adresse>/api/audit` dans le navigateur. L'action y figure, **sans aucun secret**.

## 7. Sauvegarde : la base ET la clé, ensemble
La base (volume Docker `kaji-data`) contient les **jetons Proxmox et les adresses de webhook chiffrés** avec `KAJI_SECRET_KEY`, les comptes de Kaji et leurs rôles, les actions planifiées, les règles d'alerte et l'audit. **L'une sans l'autre est inutilisable.** La clé est dans `.env`, pas dans la base : sauvegarde les deux, **séparément et en lieu sûr** (gestionnaire de mots de passe pour `.env`).
```bash
tools/backup.sh /chemin/sûr/sauvegardes      # base cohérente, Kaji reste en marche ; la copie est relue avec la clé (jetons et webhooks déchiffrés)
cp .env /chemin/sûr/kaji.env                 # la clé, à part ; note aussi l'empreinte de la clé affichée par le script
```
**Restauration**, sur une machine installée comme à l'étape 3 : remets le **même** `.env`, puis :
```bash
tools/restore.sh /chemin/sûr/sauvegardes/kaji-AAAAMMJJ-HHMMSS.db      # demande de taper RESTAURER, refuse une sauvegarde illisible avec cette clé
```
Le script contrôle ensuite la base (`verify`) ; termine par un essai à la main : connexion à Kaji, page « Connexions » → « Tester », webhooks d'alerte présents. Détails, contrôle d'une sauvegarde et méthode de secours (copie du volume) : `docs/deploiement.md`.

> **Pas encore éprouvé avec Docker de bout en bout.** La logique (sauvegarde cohérente, refus avec la mauvaise clé, aller-retour complet, enchaînement des scripts) est testée automatiquement sur de vraies bases SQLite et avec un faux `docker` ; **le volume Docker réel n'a jamais servi à une restauration** : c'est la fin du ticket #429, à faire sur une machine avec Docker. Si une étape échoue chez toi, ouvre un ticket avec le message obtenu.

## 8. Mettre à jour
```bash
git pull                     # ou : git fetch --tags && git checkout <nouvelle étiquette>
docker compose up -d --build  # ajoute -f docker-compose.tls.yml si tu as activé le HTTPS (étape 5)
docker compose exec backend python -m app.migrations status
```
Les migrations de schéma s'exécutent au démarrage, **après une copie de la base** dans le volume (`kaji.db.bak-vN-AAAAMMJJ-HHMMSS`, les 5 dernières sont gardées). Si Kaji refuse de démarrer sur une base « plus récente que le code », c'est que tu as redescendu de version : restaure une sauvegarde d'avant la mise à niveau. **Fais une sauvegarde (étape 7) avant de mettre à jour.**

## 9. Dépannage rapide
| Symptôme | Cause probable |
|---|---|
| `backend` redémarre en boucle | `KAJI_SECRET_KEY` vide ou valant `changeme` : `docker compose logs backend` |
| Le formulaire de connexion revient sans message | cookie `Secure` refusé en HTTP : étape 5 |
| « Droits insuffisants pour cette opération » | droit absent du jeton : page « Accès », étape 2.2 (et le rôle doit aller à l'utilisateur **et** au jeton) |
| « Tester » échoue sur une connexion | adresse ou port injoignables depuis la machine de Kaji, certificat épinglé qui a changé (réépingler), ou mauvais secret de jeton |
| `ERR_SSL_PROTOCOL_ERROR` en ouvrant par un nom | le nom doit être dans `KAJI_TLS_NAME` (ou être l'adresse de `KAJI_TLS_SITE`) |
| Console web refusée | ouverte par un autre nom que celui du certificat, ou rôle autre qu'administrateur de Kaji |
| Mot de passe perdu | sur le serveur : `docker compose exec backend python -m app.admin_cli reset-password --user <nom>` (les sessions du compte sont révoquées) |
| Actions ou alertes en double | deux instances de Kaji tournent : n'en garde qu'une (ou `KAJI_SCHEDULER=false` sur l'autre) |

## 10. Pour aller plus loin
- `docs/deploiement.md` : détails Docker, limiteur de connexions derrière un proxy, ce que fait (et ne fait pas) la configuration.
- `docs/images-et-versions.md` : images de base épinglées, mise à jour des empreintes, nommage et publication des versions.
- `docs/securite.md` : revue de sécurité, ce qui est vérifié, ce qui reste à décider.
- `docs/statut-fonctions.md` : quelles fonctions sont « validées en réel » et lesquelles sont « expérimentales ».
- `docs/cadrage-prod-entreprise.md` : ce qui sépare ce lab d'une production en entreprise.
- **Signaler un problème** : un ticket sur le dépôt. **Une faille de sécurité** : pas de ticket public, suis `SECURITY.md` (signalement privé). L'historique des versions est dans `CHANGELOG.md`.
