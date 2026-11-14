# Runbook d'exploitation de Kaji

Pour la personne qui **fait tourner** Kaji (pas celle qui le développe). Chaque procédure renvoie vers la documentation détaillée ; ce document dit **quoi faire, dans quel ordre, et comment vérifier**.

> **Statut honnête (jalon J4).** Ce runbook a été écrit à partir du code et des tests, **jamais rejoué de bout en bout par un exploitant autre que son auteur** : c'est un critère de sortie de J4 (#461, #462). Les commandes marquées « non essayé » n'ont jamais tourné sur un vrai Docker. Si une étape ne marche pas comme écrit, ouvre un ticket avec la commande et le message.

## 0. Ce qu'il faut savoir avant tout
- Kaji = 3 conteneurs (`backend`, `web`, et `tls` si HTTPS) sur **une** machine, **un seul processus backend** (jamais deux instances : planificateur et alertes seraient doublés).
- **Deux choses se sauvegardent ensemble** : la base (volume `kaji-data`) **et** les clés : `KAJI_SECRET_KEY` (dans `.env`) et, si les jetons personnels ou de service sont utilisés, **`KAJI_TOKEN_KEY`** (de préférence un fichier à part). Une base sans ses clés est inutilisable.
- Accès de secours qui ne passe **pas** par Kaji : interface Proxmox → machine qui héberge Kaji → Console. La console de Kaji se coupe à chaque redémarrage de Kaji.

## 1. Supervision de Kaji lui-même
Kaji n'expose **pas** de métriques ni de tableau de bord de sa propre santé : voici ce qui existe.

| Contrôle | Commande | Attendu |
|---|---|---|
| Santé | `curl -sk https://<adresse>/api/health` | `200` (un 200 ne prouve pas que l'interface est prête : recharger deux fois) |
| Conteneurs | `docker compose ps` | `backend` et `web` en « healthy » / « running » (et `tls` si HTTPS) |
| Journaux | `docker compose logs --tail 200 backend` | pas de trace d'erreur répétée ; aucun secret (garanti par des tests) |
| Version de la base | `docker compose exec backend python -m app.migrations status` | `pending: []` |
| Contenu de la base | `docker compose exec backend python -m app.admin_cli verify` | « Résultat : OK », jetons et webhooks « déchiffrés : n/n » |
| Disque | `docker system df` ; taille du volume `kaji-data` | la base grossit surtout avec l'audit (`KAJI_AUDIT_RETENTION_DAYS`) |
| Sauvegardes | date du dernier fichier de `tools/backup.sh` | moins de 24 h (à vous de le programmer : rien n'est automatique) |
| Échéances des jetons | « Compte » → « Mon jeton Proxmox » ; page Connexions → « Jeton de service… » | aucun « Expire bientôt » / « Expiré » / « Refusé par Proxmox » |
| Mises à jour d'images | `tools/image_digests.sh` | « à jour » (sinon `docs/images-et-versions.md`) |

**Rien n'avertit tout seul** : pas d'alerte sur l'échéance d'un jeton, sur un échec de sauvegarde ni sur une image périmée. À programmer chez vous (cron, supervision existante).

## 2. Rythme conseillé
- **Chaque jour** : sauvegarde (`tools/backup.sh`) ; santé.
- **Chaque semaine** : relire les PR Dependabot ; regarder les échéances de jetons.
- **Chaque mois** : `tools/image_digests.sh` (les images épinglées ne reçoivent pas de correctif tant que l'empreinte ne change pas) ; `verify` ; essai de restauration sur une machine de test.
- **Chaque version** : `docs/images-et-versions.md` (publication), mise à jour (§ 5).
- **Chaque année** (ou après un départ de la personne qui connaît les clés) : rotation des secrets (§ 3).

## 3. Rotation des secrets
Quel secret, quel effet, quelle procédure.

| Secret | Où | Effet d'un changement | Procédure |
|---|---|---|---|
| `KAJI_SECRET_KEY` | `.env` | **invalide toutes les sessions** ; les jetons des connexions et les webhooks sont ré-chiffrés par `rotate-secret-key` | § 3.1 |
| `KAJI_TOKEN_KEY` | fichier ou `.env` | rien si la rotation est faite dans les règles | `docs/deploiement.md`, « Rotation de `KAJI_TOKEN_KEY` » |
| Jeton partagé d'une connexion | Proxmox + page Connexions | les tâches de fond sans jeton de service et les utilisateurs sans jeton personnel s'arrêtent le temps du changement | § 3.2 |
| Jeton personnel d'un utilisateur | Proxmox + « Mon jeton Proxmox » | seul cet utilisateur est concerné | il en crée un nouveau, l'enregistre ; Kaji refuse l'expiré |
| Jeton de service | Proxmox + page Connexions | planificateur et alertes concernés | un administrateur en enregistre un nouveau (mêmes droits limités) |
| `KAJI_SETUP_TOKEN` | `.env` | aucun (n'agit que tant qu'aucun compte n'existe) | le changer librement |
| Mot de passe d'un compte de Kaji | « Compte » ou `admin_cli reset-password` | les sessions du compte sont révoquées | `docs/deploiement.md`, « Mot de passe perdu » |

### 3.1 Rotation de `KAJI_SECRET_KEY`
`KAJI_SECRET_KEY` signe les sessions et chiffre le jeton partagé de chaque connexion et les webhooks d'alerte. La changer **sans** la commande ci-dessous oblige à ressaisir chaque connexion et chaque webhook.
1. `tools/backup.sh` ; note l'**ancienne** clé (les anciennes sauvegardes sont chiffrées avec elle).
2. Génère la nouvelle : `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Dans `.env` : **`KAJI_SECRET_KEY` = la nouvelle**, **`KAJI_SECRET_KEY_PREVIOUS` = l'ancienne**.
3. Applique : `docker compose up -d --force-recreate backend` (un simple `restart` ne relit pas `.env`).
4. `docker compose exec backend python -m app.admin_cli rotate-secret-key --yes` : ré-chiffre **tout ou rien**, relit chaque secret avec la seule nouvelle clé, rejouable, n'affiche que des nombres. Il refuse (sans rien modifier) si un secret n'est lisible par aucune des deux clés.
5. Retire `KAJI_SECRET_KEY_PREVIOUS` de `.env` ; `docker compose up -d --force-recreate backend` ; `docker compose exec backend python -m app.admin_cli verify` : « jetons déchiffrés : n/n », « webhooks déchiffrés : n/n ».
6. **Toutes les sessions sont tombées** (elles sont signées avec la clé) : tout le monde se reconnecte. Sauvegarde le nouveau `.env`/la nouvelle clé **à part**.
Essayé sur de vraies bases SQLite (`backend/tests/test_secret_rotation.py`, 11 mutations tuées) ; **jamais avec le vrai Docker**.

### 3.2 Remplacer le jeton partagé d'une connexion
1. Dans Proxmox : créer un **nouveau** jeton (mêmes droits, privilèges séparés, expiration).
2. Dans Kaji : page « Connexions » → modifier la connexion → nouveau secret (et identifiant s'il change) → « Tester ».
3. Vérifier l'audit et un appel réel (tableau de bord).
4. **Puis seulement** supprimer l'ancien jeton dans Proxmox.

## 4. Restauration
`docs/deploiement.md`, « Sauvegarde et restauration » : `tools/restore.sh FICHIER.db` après avoir remis **les mêmes clés**. Le script refuse une sauvegarde que les clés actuelles ne lisent pas, garde l'ancienne base à côté, puis contrôle.
**À vérifier après** : connexion, page « Connexions » → « Tester », jetons personnels et de service « actifs », actions planifiées et alertes présentes.
**Non essayé avec le vrai Docker** (ticket #429).

## 5. Mise à jour et retour arrière
1. `tools/backup.sh` (et noter les clés).
2. `git fetch --tags && git checkout <étiquette>` ; relire `CHANGELOG.md` (rubriques « Sécurité » et « Modifié »).
3. Reconstruire avec les **deux** fichiers Compose si le HTTPS est actif : `docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build`.
4. `docker compose exec backend python -m app.migrations status` : `pending: []`, puis `verify`.
5. **Retour arrière** : `git checkout <ancienne étiquette>` + `tools/restore.sh` avec la sauvegarde de l'étape 1 (une base plus récente que le code est refusée au démarrage).
La CI migre chaque base d'exemple de version vers le code courant (`backend/tests/test_upgrade_from_versions.py`) ; **la procédure complète n'a pas été essayée avec le vrai Docker** (#456).

## 6. Incidents
Dans tous les cas : **noter l'heure, ne rien supprimer, garder l'audit** (`/api/audit`, `docker compose logs`).

### 6.1 Un jeton Proxmox a fuité (ou on le soupçonne)
1. **Dans Proxmox** : révoquer le jeton (Datacenter → Permissions → API Tokens). C'est l'action qui compte : la révocation est immédiate, quoi qu'en dise Kaji.
2. Lire le **journal de Proxmox** pour ce jeton (ce qu'il a fait, depuis quelle adresse) ; jeton personnel : Proxmox le nomme.
3. Dans Kaji : l'utilisateur ou l'administrateur enregistre un nouveau jeton. Un jeton révoqué apparaît « Refusé par Proxmox » et Kaji cesse de l'utiliser.

### 6.2 Kaji lui-même est peut-être compromis (base ou machine copiée, accès non autorisé)
Kaji détient des jetons : **les considérer tous comme compromis**.
1. Isoler : `docker compose stop` (ou couper l'accès réseau).
2. **Révoquer dans Proxmox** : le jeton partagé de chaque connexion, tous les jetons personnels, les jetons de service. Vérifier les droits des comptes concernés.
3. Changer **toutes** les clés (`KAJI_SECRET_KEY`, `KAJI_TOKEN_KEY`) et les mots de passe des comptes de Kaji (`admin_cli reset-password`).
4. Relire le journal de Proxmox et l'audit de Kaji sur la période.
5. Reconstruire depuis une étiquette connue (pas depuis la machine suspecte) ; restaurer la base **seulement** si elle est saine ; ré-enregistrer tous les jetons.
6. Signaler la faille : `SECURITY.md`.

### 6.3 La clé est perdue
- `KAJI_SECRET_KEY` perdue (donc pas d'ancienne clé à fournir à `rotate-secret-key`) : sessions invalides, **connexions et webhooks à ressaisir** ; comptes, rôles, audit lisibles. Restauration refusée par `tools/restore.sh` (par prudence) : utiliser la méthode « copie du volume » de `docs/deploiement.md`.
- `KAJI_TOKEN_KEY` perdue : jetons personnels et de service à ré-enregistrer ; le reste fonctionne.

### 6.4 Base corrompue ou ne démarre plus
`docker compose logs backend` ; `verify` ; restaurer la dernière bonne sauvegarde (`tools/restore.sh`). Si le message dit « base plus récente que le code » : on a redescendu de version, remettre le code de la bonne étiquette.

### 6.5 Plus de connexion possible (mot de passe perdu, compte bloqué)
`docker compose exec backend python -m app.admin_cli reset-password --user <nom>`. Trop d'échecs : attendre 5 minutes (le blocage est par adresse, persistant) ou voir si un proxy fait partager une adresse à tous les clients (`docs/deploiement.md`).

### 6.6 Proxmox ne répond pas ou son certificat a changé
Kaji affiche « Proxmox injoignable » / « certificat différent » sans rien casser. Certificat renouvelé : page « Connexions » → « Épingler le certificat… » après **comparaison de l'empreinte** avec celle du nœud.

### 6.7 Une faille est annoncée dans une image de base ou une dépendance
`tools/image_digests.sh` ; Dependabot ; reconstruire (`docker compose build --no-cache`) ; consulter `CHANGELOG.md`.

## 7. Ce qui manque (et qui reste à faire)
- Aucune alerte automatique sur : échéance d'un jeton, échec de sauvegarde, image périmée.
- Aucune procédure ci-dessus n'a été rejouée par un tiers (critère de sortie de J4).
