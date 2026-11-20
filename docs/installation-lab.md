# Installer Kaji en lab

Guide pour installer Kaji sur une machine neuve et le brancher sur un cluster Proxmox VE **de test ou de lab**. Il suffit de le suivre dans l'ordre. Durée : 30 à 45 minutes.

> **Ce que ce guide ne couvre pas : la production.** Kaji est une « V1 candidate » pour un lab interne non exposé (`docs/cadrage-prod-entreprise.md`, jalon J1). Aujourd'hui **tout le monde partage un seul jeton Proxmox** (les actions apparaissent sous le même nom dans le journal de Proxmox), il n'y a **ni SSO ni double authentification** pour se connecter à Kaji, et **aucune relecture de sécurité par un tiers** n'a été faite. N'expose jamais Kaji sur Internet.

> **Honnêteté sur ce guide.** Il a été écrit à partir du code et de l'installation du propriétaire, **mais jamais rejoué de zéro par quelqu'un d'autre** : c'est le but du ticket #428. **Si une étape ne marche pas comme écrit, ouvre un ticket** avec la commande et le message obtenu : c'est exactement ce qu'on cherche.

## Option express : un script fait les étapes 3 à 5 pour toi
Sur la machine de Kaji (Debian ou Ubuntu : Docker est installé au besoin ; ailleurs, Docker doit déjà être là). **Télécharge le script, relis-le, puis lance-le** (ne l'exécute pas à l'aveugle) :
```bash
curl -fsSL https://raw.githubusercontent.com/Ek8Oxilive/kaji/main/install.sh -o install.sh
less install.sh        # relis-le (q pour quitter)
sh install.sh
```
Il te demande **une seule chose** : l'adresse par laquelle tu ouvriras Kaji (réponds `local` pour un accès depuis cette machine seulement). Puis il vérifie ou installe Docker, récupère Kaji dans `~/kaji`, crée `.env` avec des secrets au hasard (droits 600), active HTTPS si tu as donné une adresse, construit et démarre Kaji, attend qu'il réponde, copie le certificat de Caddy, et **affiche l'adresse et le jeton de première configuration**. Relancé plus tard, il **met Kaji à jour** sans toucher à `.env` ni aux données. Options : `sh install.sh --help`.

Il reste ensuite à créer l'utilisateur et le jeton dans Proxmox (§ 2) et à brancher la connexion (§ 4).

*Essayé en réel le 2026-11-20 (Docker 29 sur Arch Linux) : installation locale, relance (`.env` identique), installation HTTPS avec récupération du certificat et réponse en HTTPS avec ce certificat. **Pas essayé** : l'installation automatique de Docker sur Debian / Ubuntu (écrite d'après la documentation officielle), une machine autre que celle du développement.*

## Démarrage rapide : les 7 étapes en une page
Si tu n'as jamais installé ce genre d'outil, **suis ces 7 étapes dans l'ordre** ; chacune renvoie à la section qui la détaille. Tu n'as besoin de **rien d'autre** pour un premier essai.
1. **Une machine pour Kaji** : une VM Debian 12 sur ton Proxmox (§ 1.1), ou n'importe quel Linux.
2. **Docker** sur cette machine (§ 1.2) : trois commandes à copier.
3. **Un utilisateur et un jeton dans Proxmox**, en lecture seule (§ 2) : trois commandes ; **note le secret du jeton**.
4. **Récupérer Kaji et régler `.env`** (§ 3 et 3.1) : tu ne modifies que **trois lignes** (`KAJI_SECRET_KEY`, `KAJI_SETUP_TOKEN`, éventuellement `KAJI_PROTECTED_VMIDS`). **Ne touche pas aux autres** : elles sont facultatives.
5. **Démarrer** (§ 3.2) : `docker compose up -d --build`, puis ouvrir la page et créer le compte administrateur (§ 3.3).
6. **Brancher Proxmox** (§ 4) : page « Connexions » de Kaji.
7. **HTTPS** (§ 5), seulement si tu veux ouvrir Kaji depuis un autre poste que la machine de Kaji.

Pour un **premier essai sans HTTPS**, depuis ton poste : `ssh -L 8080:127.0.0.1:8080 <utilisateur>@<adresse de la machine de Kaji>` puis ouvre `http://127.0.0.1:8080` dans ton navigateur (§ 3.3).

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

### 1.1 Créer la machine de Kaji (si tu n'en as pas déjà une)
Le plus simple : **une VM Debian 12** sur ton Proxmox. Préfère une VM à un conteneur LXC : Docker dans un LXC demande des options spéciales (`nesting`, `keyctl`) et casse plus facilement.
1. Télécharge l'ISO « netinst » de Debian 12 (`debian.org`) et envoie-la dans un stockage de Proxmox (Stockage → ISO Images → Upload).
2. « Create VM » : 2 vCPU, **2 Go de RAM**, disque de **20 Go**, réseau `vmbr0` (le même que ton cluster).
3. Démarre la VM, ouvre sa console et installe Debian : choisis « SSH server » et « standard system utilities », laisse le reste par défaut. Retiens le nom d'utilisateur et le mot de passe que tu crées.
4. Au premier démarrage, connecte-toi et note l'adresse IP : `ip -4 addr` (cherche une ligne `inet 192.168.x.y`).
5. À partir de là, **tu peux travailler depuis ton poste** : `ssh <utilisateur>@<adresse IP>`. Toutes les commandes de ce guide se tapent dans ce terminal, **sur la machine de Kaji**, sauf celles de l'étape 2 (shell du nœud Proxmox).

Note : `sudo` n'est pas toujours installé sur Debian. S'il manque : `su -` (mot de passe `root`), puis `apt-get install -y sudo` et `usermod -aG sudo <utilisateur>`, déconnecte-toi et reconnecte-toi.

### 1.2 Installer Docker et Docker Compose (Debian 12 / Ubuntu)
Docker fait tourner Kaji dans des « conteneurs » : des boîtes isolées, sans rien installer d'autre sur la machine. **Docker Compose** lit le fichier `docker-compose.yml` du dépôt et lance les trois boîtes d'un coup. On installe la version officielle, depuis le dépôt de Docker (celle de Debian est trop ancienne).
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3
sudo install -m 0755 -d /etc/apt/keyrings
# Debian. Sous Ubuntu, remplace « debian » par « ubuntu » dans les DEUX lignes qui suivent.
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```
Vérifie que ça marche :
```bash
sudo docker run --rm hello-world       # affiche « Hello from Docker! »
docker compose version                 # affiche « Docker Compose version v2.… »
```
Pour ne pas taper `sudo` devant chaque commande `docker` : `sudo usermod -aG docker $USER`, puis **déconnecte-toi et reconnecte-toi** (ou `newgrp docker`). Attention : faire partie du groupe `docker` revient à être `root` sur la machine ; fais-le seulement sur la machine dédiée à Kaji. Sans cela, ajoute `sudo` devant chaque `docker …` du guide.

Autre distribution : suis la page officielle `docs.docker.com/engine/install/` pour la tienne (Arch : `sudo pacman -S docker docker-compose`, puis `sudo systemctl enable --now docker`).

### 1.3 Se repérer dans le terminal
- **Où taper** : chaque bloc de commandes se copie-colle dans le terminal SSH, une ligne à la fois ou le bloc entier.
- **Éditer le fichier `.env`** : `nano .env`. Déplace-toi avec les flèches, **Ctrl+O** puis **Entrée** pour enregistrer, **Ctrl+X** pour quitter. Une valeur par ligne, **sans guillemets**, sans espace autour du `=`.
- **Où suis-je ?** `pwd` affiche le dossier courant ; `cd ~/kaji` revient dans celui de Kaji. Les commandes `docker compose …` se tapent **toujours dans ce dossier**.
- **Un message d'erreur** : copie-le tel quel dans un ticket du dépôt (jamais un secret).

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
| `KAJI_TOKEN_KEY` / `KAJI_TOKEN_KEY_FILE` | facultatif : une **seconde** clé, différente de `KAJI_SECRET_KEY` | Active les **jetons Proxmox personnels** (chacun enregistre le sien : ses droits, son nom dans le journal de Proxmox). Mieux vaut un fichier (`KAJI_TOKEN_KEY_FILE`) hors de `.env` et hors de la sauvegarde. Voir `docs/api/jetons-utilisateur.md`. |
| `KAJI_TOKEN_KEY_PREVIOUS` | seulement pendant une rotation | Voir `docs/deploiement.md`. |
| `KAJI_REQUIRE_USER_TOKEN` | `false` (défaut) | `true` : sans jeton personnel, pas d'accès à Proxmox. |
| `KAJI_USER_TOKEN_MAX_DAYS` | `90` (défaut) | Durée maximale acceptée pour un jeton personnel. |
| `KAJI_SECRET_KEY_PREVIOUS` | seulement pendant une rotation | L'ancienne clé, pour `rotate-secret-key` : `docs/runbook.md`. |
| `KAJI_REQUIRE_SERVICE_TOKEN` | `false` (défaut) | `true` : le planificateur et les alertes ne font rien pour une connexion sans **jeton de service** limité (`docs/api/jeton-service.md`) au lieu d'utiliser le jeton partagé. |
| `KAJI_SERVICE_TOKEN_MAX_DAYS` | `365` (défaut) | Échéance maximale acceptée pour un jeton de service. |
| `KAJI_OIDC_ISSUER` | vide (défaut) | Adresse https du fournisseur OpenID Connect (Keycloak, Entra ID, Authentik…) : active le SSO. Vide : pas de SSO. Voir `docs/api/sso.md`. |
| `KAJI_OIDC_CLIENT_ID` | vide | Identifiant du client déclaré chez le fournisseur (obligatoire si le SSO est actif). |
| `KAJI_OIDC_CLIENT_SECRET` | vide | Secret du client (clients « confidentiels ») ; reste dans `.env`, jamais renvoyé ni journalisé. |
| `KAJI_OIDC_REDIRECT_URI` | vide | Adresse de retour EXACTE, en https, qui se termine par `/api/auth/oidc/callback` ; la même chez le fournisseur. |
| `KAJI_OIDC_SCOPES` | `openid profile` | Périmètres demandés (`openid` est toujours ajouté). |
| `KAJI_OIDC_USERNAME_CLAIM` | `preferred_username` | Champ du jeton qui désigne le compte de Kaji (lettres, chiffres, `.`, `_`, `-`, 3 à 64 caractères). |
| `KAJI_OIDC_AUTO_CREATE` | `false` | `true` : crée un compte neuf à la première connexion SSO ; sinon la personne doit déjà avoir un compte de Kaji. |
| `KAJI_OIDC_DEFAULT_ROLE` | `viewer` | Rôle d'un compte créé par le SSO : `viewer` ou `operator`, **jamais** administrateur. |
| `KAJI_OIDC_ALLOW_ADMIN` | `true` | `false` : les administrateurs ne se connectent pas par le SSO (mot de passe local seulement). |
| `KAJI_OIDC_GROUPS_CLAIM` | `groups` | Champ de l'ID token qui liste les groupes (ajouter le périmètre `groups` chez le fournisseur). |
| `KAJI_OIDC_ADMIN_GROUP` | vide | Nom **exact** du groupe dont les membres sont administrateurs de Kaji (donc de Proxmox) ; vide : aucun rôle n'est modifié. |
| `KAJI_OIDC_OPERATOR_GROUP` | vide | Nom exact du groupe dont les membres sont opérateurs. |
| `KAJI_OIDC_LABEL` | `SSO` | Texte du bouton de l'écran de connexion. |
| `KAJI_LDAP_URL` | vide (défaut) | Adresse de l'annuaire LDAP / Active Directory (`ldaps://hôte:636`) : active la connexion par annuaire. Vide : pas d'annuaire. Voir `docs/api/ldap.md`. |
| `KAJI_LDAP_START_TLS` | `false` | `true` avec une adresse `ldap://` : STARTTLS est négocié avant toute liaison. Sans `ldaps://` ni STARTTLS, la connexion est refusée (pas de mot de passe en clair). |
| `KAJI_LDAP_CA_FILE` | vide | Chemin d'une autorité privée de l'annuaire ; le certificat est toujours vérifié. |
| `KAJI_LDAP_TLS_SERVER_NAME` | vide | Nom que le certificat de l'annuaire doit porter quand l'adresse est une IP (sans DNS joignable) ; un nom DNS, jamais de joker. Vide : le nom de l'adresse. |
| `KAJI_LDAP_BASE_DN` | vide | Où chercher les personnes (obligatoire si l'annuaire est actif). |
| `KAJI_LDAP_BIND_DN` | vide | Compte de **lecture seule** qui retrouve l'entrée de la personne (obligatoire si l'annuaire est actif). |
| `KAJI_LDAP_BIND_PASSWORD` | vide | Mot de passe de ce compte de lecture ; reste dans `.env`, jamais renvoyé ni journalisé. |
| `KAJI_LDAP_USER_FILTER` | `(&(objectClass=person)(uid={username}))` | Filtre de recherche, qui contient `{username}` (Active Directory : `(&(objectClass=user)(sAMAccountName={username}))`). |
| `KAJI_LDAP_USERNAME_ATTR` | `uid` | Attribut qui porte l'identifiant (`sAMAccountName` pour Active Directory). |
| `KAJI_LDAP_AUTO_CREATE` | `false` | `true` : crée un compte neuf à la première connexion par l'annuaire ; sinon la personne doit déjà avoir un compte de Kaji (jamais un administrateur). |
| `KAJI_LDAP_DEFAULT_ROLE` | `viewer` | Rôle d'un compte créé par l'annuaire : `viewer` ou `operator`, **jamais** administrateur. |
| `KAJI_LDAP_ALLOW_ADMIN` | `true` | `false` : les administrateurs ne se connectent pas par l'annuaire (mot de passe local seulement). |
| `KAJI_LDAP_GROUPS_ATTR` | `memberOf` | Attribut de l'entrée qui liste les groupes de la personne (groupes directs seulement). |
| `KAJI_LDAP_ADMIN_GROUP` | vide | DN **exact** du groupe dont les membres sont administrateurs de Kaji (donc de Proxmox) ; vide : aucun rôle n'est modifié. |
| `KAJI_LDAP_OPERATOR_GROUP` | vide | DN exact du groupe dont les membres sont opérateurs. |
| `KAJI_LDAP_LABEL` | `Annuaire` | Texte de la case de l'écran de connexion. |
| `KAJI_TOKEN_CREATE_MAX_DAYS` | `365` (défaut) | Jetons Proxmox créés par l'administrateur depuis Kaji (page « Accès ») : **l'expiration est obligatoire** et au plus ce nombre de jours (`0` = facultative, déconseillé). |
| `KAJI_MAX_CONCURRENT_REQUESTS` | `100` (défaut) | Requêtes simultanées au plus ; au-delà, **503** immédiat au lieu d'un blocage (`docs/robustesse.md`). |
| `KAJI_SCHEDULER` | `true` (défaut) | Planificateur d'actions et alertes. **Une seule instance de Kaji** doit tourner, sinon actions et alertes sont doublées. |
| `KAJI_TRUST_PROXY` | laisse `false` | Le `docker-compose.yml` le règle déjà pour le conteneur. |
| `KAJI_AUDIT_RETENTION_DAYS` | `365` (défaut) | Conservation du journal d'audit de Kaji, en jours (`0` = indéfiniment). |
| `KAJI_AUDIT_FILE` | vide (défaut) | Copie de l'audit dans un fichier JSON (une ligne par événement, droits `600`) : chemin **absolu**, dans le volume `/data` si tu es dans Docker (`/data/audit.jsonl`). Voir `docs/api/audit-export.md`. |
| `KAJI_AUDIT_FILE_MAX_MB` | `10` (défaut) | Taille à partir de laquelle le fichier d'audit tourne (1 à 1024). |
| `KAJI_AUDIT_FILE_BACKUPS` | `10` (défaut) | Nombre d'anciens fichiers d'audit gardés (`0` = pas de rotation : le fichier grossit sans limite). |
| `KAJI_AUDIT_SYSLOG` | vide (défaut) | Envoi de l'audit à un serveur syslog : `udp://hôte:port` ou `tcp://hôte:port` (en clair : réseau de confiance seulement). Une valeur mal formée empêche Kaji de démarrer. |
| `KAJI_VERSION` | `latest` (défaut) | Version des **images publiées** (`install.sh --image`, § 3.2 bis) : `latest` ou une étiquette précise comme `v1.0.0-rc1` (recommandé). Sans effet si tu construis Kaji sur place. |
| `KAJI_BIND` | `127.0.0.1` (défaut) | Interface d'écoute de nginx. `0.0.0.0` ouvre tout le réseau : seulement derrière le HTTPS de l'étape 5. |
| `KAJI_PORT` | `8080` (défaut) | Port de nginx. |

Les variables `KAJI_TLS_*` et `KAJI_HTTP_PORT` ne servent qu'à l'étape 5.

### 3.1 bis Tout le `.env` d'un coup (un seul copier-coller)
Si tu préfères ne pas éditer le tableau ligne par ligne : **dans le dossier `kaji`, colle ce bloc entier dans le terminal**. Il **crée `.env`** (en remplaçant celui de l'étape 3), **génère les deux secrets pour toi** et laisse en commentaire (`#`) toutes les options facultatives, avec leur valeur par défaut. Une option s'active en retirant le `#` au début de sa ligne (`nano .env`).
```bash
cat > .env <<EOF
# ===== À RÉGLER (les seuls réglages utiles pour démarrer) =====
KAJI_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
KAJI_SETUP_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
KAJI_PROTECTED_VMIDS=
KAJI_COOKIE_SECURE=true
KAJI_BIND=127.0.0.1
KAJI_PORT=8080
KAJI_AUDIT_RETENTION_DAYS=365
KAJI_TRUST_PROXY=false

# ===== HTTPS (étape 5) : retire le # et mets TON adresse, SANS port =====
# KAJI_TLS_SITE=192.168.1.10
# KAJI_TLS_NAME=kaji.home
# KAJI_TLS_PORT=443
# KAJI_HTTP_PORT=80
# KAJI_TLS_BIND=0.0.0.0

# ===== Facultatif : version des images publiées (install.sh --image) =====
# KAJI_VERSION=latest

# ===== Facultatif : jetons Proxmox personnels, de service, planificateur =====
# KAJI_ADMIN_USE_KAJI_TOKEN=true
# KAJI_SCHEDULER=true
# KAJI_TOKEN_KEY=
# KAJI_TOKEN_KEY_FILE=
# KAJI_TOKEN_KEY_PREVIOUS=
# KAJI_REQUIRE_USER_TOKEN=false
# KAJI_USER_TOKEN_MAX_DAYS=90
# KAJI_TOKEN_CREATE_MAX_DAYS=365
# KAJI_REQUIRE_SERVICE_TOKEN=false
# KAJI_SERVICE_TOKEN_MAX_DAYS=365
# KAJI_MAX_CONCURRENT_REQUESTS=100
# KAJI_SECRET_KEY_PREVIOUS=

# ===== Facultatif : export de l'audit =====
# KAJI_AUDIT_FILE=/data/audit.jsonl
# KAJI_AUDIT_FILE_MAX_MB=10
# KAJI_AUDIT_FILE_BACKUPS=10
# KAJI_AUDIT_SYSLOG=udp://syslog.example.com:514

# ===== Facultatif : SSO OpenID Connect =====
# KAJI_OIDC_ISSUER=https://idp.example.com/realms/entreprise
# KAJI_OIDC_CLIENT_ID=kaji
# KAJI_OIDC_CLIENT_SECRET=
# KAJI_OIDC_REDIRECT_URI=https://kaji.example.com/api/auth/oidc/callback
# KAJI_OIDC_SCOPES=openid profile
# KAJI_OIDC_USERNAME_CLAIM=preferred_username
# KAJI_OIDC_AUTO_CREATE=false
# KAJI_OIDC_DEFAULT_ROLE=viewer
# KAJI_OIDC_LABEL=SSO
# KAJI_OIDC_ALLOW_ADMIN=true
# KAJI_OIDC_GROUPS_CLAIM=groups
# KAJI_OIDC_ADMIN_GROUP=
# KAJI_OIDC_OPERATOR_GROUP=

# ===== Facultatif : annuaire LDAP / Active Directory =====
# KAJI_LDAP_URL=ldaps://annuaire.example.com:636
# KAJI_LDAP_START_TLS=false
# KAJI_LDAP_CA_FILE=
# KAJI_LDAP_TLS_SERVER_NAME=
# KAJI_LDAP_BASE_DN=dc=example,dc=com
# KAJI_LDAP_BIND_DN=cn=kaji-lecture,dc=example,dc=com
# KAJI_LDAP_BIND_PASSWORD=
# KAJI_LDAP_USER_FILTER=(&(objectClass=person)(uid={username}))
# KAJI_LDAP_USERNAME_ATTR=uid
# KAJI_LDAP_AUTO_CREATE=false
# KAJI_LDAP_DEFAULT_ROLE=viewer
# KAJI_LDAP_LABEL=Annuaire
# KAJI_LDAP_ALLOW_ADMIN=true
# KAJI_LDAP_GROUPS_ATTR=memberOf
# KAJI_LDAP_ADMIN_GROUP=
# KAJI_LDAP_OPERATOR_GROUP=
EOF
chmod 600 .env
grep -E '^KAJI_(SECRET_KEY|SETUP_TOKEN)=' .env     # affiche tes deux secrets : copie-les dans ton gestionnaire de mots de passe
```
- **À retenir** : `KAJI_SETUP_TOKEN` sert **une seule fois**, à créer le compte administrateur (§ 3.3) ; `KAJI_SECRET_KEY` doit être **sauvegardée à part** (§ 7).
- Pour **protéger tes machines importantes** : `nano .env`, puis `KAJI_PROTECTED_VMIDS=100,101` (les numéros de tes VM).
- Les lignes `#` n'ont aucun effet tant que tu n'as pas retiré le `#`. Ne mets **jamais** ce fichier dans Git ni dans un ticket.

### 3.2 Démarrer
```bash
docker compose up -d --build
docker compose ps                                # backend et web : « healthy » / « running »
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/health     # 200
```
Le premier démarrage construit les images (quelques minutes). Si `backend` redémarre en boucle : `docker compose logs backend` (cause la plus fréquente : `KAJI_SECRET_KEY` vide ou d'exemple).

**Ce que font ces commandes, et comment lire le résultat**
- `docker compose up -d --build` : **construit** les images (`--build`, quelques minutes la première fois) et **lance** les conteneurs en arrière-plan (`-d`). Elle ne bloque pas le terminal.
- `docker compose ps` : la liste des conteneurs. `backend` doit afficher `healthy` (ou `Up`) et `web` `Up` ; **`Restarting` veut dire un problème** : `docker compose logs backend` donne la raison dans ses dernières lignes (le plus souvent `KAJI_SECRET_KEY` vide).
- `docker compose logs -f backend` : suit le journal en direct (Ctrl+C pour arrêter de suivre, ça n'arrête pas Kaji).
- `docker compose stop` / `docker compose start` : arrête / relance Kaji **sans rien perdre**. `docker compose down` supprime les conteneurs **mais garde les données** (volume `kaji-data`) ; **`docker compose down -v` EFFACE la base** (comptes, connexions, audit) : ne le tape jamais sans sauvegarde (§ 7).
- Si tu as activé le HTTPS (§ 5), **ajoute `-f docker-compose.yml -f docker-compose.tls.yml` à chaque commande `docker compose`** (sinon Caddy s'arrête).
- Après un redémarrage de la machine, Kaji repart tout seul (Docker relance les conteneurs).

### 3.2 bis Sans compiler : utiliser les images publiées
Les versions étiquetées publient leurs images sur `ghcr.io` (`ghcr.io/ek8oxilive/kaji-backend` et `kaji-web`, amd64 et arm64). Au lieu de `docker compose up -d --build` (plusieurs minutes de compilation), tu peux faire :
```bash
docker compose -f docker-compose.yml -f docker-compose.image.yml pull
docker compose -f docker-compose.yml -f docker-compose.image.yml up -d
```
Choisis la version avec `KAJI_VERSION=v1.0.0-rc1` dans `.env` (sinon `latest`). Avec le script d'installation express : `sh install.sh --image`. Si `pull` répond « not found » ou « denied », **aucune image n'est encore publiée pour cette version** : reviens à `--build`. Les images ne sont **pas signées** ; seules les sources le sont (`docs/signature.md`). Ajoute `-f docker-compose.tls.yml` à chaque commande si tu as activé le HTTPS.

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

**Installer `caddy-root.crt` sur ton poste** (la machine qui ouvre Kaji, pas la machine de Kaji). Récupère d'abord le fichier : `scp <utilisateur>@<adresse de Kaji>:~/kaji/caddy-root.crt .` (ou copie son contenu dans un fichier du même nom). C'est un certificat **public** (pas un secret) ; **n'installe jamais** un certificat d'autorité reçu d'une source que tu ne connais pas.
- **Windows** : double-clique le fichier → « Installer le certificat… » → « Ordinateur local » → « Placer tous les certificats dans le magasin suivant » → **« Autorités de certification racines de confiance »** → Terminer. Ou, dans un PowerShell **administrateur** : `certutil -addstore -f Root caddy-root.crt`. Redémarre le navigateur.
- **macOS** : `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain caddy-root.crt`, puis redémarre le navigateur.
- **Linux** (Debian / Ubuntu) : `sudo cp caddy-root.crt /usr/local/share/ca-certificates/caddy-root.crt && sudo update-ca-certificates`. Chrome et Chromium lisent leur propre magasin : Paramètres → Confidentialité et sécurité → Sécurité → Gérer les certificats → **Autorités** → Importer.
- **Firefox** (tous systèmes, il a son propre magasin) : Paramètres → Vie privée et sécurité → Certificats → « Afficher les certificats… » → **Autorités** → Importer → coche « Confirmer cette AC pour identifier des sites web ».

Vérification : ouvre `https://<adresse>` ; le cadenas doit être fermé, sans avertissement. Si le navigateur affiche encore « connexion non sécurisée », le certificat n'est pas dans le bon magasin, ou tu ouvres Kaji par un nom ou une adresse qui n'est ni `KAJI_TLS_SITE` ni `KAJI_TLS_NAME`.

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
- `docs/runbook.md` : exploitation au quotidien (supervision, rotation des secrets, restauration, mise à jour, incidents).
- `docs/securite.md` : revue de sécurité, ce qui est vérifié, ce qui reste à décider.
- `docs/statut-fonctions.md` : quelles fonctions sont « validées en réel » et lesquelles sont « expérimentales ».
- `docs/cadrage-prod-entreprise.md` : ce qui sépare ce lab d'une production en entreprise.
- **Signaler un problème** : un ticket sur le dépôt. **Une faille de sécurité** : pas de ticket public, suis `SECURITY.md` (signalement privé). L'historique des versions est dans `CHANGELOG.md`.
