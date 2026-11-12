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

Dans `.env`, pense aussi à `KAJI_PROTECTED_VMIDS` (machines que Kaji refuse de supprimer, ex. `105,108`).

## Accès depuis un autre poste, HTTPS
Le cookie de session est `Secure` : il n'est accepté par le navigateur qu'en **HTTPS** ou sur `localhost`. En HTTP sur ton réseau
local (`http://192.168.x.x:8080`), la connexion échoue **sans message d'erreur** : le formulaire se revalide puis revient
à l'écran de connexion (les journaux montrent `POST /api/auth/login 200` suivi d'un état « non connecté »). Deux solutions :
1. **HTTPS** devant `web` (recommandé) : Tailscale (`tailscale serve`, vérifie la syntaxe de ta version), ou un reverse proxy
   (Caddy, Traefik, nginx) qui termine le TLS et relaie vers `127.0.0.1:8080`.
2. En dernier recours, sur un réseau de confiance : `KAJI_COOKIE_SECURE=false` dans `.env` (le cookie circule alors en clair). Puis `docker compose up -d --force-recreate backend` : un simple `restart`
   ne relit pas `.env`.

Pour écouter sur le réseau : `KAJI_BIND=0.0.0.0` dans `.env`, puis `docker compose up -d`.

**Limiteur de connexions derrière un autre proxy.** nginx écrase `X-Forwarded-For` par l'adresse qu'il voit. Derrière Caddy ou
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
**Il faut sauvegarder DEUX choses ensemble : la base ET `KAJI_SECRET_KEY`.** La base contient les tokens Proxmox **chiffrés** avec cette
clé : l'une sans l'autre est inutilisable.
```bash
docker volume ls                                                   # repère le volume, ex. kaji_kaji-data
docker run --rm -v kaji_kaji-data:/data -v "$PWD":/backup alpine tar czf /backup/kaji-data.tgz -C /data .
cp .env /chemin/sûr/kaji.env                                       # la clé, séparément de la base
```
Restauration : recrée le volume, extrais l'archive dedans, remets le même `.env`, puis `docker compose up -d`.
**Perdre la clé** = les connexions Proxmox enregistrées sont à ressaisir (le compte et l'audit restent).

## Mot de passe perdu
La création de compte par l'interface n'est possible qu'à la toute première utilisation. Pour un mot de passe oublié, **sur le serveur** :
```bash
docker compose exec backend python -m app.admin_cli reset-password
```
Le nouveau mot de passe est saisi de façon masquée ; toutes les sessions sont révoquées ; l'opération est inscrite dans l'audit.
Les connexions Proxmox sont conservées.

## Ce que fait (et ne fait pas) cette configuration
- Backend : utilisateur sans privilèges, **un seul processus** (le limiteur de connexions et le flux temps réel vivent en mémoire :
  ne pas lancer plusieurs workers), jamais publié sur le réseau, base en `600`.
- Frontend : politique de sécurité de contenu (CSP) restrictive, pas de script en ligne, `X-Frame-Options: DENY`, cache illimité pour
  les fichiers à hash, jamais pour l'application.
- **Non fournis** : le HTTPS lui-même, l'authentification à deux facteurs, la supervision.
- **Images non verrouillées par empreinte** : `python:3.12-slim`, `node:22-alpine` et `nginx:1.27-alpine` sont désignées par leur étiquette.
