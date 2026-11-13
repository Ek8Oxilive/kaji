# Déploiement avec Docker

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
# .env : KAJI_COOKIE_SECURE=true, KAJI_TLS_SITE=192.168.1.10:8443 (l'adresse par laquelle tu ouvres Kaji, avec le port), KAJI_BIND=127.0.0.1
docker compose down                     # le réseau change de sous-réseau : il doit être recréé
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build
docker compose cp tls:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt   # à installer comme autorité de confiance dans ton navigateur ou ton système
```
Ouvre ensuite `https://<adresse>:8443`. **Non testé en réel par les agents** (pas de Docker sur leur poste) : essaie d'abord sur une machine qui ne compte pas, et garde l'ancien accès HTTP (`KAJI_BIND`) tant que le HTTPS n'est pas vérifié. Pense à sauvegarder le volume `caddy-data` (clé de l'autorité interne). Avec Tailscale, `tailscale serve` fait la même chose sans Caddy.

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

## Sauvegarde et restauration
**Il faut sauvegarder DEUX choses ensemble : la base ET `KAJI_SECRET_KEY`.** La base contient les tokens Proxmox et les adresses de webhook des alertes **chiffrés** avec cette
clé : l'une sans l'autre est inutilisable. Elle contient aussi les utilisateurs de Kaji et leurs rôles, les actions planifiées, les règles d'alerte et l'audit.
```bash
docker volume ls                                                   # repère le volume, ex. kaji_kaji-data
docker run --rm -v kaji_kaji-data:/data -v "$PWD":/backup alpine tar czf /backup/kaji-data.tgz -C /data .
cp .env /chemin/sûr/kaji.env                                       # la clé, séparément de la base
```
Restauration : recrée le volume, extrais l'archive dedans, remets le même `.env`, puis `docker compose up -d`.
**Perdre la clé** = les connexions Proxmox enregistrées sont à ressaisir (le compte et l'audit restent).

## Mot de passe perdu
La création du **premier** compte par l'écran de première configuration n'est possible qu'une fois ; les autres comptes se créent ensuite par un administrateur (bouton « Compte » → « Gérer les utilisateurs »). Pour un mot de passe oublié, **sur le serveur** :
```bash
docker compose exec backend python -m app.admin_cli reset-password                 # s'il n'y a qu'un compte
docker compose exec backend python -m app.admin_cli reset-password --user <nom>    # sinon : « Plusieurs comptes : précise lequel avec --user »
```
Le nouveau mot de passe est saisi de façon masquée ; toutes les sessions du compte sont révoquées ; l'opération est inscrite dans l'audit. Le rôle du compte ne change pas.
Les connexions Proxmox sont conservées.

## Ce que fait (et ne fait pas) cette configuration
- Backend : utilisateur sans privilèges, **un seul processus** (le limiteur de connexions, le flux temps réel, **le planificateur d'actions et l'évaluation des alertes** vivent en mémoire :
  ne pas lancer plusieurs workers ni deux instances, les actions et les alertes seraient doublées ; `KAJI_SCHEDULER=false` les coupe), jamais publié sur le réseau, base en `600`.
- Frontend : politique de sécurité de contenu (CSP) restrictive, pas de script en ligne, `X-Frame-Options: DENY`, cache illimité pour
  les fichiers à hash, jamais pour l'application.
- **Non fournis par défaut** : le HTTPS (option Caddy ci-dessus), l'authentification à deux facteurs pour se connecter à Kaji, l'envoi d'e-mails (les alertes passent par un webhook).
- **Images non verrouillées par empreinte** : `python:3.12-slim`, `node:22-alpine` et `nginx:1.27-alpine` sont désignées par leur étiquette.
