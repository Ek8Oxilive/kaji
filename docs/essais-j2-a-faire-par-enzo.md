# Essais du jalon J2 : ce qui est vu en réel, et ce qu'il reste à voir par le propriétaire

**Date des essais : 2026-11-15**, sur le Kaji déployé (CT 116, `https://kaji.home`), redéployé avec `main` à `97e6a17` (PR #473 à #476). Les essais ont été faits par PC B dans la session ouverte du propriétaire, avec des comptes jetables, puis tout a été nettoyé (il ne reste que le compte `admin`, aucun utilisateur ni jeton Proxmox d'essai, session administrateur fermée).

## Vu en réel (par PC B)
| Fonction | Ce qui a été vu |
|---|---|
| **Jeton Proxmox à expiration obligatoire** (#442) | Utilisateur Proxmox jetable `kajitest-exp@pve` créé, session administrateur par le jeton de Kaji. Création d'un jeton **sans expiration, avec `expire=0`, avec une date passée, avec une date à plus d'un an : 422, audités, avant tout appel à Proxmox** ; avec 30 jours : **201**, jeton listé, privilèges séparés, expiration posée. **Le secret n'apparaît ni dans la liste, ni dans l'audit, ni dans l'état de la session administrateur.** Jeton révoqué, utilisateur supprimé, session fermée. |
| **Périmètre d'un compte, côté administrateur** (#447) | Compte Kaji jetable créé (mot de passe aléatoire **jamais utilisé**). Refus : liste vide, `true`, `"115"`, `0`, doublon, connexion inconnue (422), vers un administrateur (409), rien d'écrit. Périmètre {connexion 1 : VM 115} enregistré, signalé par la liste (`scoped`), ton compte reste non restreint. Retrait sans confirmation 400, mauvais nom 400, valide 200, second retrait 409. Audit présent. Compte supprimé. |
| **Retrait du TOTP d'un autre compte** (#444) | 409 pour un compte qui n'en a pas, 409 pour soi-même, 404 pour un compte inconnu, audités. |
| **Déploiement** | Nouvelle version en ligne 40 s après le lancement ; `/api/health` 200 ; `http://kaji.home` renvoie vers HTTPS (308). |

## Pourquoi le reste te revient
Un agent **ne tape jamais de mot de passe** sur ton Kaji réel, même celui d'un compte jetable qu'il aurait créé. Tout ce qui demande de **se connecter** avec un compte est donc à faire par toi. Et l'export de l'audit exige de modifier le `.env` du CT 116 (réglage système) : c'est à toi aussi.

## À faire par toi (15 minutes), dans l'ordre

### 1. Double authentification (#444), sur un compte de TEST (pas le tien)
1. **Compte** → **Gérer les utilisateurs…** → crée `test-totp`, rôle **Lecture seule**, un mot de passe de 12 caractères au moins.
2. Ouvre une **fenêtre privée**, connecte-toi à `https://kaji.home` avec `test-totp`.
3. **Compte** → **Double authentification…** → mot de passe → **Activer**. Saisis la clé dans ton application d'authentification, tape le code, **note les codes de secours**.
4. Déconnecte-toi, reconnecte-toi : le mot de passe seul doit afficher **« Double authentification »** ; un mauvais code doit répondre « Code invalide » ; le bon code ouvre la session.
5. Reconnecte-toi avec **un code de secours** (il ne marchera qu'une fois).
6. Dans ta session d'administrateur : **Gérer les utilisateurs…** → `test-totp` porte le badge **2FA** ; **Retirer la 2FA…** (nom retapé) la retire.
7. Supprime `test-totp`.

### 2. Compte restreint à un groupe de machines (#447)
1. Crée `test-perimetre`, rôle **Lecture seule**.
2. **Gérer les utilisateurs…** → **Périmètre…** de `test-perimetre` : coche **seulement la VM 115** → **Enregistrer le périmètre**.
3. Fenêtre privée, connecte-toi avec `test-perimetre` : le tableau de bord doit montrer **la seule VM 115**, sans le cluster, sans le menu Stockage, Réseau, Accès… ; la page de la VM 115 s'ouvre ; ouvre à la main `https://kaji.home/#/storage` ou la page d'une autre machine : **refus ou retour au tableau de bord**.
4. Dis-moi ce que tu constates (surtout les **onglets de la VM 115** qui s'affichent en erreur : ils appellent parfois des routes globales ; c'est une limite documentée dans `docs/api/roles-perimetre.md`).
5. Supprime `test-perimetre`.

### 3. Session administrateur par mot de passe (opérations interdites aux jetons, #442)
**Compte** (page « Accès ») → panneau « Mode administrateur » → **Ouvrir avec un mot de passe…** avec un compte Proxmox qui a le droit d'écrire la double authentification d'un utilisateur Proxmox **jetable** : tu tapes le mot de passe (jamais un agent). Ouvre **Double authentification…** d'un utilisateur Proxmox de test et ajoute-lui des codes de secours. Supprime l'utilisateur de test ensuite.

### 4. Export de l'audit (#445)
Dans le terminal du CT 116, dans `~/kaji` :
```
echo 'KAJI_AUDIT_FILE=/data/audit.jsonl' >> .env
nohup sh -c 'cd ~/kaji && docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --force-recreate backend' > /root/audit.log 2>&1 &
```
Puis, après une minute : `docker compose -f docker-compose.yml -f docker-compose.tls.yml exec -T backend tail -n 3 /data/audit.jsonl` : trois lignes JSON (`{"ts":…,"service":"kaji",…}`). Colle-les-moi (elles ne contiennent pas de secret) et je vérifie le format. **Retour arrière** : retire la ligne du `.env` et recrée de la même façon.

### 5. Journal de Proxmox nominatif : le jeton personnel (#440)
C'est LE critère de l'option A du cadrage : une action d'une personne doit apparaître **sous son nom** chez Proxmox. Jamais vu en réel.
1. Dans Proxmox, crée un utilisateur de test `kajitest-perso@pve` et, pour lui, un jeton `essai` **avec séparation de privilèges** et une expiration (30 jours). Donne au jeton le rôle `PVEAuditor` sur `/vms/115` (lecture seule) : il ne peut **rien modifier**.
2. Dans Kaji, avec ton compte (ou un compte de test) : **Compte** → **Mon jeton Proxmox…** → `kajitest-perso@pve!essai`, colle le secret **toi-même** (aucun agent ne saisit un jeton), expiration. Kaji le vérifie auprès de Proxmox avant de le garder.
3. Ouvre la VM 115, onglet **Matériel** ou **Options** (lecture) : l'action part avec ton jeton. Dans Proxmox → **Datacenter** → **Tâches** ou le journal d'accès du nœud, l'utilisateur de la requête doit être `kajitest-perso@pve!essai`, **pas** `kaji@pve!kaji`.
4. Retire le jeton de Kaji (« Mon jeton Proxmox… » → retirer), puis supprime le jeton et l'utilisateur dans Proxmox.
Dis-moi ce que tu vois dans le journal : c'est la preuve attendue.

### 6. Jeton de service du planificateur (#441)
Dans Proxmox, un jeton `kajitest-service@pve!svc` à privilèges séparés avec **seulement** les droits que `docs/api/jeton-service.md` liste pour le planificateur et les alertes. Dans Kaji, enregistre-le comme jeton de service de la connexion (la page indique les droits manquants). Crée une action planifiée **sur la VM 115** (un snapshot dans 2 minutes), vois-la s'exécuter, puis supprime l'action. Vérifie ensuite qu'une écriture hors de ces droits est **refusée**. Retire le jeton de service et supprime le jeton et l'utilisateur dans Proxmox.

## Ce que je fais ensuite
Quand tu me dis « fait », je lis l'état en lecture seule (liste des comptes, audit, tickets) et je ferme les tickets #442, #444, #445 et #447 si leurs critères de sortie sont remplis.
