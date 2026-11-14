# Déploiement avec Docker

> **Première installation ? Suis plutôt le guide pas à pas `docs/installation-lab.md`** (prérequis, jeton Proxmox au moindre privilège, variables, HTTPS, sauvegarde). Cette page en est le détail technique.

Deux conteneurs : **backend** (FastAPI, base SQLite dans un volume) et **web** (nginx : fichiers statiques et relais de `/api`).
Seul `web` écoute sur le réseau, **par défaut sur cette machine uniquement** (`127.0.0.1:8080`).

> **N'expose jamais Kaji directement sur Internet.** Il détient un token Proxmox aux droits étendus. Utilise le réseau local,
> Tailscale/un VPN, ou un reverse proxy HTTPS avec accès restreint.

## Installation
```bash
git clone https://github.com/Ek8Oxilive/kaji.git && cd kaji
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"      # colle le résultat dans KAJI_SECRET_KEY du .env
# (Kaji refuse de démarrer avec la valeur d'exemple « changeme » et signale une clé de moins de 32 caractères.)
docker compose up -d --build
```
Ouvre http://127.0.0.1:8080 et **crée tout de suite le compte administrateur** (première configuration) : tant qu'il n'existe pas,
n'importe qui atteignant la page peut le créer. Garde donc `KAJI_BIND=127.0.0.1` jusqu'à cette étape.

Dans `.env`, pense aussi à `KAJI_PROTECTED_VMIDS` (machines que Kaji refuse de supprimer **et sur lesquelles il refuse toute action planifiée**, ex. `105,108`) et à `KAJI_SETUP_TOKEN` (voir plus bas). `KAJI_ADMIN_USE_KAJI_TOKEN` reste **désactivé** tant que tu n'as pas décidé de donner les droits d'administration au jeton de Kaji (voir `docs/securite.md`).

## Accès depuis un autre poste, HTTPS
Le cookie de session est `Secure` : il n'est accepté par le navigateur qu'en **HTTPS** ou sur `localhost`. En HTTP sur ton réseau
local (`http://192.168.x.x:8080`), la connexion échoue **sans message d'erreur** : le formulaire se revalide puis revient
à l'écran de connexion (les journaux montrent `POST /api/auth/login 200` suivi d'un état « non connecté »). Deux solutions :
1. **HTTPS** devant `web` (recommandé) : Tailscale (`tailscale serve`, vérifie la syntaxe de ta version), ou un reverse proxy
   (Caddy, Traefik, nginx) qui termine le TLS et relaie vers `127.0.0.1:8080`.
2. En dernier recours, sur un réseau de confiance : `KAJI_COOKIE_SECURE=false` dans `.env` (le cookie circule alors en clair). Puis `docker compose up -d --force-recreate backend` : un simple `restart`
   ne relit pas `.env`.

Pour écouter sur le réseau : `KAJI_BIND=0.0.0.0` dans `.env`, puis `docker compose up -d`.

### HTTPS fourni en option : Caddy (`docker-compose.tls.yml`)
Un conteneur Caddy termine le TLS avec **son autorité interne** (`tls internal`) et relaie vers nginx ; nginx reprend l'adresse du client que Caddy lui donne (`deploy/realip.conf`, réseau Docker à adresses fixes `172.29.77.0/24`), donc **le limiteur de connexions voit bien chaque client**.
```bash
# .env : KAJI_COOKIE_SECURE=true, KAJI_TLS_NAME=kaji.home (un nom DNS local, facultatif : le certificat couvre l'adresse ET ce nom), KAJI_TLS_SITE=192.168.1.10 (l'adresse par laquelle tu ouvres Kaji, SANS port : HTTPS sur 443, le port 80 renvoie vers HTTPS), KAJI_BIND=127.0.0.1
docker compose down                     # le réseau change de sous-réseau : il doit être recréé
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build
docker compose cp tls:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt   # à installer comme autorité de confiance dans ton navigateur ou ton système
```
Ouvre ensuite `https://<adresse>` (port 443, `KAJI_TLS_PORT`). **Non testé en réel par les agents** (pas de Docker sur leur poste) : essaie d'abord sur une machine qui ne compte pas, et garde l'ancien accès HTTP (`KAJI_BIND`) tant que le HTTPS n'est pas vérifié. Pense à sauvegarder le volume `caddy-data` (clé de l'autorité interne). Avec Tailscale, `tailscale serve` fait la même chose sans Caddy.

## Épinglage du certificat de Proxmox (page « Connexions »)
Le certificat par défaut de Proxmox n'est signé par aucune autorité publique, donc « Vérifier le certificat SSL » ne marche pas sans l'avoir remplacé. **Épingler** règle cela : bouton « Épingler le certificat… » sur la connexion, compare l'empreinte SHA-256 affichée à celle de ton nœud (`openssl x509 -fingerprint -sha256 -noout -in /etc/pve/local/pve-ssl.pem` sur le nœud, ou la colonne « Empreinte du certificat » de la page Cluster), coche la case et confirme. Kaji n'acceptera plus **que ce certificat**, y compris pour les consoles ; s'il change (renouvellement, ou usurpation), les appels échouent avec un message clair jusqu'à ce que tu épingles le nouveau. Changer l'hôte ou le port de la connexion retire l'épingle. Détails : `docs/api/connexions-tls.md`.

## Jeton de première configuration
`KAJI_SETUP_TOKEN` dans `.env` (valeur aléatoire, ex. `python3 -c "import secrets; print(secrets.token_urlsafe(24))"`) : tant qu'aucun compte n'existe, l'écran de première configuration le demande, et les essais ratés sont limités (5 par 5 minutes et par adresse). Il ne sert qu'une fois, pour créer le compte ; ensuite il n'a plus d'effet. Sans lui, le premier qui atteint le port crée le compte.

**Limiteur de connexions derrière un autre proxy** (hors l'option Caddy ci-dessus, qui le règle). nginx écrase `X-Forwarded-For` par l'adresse qu'il voit. Derrière Caddy ou
Tailscale, c'est l'adresse **du proxy** : tous les clients partagent alors le même limiteur (5 échecs / 5 min pour tout le monde).
Pas de contournement par un en-tête falsifié, mais un attaquant pourrait bloquer la connexion des autres pendant 5 minutes.

## Mise à jour
```bash
git pull && docker compose up -d --build
```
Les **migrations de schéma** s'exécutent au démarrage. Avant toute migration, la base est copiée dans le volume
(`kaji.db.bak-vN-AAAAMMJJ-HHMMSS`, les 5 dernières sont gardées). Si Kaji refuse de démarrer sur une base « plus récente que le
code », c'est que tu as redescendu de version : restaure une sauvegarde d'avant la mise à niveau.
État : `docker compose exec backend python -m app.migrations status`.
**Testé à chaque modification** : des bases d'exemple produites par le vrai code de chaque version étiquetée (et de deux anciens états du schéma) sont migrées vers le code courant par la CI, sans perte de valeur, avec relecture des jetons, webhooks, comptes et rôles (`backend/tests/test_upgrade_from_versions.py`, `backend/tests/fixtures/db/`). **Retour arrière** : restaure la sauvegarde faite avant la mise à jour (`tools/restore.sh`, section suivante) puis remets le code de l'ancienne étiquette ; **essayé avec de vraies bases, pas encore avec le vrai Docker** (ticket #456).

## Sauvegarde et restauration
**Il faut sauvegarder DEUX choses ensemble : la base ET `KAJI_SECRET_KEY`.** La base contient les tokens Proxmox et les adresses de webhook des alertes **chiffrés** avec cette
clé : l'une sans l'autre est inutilisable. Elle contient aussi les utilisateurs de Kaji et leurs rôles, les actions planifiées, les règles d'alerte et l'audit. La clé est dans `.env`, **jamais dans la base** : sauvegarde `.env` à part, en lieu sûr (gestionnaire de mots de passe).

### Sauvegarder (sans arrêter Kaji)
```bash
tools/backup.sh [DOSSIER]          # défaut : ./sauvegardes ; crée kaji-AAAAMMJJ-HHMMSS.db en 600 (dossier en 700)
```
Le script demande au conteneur une **copie cohérente de la base en service** (API de sauvegarde de SQLite : une copie de fichier faite pendant une écriture peut être déchirée), puis **relit cette copie avec la clé actuelle** (`verify`) : si un jeton ou un webhook n'est pas lisible, il échoue et le dit. Il affiche l'**empreinte de la clé** (8 caractères qui permettent de reconnaître la clé sans la révéler) : note-la avec la sauvegarde de `.env`. Il ne sauvegarde pas la clé lui-même. Le HTTPS (Caddy) est détecté tout seul.

Pas de sauvegarde automatique fournie. Une ligne `cron` peut appeler le script (`0 3 * * * cd /chemin/vers/kaji && tools/backup.sh /chemin/sûr`) : **non essayé**. Pense à purger les anciennes copies et à les emmener **hors de la machine**.

### Contrôler une base ou une sauvegarde
```bash
docker compose exec backend python -m app.admin_cli verify                      # la base en service
docker compose exec -T backend python -m app.admin_cli verify --file - < kaji-….db     # une sauvegarde
```
Affiche l'intégrité SQLite, le numéro de schéma, le nombre de comptes par rôle, de connexions (**jetons déchiffrés : n/n**, certificats épinglés), de règles d'alerte (**webhooks déchiffrés : n/n**), d'actions planifiées et d'entrées d'audit. **Jamais une valeur secrète** ; code de sortie 1 s'il y a un problème (base abîmée, aucun administrateur, secret illisible avec cette clé).

### Restaurer
```bash
# 1. remets le MÊME .env (même KAJI_SECRET_KEY) que celui de la sauvegarde
tools/restore.sh kaji-AAAAMMJJ-HHMMSS.db          # demande de taper RESTAURER (--yes pour passer la question)
```
Déroulé : arrêt du backend → `restore` dans un conteneur jetable → redémarrage → `verify`. `restore` **refuse, sans rien modifier**, un fichier qui n'est pas une base SQLite saine de Kaji, un schéma plus récent que le code (mets Kaji à jour d'abord), ou une sauvegarde dont un jeton ou un webhook n'est **pas lisible avec la clé actuelle** (mauvais `.env`). L'ancienne base reste dans le volume (`kaji.db.avant-restauration-AAAAMMJJ-HHMMSS`, à supprimer à la main quand tu es sûr) et son journal SQLite périmé est retiré. Les sessions enregistrées au moment de la sauvegarde devraient rester valides tant qu'elles n'ont pas expiré (**non vérifié**) ; les migrations s'appliquent au démarrage si la sauvegarde est plus ancienne.
Termine par un essai à la main : connexion à Kaji, page « Connexions » → « Tester », actions planifiées et alertes présentes.

**Perdre la clé** = les connexions Proxmox enregistrées et les webhooks sont à ressaisir (les comptes, les rôles et l'audit restent lisibles). `tools/restore.sh` **refuse** alors la sauvegarde, par prudence : elle remplacerait une base qui marche par une base dont les jetons sont inutilisables. Pour récupérer quand même les comptes et l'audit, utilise la méthode de secours (copie du volume, ci-dessous), puis ressaisis les connexions et les webhooks.

### Ce qui a été essayé, et ce qui ne l'a pas été
- **Essayé (tests automatiques, vraies bases SQLite)** : sauvegarde d'une base en service avec une écriture non validée (absente de la copie), aller-retour complet sauvegarde → perte → restauration → relecture par l'application des comptes, rôles, jeton, webhooks, planification, audit ; refus avec la mauvaise clé, un fichier tronqué ou étranger, un schéma trop récent ; retour en arrière si le remplacement final échoue ; aucun secret affiché.
- **Essayé avec un faux `docker`** (qui exécute les vraies commandes) : l'enchaînement des deux scripts, la confirmation, les refus, les droits des fichiers, le choix des fichiers Compose.
- **PAS essayé : le vrai Docker** (volume, utilisateur du conteneur, `compose run`, `--wait`). Le critère de sortie du jalon J1 (« restauration validée ») n'est donc **pas** rempli tant qu'une sauvegarde n'a pas été restaurée sur une machine avec Docker (ticket #429).

### Autre méthode : copie du volume entier (secours)
Arrête d'abord le backend (`docker compose stop backend`), puis :
```bash
docker volume ls                                                   # repère le volume, ex. kaji_kaji-data
docker run --rm -v kaji_kaji-data:/data -v "$PWD":/backup alpine tar czf /backup/kaji-data.tgz -C /data .
docker compose start backend
cp .env /chemin/sûr/kaji.env                                       # la clé, séparément de la base
```
Restauration : recrée le volume, extrais l'archive dedans, remets le même `.env`, puis `docker compose up -d`. Cette méthode copie aussi les anciennes sauvegardes de migration (`kaji.db.bak-vN-…`).

## Jetons Proxmox personnels : clé séparée et rotation
Chaque utilisateur peut enregistrer **son** jeton Proxmox (fenêtre « Compte » → « Mon jeton Proxmox ») : Proxmox applique alors **ses** droits et son journal le **nomme** (`docs/api/jetons-utilisateur.md`). Ces jetons sont chiffrés avec **`KAJI_TOKEN_KEY`**, une clé **différente** de `KAJI_SECRET_KEY` : compromettre l'une n'ouvre pas l'autre.

**Mise en place**
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"      # une NOUVELLE valeur, différente de KAJI_SECRET_KEY
```
- Soit `KAJI_TOKEN_KEY=…` dans `.env` (simple, mais la clé suit alors la sauvegarde de `.env`).
- Soit **un fichier** hors de `.env` : `KAJI_TOKEN_KEY_FILE=/run/secrets/kaji_token_key`, monté en lecture seule dans le conteneur backend (par exemple `volumes: ["./secrets/token.key:/run/secrets/kaji_token_key:ro"]` dans un fichier Compose à toi, fichier en `600`). Avec la clé dans un fichier à part, **la base et `.env` réunis ne permettent pas de lire un jeton** (test automatisé). **Non essayé avec Docker** (montage, droits du fichier pour l'utilisateur 10001 du conteneur).
- Redémarre : `docker compose up -d --force-recreate backend`. Sans clé, la fonction est simplement désactivée (la fenêtre l'explique).
- `KAJI_REQUIRE_USER_TOKEN=true` : un utilisateur sans jeton personnel n'a plus accès à Proxmox. À n'activer qu'une fois que chacun a enregistré le sien ; les tâches de fond (planificateur, alertes) gardent le jeton partagé.

**Sauvegarde** : `tools/backup.sh` sauvegarde la base (qui contient les jetons chiffrés) ; **la clé `KAJI_TOKEN_KEY` se sauvegarde à part, séparément de la base ET de `.env`** (gestionnaire de mots de passe). `verify` et `restore` relisent les jetons personnels avec cette clé et **refusent** une sauvegarde qu'elle ne lit pas.

**Rotation de `KAJI_TOKEN_KEY`** (par exemple tous les 12 mois, ou si la clé a pu fuiter)
1. `tools/backup.sh` (et note l'ancienne clé : les anciennes sauvegardes restent chiffrées avec elle).
2. Génère la nouvelle clé ; mets **`KAJI_TOKEN_KEY` = la nouvelle** et **`KAJI_TOKEN_KEY_PREVIOUS` = l'ancienne** ; redémarre le backend (les deux clés lisent, la nouvelle écrit).
3. `docker compose exec backend python -m app.admin_cli rotate-token-key --yes` : ré-chiffre **tous** les jetons en une transaction (tout ou rien), relit chacun avec la seule nouvelle clé, n'affiche que des nombres. `--drop-unreadable` supprime les jetons qu'aucune des deux clés ne lit (leurs propriétaires les enregistrent de nouveau).
4. Retire `KAJI_TOKEN_KEY_PREVIOUS`, redémarre, `docker compose exec backend python -m app.admin_cli verify` : « jetons personnels déchiffrés : n/n ».
**Essayée sur de vraies bases SQLite et des commandes réelles, pas avec Docker.** Perdre la clé = les jetons personnels sont à ré-enregistrer (les comptes, les rôles et le reste restent).

**Un jeton personnel expire** : Kaji cesse de l'utiliser à la date retenue (au plus `KAJI_USER_TOKEN_MAX_DAYS` jours après l'enregistrement) et le dit clairement ; l'utilisateur en crée un nouveau dans Proxmox et l'enregistre.

## Mot de passe perdu
La création du **premier** compte par l'écran de première configuration n'est possible qu'une fois ; les autres comptes se créent ensuite par un administrateur (bouton « Compte » → « Gérer les utilisateurs »). Pour un mot de passe oublié, **sur le serveur** :
```bash
docker compose exec backend python -m app.admin_cli reset-password                 # s'il n'y a qu'un compte
docker compose exec backend python -m app.admin_cli reset-password --user <nom>    # sinon : « Plusieurs comptes : précise lequel avec --user »
```
Le nouveau mot de passe est saisi de façon masquée ; toutes les sessions du compte sont révoquées ; l'opération est inscrite dans l'audit. Le rôle du compte ne change pas.
Les connexions Proxmox sont conservées.

## Ce que fait (et ne fait pas) cette configuration
- Backend : utilisateur sans privilèges, **un seul processus** (le flux temps réel, **le planificateur d'actions et l'évaluation des alertes** vivent en mémoire :
  ne pas lancer plusieurs workers ni deux instances, les actions et les alertes seraient doublées ; `KAJI_SCHEDULER=false` les coupe), jamais publié sur le réseau, base en `600`.
- Frontend : politique de sécurité de contenu (CSP) restrictive, pas de script en ligne, `X-Frame-Options: DENY`, cache illimité pour
  les fichiers à hash, jamais pour l'application.
- **Non fournis par défaut** : le HTTPS (option Caddy ci-dessus), l'authentification à deux facteurs pour se connecter à Kaji, l'envoi d'e-mails (les alertes passent par un webhook).
- **Images de base épinglées par empreinte** (`python`, `node`, `nginx`, `caddy` : `nom:étiquette@sha256:…`) : une reconstruction redonne les mêmes images. Contrepartie : elles ne reçoivent plus de correctif de sécurité tant que l'empreinte n'est pas mise à jour (Dependabot ou `tools/image_digests.sh`) : `docs/images-et-versions.md`.
