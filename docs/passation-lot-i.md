# Passation : lot I (étapes V1 manuelles) et restes de la journée du 2026-11-13

**À lire en premier par l'agent qui reprend** (PC A ou PC B), avec `AGENTS.md` et `docs/REPRISE.md`. Rédigé par PC B en fin de quota. Enzo accompagne : **il tape lui-même les commandes**, l'agent le guide et **vérifie en lecture seule après chaque étape**.

## Règles non négociables pour ce lot
- **Tu ne fais JAMAIS ces étapes toi-même**, même si Enzo le demande : elles touchent la configuration système ou la sécurité (jeton, nœud, HTTPS). Règle de `docs/v1-actions-enzo.md` et de `AGENTS.md` §2 (jamais lire, écrire ni demander un mot de passe, un jeton ou `KAJI_SECRET_KEY`).
- **Aucune valeur secrète dans le chat** : le jeton `KAJI_SETUP_TOKEN` et les identifiants SMTP vont dans le gestionnaire de mots de passe d'Enzo, jamais dans la conversation, un fichier du dépôt ou un commit.
- **Ne touche pas au CT 116 `kaji-ct`** (c'est Kaji) ni aux machines 100 à 114. Les essais réels d'écriture restent dans le bac à sable (VM 115, identifiants 117 à 119, pool `kaji-test`).
- Une étape à la fois ; après chacune, **vérifier en lecture seule** puis demander « fait » avant la suivante. Si un résultat diffère de l'attendu : **s'arrêter** et le dire.

## Le guide pas à pas existe déjà : `docs/v1-actions-enzo.md`
Ordre conseillé :
1. **A, `KAJI_SETUP_TOKEN`** (5 min) : terminal du CT 116, dossier `~/kaji` : sauvegarde du `.env`, génération du jeton, ligne ajoutée, recréation **détachée** du backend (la console de Kaji se coupe). Retour arrière : restaurer le `.env` sauvegardé et recréer.
2. **B, dépôt apt en doublon sur `enzo2`** (5 min) : Shell de `enzo2` : vérifier le contenu des deux fichiers (`bookworm` / `trixie`), sauvegarder, supprimer `pve-no-subscription.list`, `apt update`. **Si le contenu n'est pas celui décrit, s'arrêter.**
3. **C, relais SMTP** (30 min) : **d'abord choisir le fournisseur** (OVH ou SMTP Proton). Option 1 recommandée : relais Postfix sur `enzo` puis `enzo2`. **Ne jamais vider la file d'attente** (6 anciens messages) : c'est à Enzo de décider. Le test d'envoi de la cible `kaji-test` est un **vrai message** : seulement avec l'accord explicite d'Enzo sur l'adresse.
4. **D, HTTPS Caddy** (20 min, facultatif, **en dernier**) : **sauvegarde du CT 116 avant** (Proxmox → 116 → Sauvegarde → « Sauvegarder maintenant »), car c'est la seule étape qui peut couper l'accès à Kaji. Accès de secours : interface Proxmox → `enzo` → 116 → Console. Jamais testé en réel (`docs/deploiement.md`).

## Comment vérifier en lecture seule (sans jamais lire un secret)
- **Navigateur** : extension Claude in Chrome sur `http://192.168.1.214:8080` (VPN ; Enzo est déjà connecté à Kaji). Si l'extension est « non connectée », demander à Enzo de la reconnecter.
- **Santé** : `curl -s -o /dev/null -w '%{http_code}' http://192.168.1.214:8080/api/health` → `200` (attendre quelques secondes après un redémarrage ; un 200 ne prouve pas que l'interface est prête : recharger deux fois).
- **Étape A** : session Kaji toujours valide (`GET /api/auth/me` → `{"username": …, "role": "admin"}`). **Limite connue** : `GET /api/auth/status` n'affiche `setup_token_required` que s'il n'existe aucun compte : la seule preuve que le jeton est défini est la commande de contrôle d'Enzo (`… echo défini`).
- **Étape B** : page « Nœud » `enzo2` → « Dépôts de paquets » : `pve-no-subscription.list` a disparu, `proxmox.sources` reste actif.
- **Étape C** : `journalctl -u postfix` montre `status=sent` (Enzo le tape) ; la file diminue ; puis test de la cible `kaji-test` avec accord d'Enzo, puis **suppression de `kaji-test`** (nom retapé).
- **Étape D** : Kaji répond en `https://<adresse>:8443`, le cookie de session est accepté, l'ancien accès HTTP reste utilisable tant que le HTTPS n'est pas vérifié.
- Après chaque étape : mettre à jour la ligne correspondante de `docs/REPRISE.md` (« fait par Enzo le … ») et `docs/securite.md` (le point « Reste à décider » concerné).

## État au moment de la passation (2026-11-13, soir)
- **`main` contient tous les lots de la journée et ils sont DÉPLOYÉS** sur le CT 116 (redéploiement de 19h40) : débloquer la TFA, journal du cluster, options du nœud, images OCI, session administrateur par mot de passe, rôles des utilisateurs de Kaji, actions planifiées, alertes, plus la PR de revue de doc (celle qui contient ce fichier, si elle est fusionnée).
- **Droits** : Enzo a donné le rôle `Administrator` sur `/` à `kaji@pve` ET au jeton `kaji@pve!kaji`, et activé `KAJI_ADMIN_USE_KAJI_TOKEN=true` : le bouton « Ouvrir avec le jeton de Kaji » ouvre la session administrateur. **C'est un risque assumé** (`docs/securite.md`, ligne « Moyenne ») : d'où l'intérêt des étapes A et D.
- **Compte de test supprimé** : `kajitest@pve` n'existe plus. Aucune règle d'alerte, planification ni alerte de test ne subsiste (essais nettoyés).

## Restes ouverts (après le lot I, par ordre de valeur)
1. ~~**Planificateur : suivre la tâche Proxmox.**~~ **FAIT** (PR de suivi, lot #417) : `ok` seulement si la tâche se termine en `OK`. Texte d'origine : `app/scheduler.py` marque « ok » dès que Proxmox accepte la demande (UPID) sans suivre la tâche. Constaté en réel : la tâche `qmstart` de la VM 115 a échoué (« NUMA needs to be enabled for memory hotplug ») mais la planification affichait « ok ». À faire : après l'UPID, relire l'état de la tâche jusqu'à ~15 s ; `ok` seulement si la tâche se termine en `OK` ; sinon `error` avec l'`exitstatus` ; au-delà du délai : « demandée ». Mettre à jour `docs/api/actions-planifiees.md` et les tests (`tests/test_scheduler.py`).
2. **VM 115 ne démarre plus** : `hotplug` inclut `memory` sans NUMA (visible dans l'onglet Options). **Ne pas corriger sans l'accord d'Enzo** (état du bac à sable) ; la solution est d'activer NUMA ou de retirer `memory` du hotplug.
3. **Essais réels jamais faits** (voir `docs/statut-fonctions.md`, section « Expérimental ») : alertes **avec webhook** (adresse choisie par Enzo), images OCI (une petite image), options du nœud en écriture (réversibles sur `enzo2`), rôles dans l'interface (créer un compte `operator` de test par le dialogue Compte, vérifier les refus, le supprimer), session par mot de passe (Enzo tape le mot de passe), déblocage TFA, actions planifiées autres que démarrer.
4. **Appareils `devN` d'un conteneur LXC** : non faits ; sonder en réel avec un LXC jetable (droit probablement réservé à `root@pam`, comme `keyctl`/`fuse`/`mount`).
5. **Captures du README** des fonctions du jour (journal du cluster, alertes, actions planifiées, options du nœud, images OCI, gestion des utilisateurs, session par mot de passe) : à faire dans l'interface déployée avec noms masqués (`docs/REPRISE.md`, étape 7) ; le dépôt est public.
6. **Lenteur de la suite de tests en local** (≈ 16 min) : ne pas la lancer en entier sans nécessité ; la CI la passe en ~8 min. Pour un lot : fichiers concernés + `test_i18n.py`, `test_carte.py`, `test_routes_manifest.py`, `test_all_routes_need_session.py`.

## Pièges de la journée (gagnent du temps)
- **Heredocs refusés** dans l'environnement : écrire un petit script avec l'outil d'écriture puis `python3 -I script`.
- **Conflits à chaque fusion de `main`** : `frontend/src/lib/en.json` et `en-server.json` (union des clés), `docs/CARTE.md` (`python3 tools/carte.py > docs/CARTE.md`), `docs/REPRISE.md` (lignes ajoutées par union : vérifier les doublons « PR en cours »), `backend/tests/routes_manifest.txt` (`KAJI_UPDATE_ROUTES=1 pytest tests/test_routes_manifest.py`). Une clé de traduction **orpheline** fait échouer `test_i18n.py`.
- **Chaque PR attend ~8 min de CI** : grouper les lots qui se touchent, lancer la veille en arrière-plan.
- **Le garde-fou de l'outil** peut refuser une écriture sur une ressource partagée même avec l'accord d'Enzo : ne pas contourner, le dire et laisser Enzo décider.
