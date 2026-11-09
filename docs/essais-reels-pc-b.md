# Essais réels des lots PC B (#164, #146, #147)

> À exécuter par une session **au premier plan** avec l'extension Claude in Chrome (`/chrome`) connectée à Kaji (`http://192.168.1.214:8080`, VPN).
> Phrase de départ : « Lis `docs/REPRISE.md`, `AGENTS.md` et `docs/essais-reels-pc-b.md`, puis fais ces essais et reporte les résultats. »
> Les lots sont **fusionnés mais jamais validés en réel** (PR #188, #191, #195). Chaque case ci-dessous dit quoi faire, le résultat attendu, et quoi noter.

## Règles (non négociables)
- **Bac à sable seulement** : pool `kaji-test`, VM **115** `kaji-sandbox` (nœud `enzo`, arrêtée), identifiants **117, 118, 119** pour des machines jetables.
- **Jamais** le CT **116** `kaji-ct` (c'est Kaji), ni les machines **100 à 114**. Aucune écriture réseau, pare-feu, SDN, HA, ni de mot de passe / token demandé ou écrit.
- **Une écriture à la fois**, état relu après chaque étape. Tout doit être **revenu à l'identique à la fin** : 17 machines, aucune machine 117 à 119, pas de modèle Alpine ni de fichier d'essai restant (sauf décision d'Enzo).
- En cas de résultat inattendu : **s'arrêter, nettoyer, noter**. Ne pas contourner un refus.
- Noter pour chaque essai : ✅ comme prévu / ❌ écart (copier le message exact, sans secret) / ⏭️ non fait (raison).

## 0. Préparation (lecture seule)
1. Ouvrir Kaji, vérifier la version déployée : `main` doit contenir #188, #191, #195. Sinon **redéployer** d'abord (console du CT 116, commande détachée de `docs/REPRISE.md`), puis relire `/root/redeploy.log`.
2. Noter l'état de départ : nombre de machines (attendu 17), VM 115 arrêtée, stockages `local` des nœuds `enzo` et `enzo2`, rôle du token (`docs/api/acces.md`) : droits `VM.PowerMgmt`, `VM.Allocate`, `VM.Clone`, `Datastore.AllocateTemplate` sur `local`, sinon l'essai concerné donnera « Droits insuffisants » (noter, ne pas modifier les droits).

## A. #147 : télécharger un modèle de conteneur (à faire en premier : il fournit le modèle du B)
Page Stockage → tiroir de `local` du nœud `enzo2` → « Télécharger un modèle de conteneur ».
- [ ] **Catalogue** : la liste s'affiche (sections `system`, `turnkeylinux`, `mail`), la recherche « alpine » filtre. Noter si la liste est vide (nœud sans Internet).
- [ ] **Téléchargement** : prendre le plus petit modèle Alpine. Barre de progression, toast de succès, le modèle apparaît dans le tiroir du stockage **et** passe à « Déjà présent ». Noter la durée et le nom exact du fichier (doit être `local:vztmpl/<nom du catalogue>`).
- [ ] **409** : retélécharger le même modèle → bouton absent (« Déjà présent ») ; côté API, `POST …/nodes/enzo2/aplinfo` avec le même nom → 409, **aucune tâche** créée dans le journal de Proxmox.
- [ ] **422 hors catalogue** (API, depuis la console du navigateur ou l'interface si possible) : `debian-99`, `../x` → 422, aucune tâche. Idem stockage inexistant ou qui n'accepte pas `vztmpl` (`local-lvm`) → 422.
- [ ] **Assistant LXC** : « Nouveau conteneur », étape Modèle, nœud `enzo2` → le bouton « Télécharger un modèle… » ouvre le même dialogue ; le modèle téléchargé apparaît dans la liste après fermeture (noter s'il faut rouvrir l'assistant : il n'est pas sélectionné automatiquement).
- [ ] **Audit** : `template-download` en `started` / `error` selon les cas, sans secret.

## B. #164 : réglages LXC réservés à root@pam (conteneur jetable 118)
Créer un LXC **118** sur `enzo2` depuis le modèle Alpine du A (pool `kaji-test`, 128 Mo, disque 1 Go, `local-lvm`, **non démarré**).
- [ ] Onglet Options du LXC : **FUSE, keyctl et les montages sont en lecture seule** avec la note « Modifiable seulement dans Proxmox (droit root@pam) » ; nesting modifiable ; « Valeur par défaut » absent pour `features` seulement si keyctl, fuse ou mount sont déjà actifs.
- [ ] **nesting** : activer puis enregistrer → succès ; relire (la case reste cochée), puis remettre comme avant.
- [ ] **keyctl / fuse refusés** (API : `PATCH …/lxc/118/options` avec `{"features":{"keyctl":true}}`, puis `{"features":{"fuse":true}}`, `{"features":{"mount":["nfs"]}}` : les trois sous `features`, sinon 400 « Aucune modification demandée ») → **403** avec le message exact « Proxmox réserve keyctl, fuse et mount à root@pam : le token de Kaji ne peut pas les modifier. Fais-le dans l'interface de Proxmox. ». Noter **pour chacun** : 403 attendu (`mount` n'a jamais été observé).
- [ ] **Écriture combinée** : `{"onboot":true,"timezone":"Europe/Paris","features":{"keyctl":true}}` → 403 **et rien d'appliqué** (relire `onboot` et `timezone`).
- [ ] **Écritures sans ces réglages** : `onboot`, `tty`, `cmode`, `timezone`, `protection` passent encore, puis tout remis.
- [ ] **Cas du relecteur (optionnel, demande l'accord d'Enzo)** : dans l'interface de **Proxmox** (root@pam), activer `keyctl` sur le LXC 118 ; revenir dans Kaji et changer **nesting seul** → noter : Proxmox l'accepte-t-il (200) ou refuse-t-il (403 → message root@pam attendu) ? Puis `clear: ["features"]` → idem. Remettre `features` comme au départ dans Proxmox.
- [ ] **Audit** : `options` en erreur avec le message fixe.
- [ ] **Nettoyage** : supprimer le LXC 118 (arrêté, nom retapé).

## C. #146 : alimentation de la VM 115 et modèle
VM 115 (sans système : pas d'agent invité). Page Machine de la VM 115.
- [ ] **État initial** : arrêtée → seul « Convertir en modèle… » et « Démarrer » visibles ; **Suspendre / Hiberner / Réinitialiser absents**.
- [ ] **Démarrer** la 115. Les boutons **Suspendre, Hiberner, Réinitialiser** apparaissent (après la première lecture de l'état).
- [ ] **Suspendre** → la VM passe en pause ; **Reprendre** apparaît (et Suspendre / Hiberner / Réinitialiser disparaissent) ; `GET …/qemu/115/power` renvoie `paused: true`. Noter les valeurs réelles de `status` et `qmpstatus` (documentation : `paused` / `suspended`, jamais observées).
- [ ] **Reprendre** → de nouveau en marche.
- [ ] **Réinitialiser** (confirmation) → la VM redémarre ; noter que l'état reste « en marche ».
- [ ] **Sans `confirm`** (API) : `POST …/qemu/115/reset` → 400 et aucune tâche ; `hibernate` idem.
- [ ] **Hibernation** : essayer `hibernate` avec confirmation. **Attendu : refus probable** (pas d'agent invité). Noter le message exact. **Ne pas insister**. Si elle réussit : la VM est arrêtée avec un verrou `suspended` ; vérifier que « Convertir en modèle » est refusé (409 « verrouillée ») puis la **redémarrer** pour consommer l'état avant de continuer.
- [ ] **Arrêt forcé** de la 115 pour revenir à l'arrêt.
- [ ] **Refus de reset sur une VM arrêtée** (API) → 409, aucune tâche.
- [ ] **Clone** : cloner 115 en **117** (complet, pool `kaji-test`). Attendre la fin.
- [ ] **Refus de conversion** sur la 117, un à la fois, **aucune tâche créée à chaque fois** : sans `confirm` → 400 ; mauvais nom (`Kaji-Sandbox-Clone`, vide) → 400 ; machine en marche (démarrer la 117 puis l'arrêter ensuite) → 409.
- [ ] **Conversion** de la 117 (nom retapé exactement) → tâche réussie. Vérifier : badge « Modèle », **démarrage refusé**, disque renommé `base-117-…` dans Proxmox (à lire seulement). **Irréversible** : ne pas la refaire sur une autre machine.
- [ ] **Déjà modèle** : reconvertir la 117 → 409, aucune tâche.
- [ ] **LXC modèle** (sur un LXC jetable **119**, créé comme au B, arrêté) : convertir (nom retapé) → l'**interface ne doit pas afficher d'erreur** (Proxmox ne renvoie pas de tâche : `upid` nul) ; le conteneur devient un modèle ; vérifier dans Proxmox.
- [ ] **Machine de `KAJI_PROTECTED_VMIDS`** (105, 108, 116) : **ne pas essayer en réel** (couvert par les tests).
- [ ] **Audit** : `reset`, `suspend`, `resume`, `hibernate`, `guest-template`, refus compris, sans secret.
- [ ] **Nettoyage** : supprimer les modèles 117 et 119 (nom retapé), vérifier que le stockage ne garde pas de disque `base-…` ; la 115 est arrêtée et inchangée.

## D. Nettoyage final (obligatoire)
- [ ] Supprimer le modèle Alpine téléchargé : route `DELETE …/storage/local/files/vztmpl/<nom>?confirm=true&typed=<nom>` (`docs/api/volumes.md`), sur `enzo2`, sauf décision contraire d'Enzo.
- [ ] Machines : **17**, aucune 117 à 119, VM 115 arrêtée et identique (disques, options, pare-feu vide).
- [ ] Journal d'audit : relire les entrées créées, aucune ne contient de secret.

## E. Compte rendu
Mettre à jour `docs/REPRISE.md` (section « État » : ce qui est **validé en réel**, avec la date, et les écarts trouvés) et passer les lignes concernées de `docs/parite-proxmox.md` de 🟡 à ✅. Pour chaque écart : ticket `agent:pc-b` (message exact, étapes, attendu), comme #164. Une PR « docs + corrections » avec la liste honnête de ce qui n'a pas pu être fait.

Écarts connus à surveiller (non vérifiés) : états `qmpstatus` des VM en pause ; refus de `mount` ; nom de fichier des modèles téléchargés (`volid`) ; liste du catalogue tronquée à 300 entrées ; bouton « Convertir en modèle… » visible même pour une machine protégée (le serveur refuse) ; boutons d'alimentation absents du menu des cartes de la liste.

## Résultats (2026-11-09, PC A, Claude in Chrome sur Kaji, cluster revenu à l'identique)
Préparation : le déploiement n'avait **pas** #195 (`POST …/aplinfo` : 404) ; redéployé par la console du CT 116 (`main` 6f74226, PR #199) avec l'accord d'Enzo.
Légende : ✅ comme prévu · ❌ écart (ticket) · ⏭️ non fait.

| Essai | Résultat |
|---|---|
| A. Catalogue, recherche, sections | ✅ 136 entrées, sections `mail` / `system` / `turnkeylinux` ; ❌ modèle `arm64` proposé sur un nœud amd64 (#205) |
| A. Téléchargement Alpine | ✅ 2 s, 3 450 920 octets, `volid` = nom du catalogue, « Déjà présent » |
| A. 409, 422 (4 cas), aucune tâche | ✅ messages exacts dans `docs/api/modeles-lxc.md` |
| A. Assistant LXC | ✅ bouton ouvre le dialogue ; modèle listé, non sélectionné automatiquement |
| A. Audit | ✅ `template-download` started / error, sans secret |
| B. Lecture seule FUSE / keyctl / montages, nesting | ✅ (nesting : coché, enregistré, relu, retiré par « Valeur par défaut ») |
| B. keyctl, fuse, **mount** refusés | ✅ 403 au message exact pour les trois (`mount` observé pour la première fois) ; corps du doc corrigé (sous `features`) |
| B. Écriture combinée | ✅ 403, rien appliqué |
| B. `onboot`, `tty`, `cmode`, `timezone`, `protection` | ✅ passent, puis `clear` (protection : 400 sans `confirm`, 200 avec) |
| B. Cas du relecteur (`keyctl` activé dans Proxmox) | ⏭️ accord d'Enzo et accès `root@pam` requis |
| B. Audit, nettoyage 118 | ✅ |
| C. États des boutons (arrêtée, en marche) | ✅ |
| C. Suspendre | ✅ `/power` : `status: running`, `qmpstatus: paused` ; ❌ `/guests` : `paused`, aucun bouton, **Reprendre introuvable** (#201), reprise par l'API |
| C. Reprendre, réinitialiser, refus sans `confirm`, refus sur VM arrêtée | ✅ |
| C. Hibernation | ✅ **réussie** (pas de refus faute d'agent) ; VM redémarrée pour consommer l'état |
| C. Refus de conversion sur verrou `suspended` | ⏭️ non essayé (risque irréversible sur la 115 ; verrou non exposé par Kaji) |
| C. Clone 117, refus de conversion (5 cas + en marche), reconversion 409 | ✅ aucune tâche à chaque refus |
| C. Conversion VM 117 | ✅ `qmtemplate` ok, `base-117-disk-0`, badge « Modèle » ; ❌ boutons de la fenêtre masqués (#202), clavier seulement ; ❌ démarrage non refusé par Kaji (#204) |
| C. LXC modèle 119 | ✅ pas d'erreur, `base-119-disk-0`, tâche `vztemplate` ; cosmétique #206 |
| C. Machines protégées 105 / 108 / 116, bouton « Convertir » sur une machine protégée, menu des cartes, catalogue tronqué à 300 | ⏭️ non essayés (136 entrées seulement) |
| C. Nettoyage 117 et 119 | ✅ par l'API : ❌ pas de bouton « Supprimer » sur un modèle (#203) |
| D. Alpine supprimé, 17 machines, 115 arrêtée et identique, audit sans secret | ✅ (options et pare-feu de la 115 inchangés, aucun volume résiduel) |

Remarques : un 502 de nginx (~8 s) et des entrées d'audit `datacenter-options` et `console-open` du CT 116 qui ne viennent pas de cette session montrent qu'un autre agent ou Enzo travaillait en parallèle sur Kaji. Le champ « description » de la VM 115 (« jamais démarrée ») n'a pas été modifié : il est désormais inexact (démarrée pendant l'essai C).
