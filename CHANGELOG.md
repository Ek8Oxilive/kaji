# Journal des changements

Tous les changements notables de Kaji. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions étiquetées `vMAJEUR.MINEUR.CORRECTIF` (`-rcN` pour une version candidate). Les numéros `#N` sont ceux des pull requests du dépôt.

**Statut de la 1.0.0** : `v1.0.0-rc1` est une **version candidate pour un lab interne non exposé**, pas une version de production. Ce qui est « validé en réel » et ce qui reste « expérimental » est dans `docs/statut-fonctions.md` ; ce qui sépare ce lab d'une production en entreprise est dans `docs/cadrage-prod-entreprise.md` (jalons J1 à J4).

## [Non publié]

### Ajouté
- Guide « Installer Kaji en lab » (`docs/installation-lab.md`) et test qui le garde aligné sur les droits Proxmox, `.env.example` et les fichiers Docker Compose (#430).
- `SECURITY.md` (signalement d'une vulnérabilité, versions suivies) et ce `CHANGELOG.md` (#426).
- **Jetons Proxmox personnels** (option A du cadrage, #440) : chaque utilisateur de Kaji enregistre son propre jeton par connexion (« Compte » → « Mon jeton Proxmox ») ; Proxmox applique ses droits et nomme la personne dans son journal. Privilèges séparés et expiration exigés (relus chez Proxmox quand c'est possible), jamais `root@pam` ni le jeton partagé, chiffrés par une **clé séparée** `KAJI_TOKEN_KEY` (ou fichier), rotation `rotate-token-key`, contrôle par `verify` et `restore`, option `KAJI_REQUIRE_USER_TOKEN`, flux temps réel cloisonné par utilisateur. **Pas encore essayé en réel.**

- **Jeton de service** du planificateur et des alertes (#441) : un jeton par connexion, limité à six privilèges (jamais Administrator, vérifié chez Proxmox avec le jeton lui-même, refusé sinon), chiffré par la clé séparée ; `KAJI_REQUIRE_SERVICE_TOKEN` ; page Connexions → « Jeton de service… ». **Pas encore essayé en réel.**

### Modifié
- Images de base Docker (`python`, `node`, `nginx`, `caddy`) **épinglées par empreinte** ; script `tools/image_digests.sh` pour les vérifier ou les mettre à jour, Dependabot pour les écosystèmes `docker` et `docker-compose`, et étape de CI qui tire l'image Caddy ; procédure de publication d'une version dans `docs/images-et-versions.md` (#427).

- Test de mise à jour entre versions : bases d'exemple produites par le code réel de `v1.0.0-rc1` et de deux anciens états du schéma, migrées vers le code courant en CI sans perte de valeur ; une base d'exemple par étiquette Git exigée, produite par `tools/snapshot_db.py` (#456).

### Corrigé
- `docs/deploiement.md` : le HTTPS fourni par Caddy écoute sur le port 443, pas 8443 (#430).

## [1.0.0-rc1] - 2026-11-14

Première version étiquetée. Tout ce qui existe est listé ci-dessous, par thème ; chaque fonction est décrite dans `docs/api/<fonction>.md`, et son niveau de validation dans `docs/statut-fonctions.md`. Entre le 2026-11-06 (première PR) et le 2026-11-13, 289 pull requests ont été fusionnées.

### Ajouté

**Socle et accès à Kaji** (M0 à M3)
- Backend FastAPI et base SQLite, jetons Proxmox chiffrés (#1) ; compte administrateur à la première configuration, connexion et sessions (#3) ; gestion des connexions Proxmox : créer, modifier, supprimer, tester (#4) ; lecture du cluster : statut, nœuds, machines, stockages (#5) ; actions d'alimentation, suivi des tâches et audit (#8).
- Frontend React avec thèmes commutables (#10), tableau de bord avec filtres et actions (#11), flux temps réel SSE avec repli en polling et palette de commandes `Ctrl+K` (#16, #17).
- Migrations de schéma versionnées, sauvegardées et atomiques (#48) ; sessions révocables, changement de mot de passe, déconnexion de toutes les sessions (#30, #45) ; chargement automatique des routeurs (#31) ; manifeste des routes de l'API, une route perdue par accident fait échouer la CI (#219).
- Thèmes Clair et Auto en plus de Sombre et Glass (#322) ; interface adaptée aux petits écrans (#305) ; bascule français / anglais de l'interface (#309, #311) ; barre de tâches permanente (#281) ; regroupement des machines par stockage, pool, étiquette, nœud ou type (#126, #253).
- Utilisateurs de Kaji avec trois rôles : administrateur, opérateur, lecture seule, appliqués par le serveur à chaque requête (#410).
- Actions planifiées (démarrer, éteindre, redémarrer, snapshot à heure fixe) (#412) et alertes CPU, RAM, stockage, nœud hors ligne, tâche en échec, avec webhook (#414) ; le planificateur suit la tâche Proxmox lancée (#418).

**Machines virtuelles et conteneurs** (M4, M14)
- Création de VM par un assistant en 4 étapes (#19, #20) et de conteneurs LXC (#28) ; cloud-init (#29) ; cloner, migrer, supprimer avec garde-fous (#23, #24, #26) ; snapshots (#18) ; matériel : disques, cartes réseau, mémoire, cœurs (#13, #14, #21, #22).
- Options d'une VM et d'un conteneur (#157, #160, #316) ; reset, suspendre, hiberner, reprendre, convertir en modèle (#191) ; modèles de conteneur du catalogue officiel (#195) ; images OCI (#406) ; snippets `cicustom` (#240).
- Périphériques : affichage, port série, audio, générateur aléatoire, watchdog (#265) ; BIOS, disque EFI, TPM (#269) ; passthrough PCI, USB et répertoires par correspondance (#263) ; correspondances de ressources du datacenter (#251).
- Options fines des disques, cartes réseau et processeur (#382) ; migration distante vers un autre cluster (#391) ; moniteur QEMU en lecture seule avec la commande à copier (#278, #344).
- Consoles : noVNC, xterm.js, shell des nœuds (#71, #73, #78) ; terminal série d'une VM (#299) ; SPICE par fichier `.vv` (#326).

**Stockage et sauvegardes** (M5)
- Stockages en lecture, ajout, modification, retrait (#46, #133) ; sauvegardes `vzdump` : lister, lancer, supprimer, restaurer vers une nouvelle machine (#47, #51) ; jobs de sauvegarde planifiés (#53) ; téléversement et téléchargement d'ISO et de modèles (#135) ; Proxmox Backup Server (#137) ; supprimer un fichier, protéger une sauvegarde, élaguer avec aperçu (#139).

**Utilisateurs, droits et authentification Proxmox** (M6)
- Page « Accès » en lecture, « droits de Kaji » par fonction et commandes `pveum` de correction à copier (#63, #64, #69) ; session administrateur temporaire (jeton collé, jeton de Kaji en option, mot de passe) (#153, #394, #408) ; écriture des ACL, utilisateurs, groupes, jetons d'API (#156, #159, #162) ; pools de ressources (#302) ; realms LDAP, AD et OpenID (#380) ; double authentification : lire, ajouter, débloquer (#388, #400).

**Réseau et pare-feu** (M7)
- Réseau d'un nœud en lecture et en écriture, jamais appliqué sans verrou (#166, #178) ; pare-feu : alias, IPSets, groupes, options, règles, sur le datacenter, les nœuds et les machines (#168, #172, #175, #275, #289) ; SDN : zones, VNets, sous-réseaux, contrôleurs, IPAM, DNS, fabrics (#181, #183).

**Haute disponibilité, réplication, cluster** (M8, M10)
- HA et réplication en lecture et en écriture (#185, #189, #192) ; signalement d'une migration ignorée par une règle stricte (#229) ; page « Cluster » (#196) ; créer, joindre, retirer un nœud avec verrous (#340).

**Système des nœuds, Ceph** (M11, M12)
- Système d'un nœud : disques et SMART, journal, services, dépôts apt, DNS, hosts, fuseau, certificats, ACME, mises à jour, redémarrage et arrêt, serveurs NTP en commandes à copier, options du nœud (#88, #91, #94, #96, #98, #100, #102, #106, #108, #114, #116, #337, #346, #404).
- Ceph : lecture, pools, moniteurs, gestionnaires, MDS, OSD, initialisation, destruction avec barrières (#79, #86, #104, #110, #347).

**Supervision et datacenter** (M13, M15)
- Journal des tâches, historique des mesures, étiquettes, notes, vues (#83, #85, #120, #124) ; serveurs de métriques InfluxDB, Graphite, OpenTelemetry (#208) ; notifications : cibles, règles, test d'envoi (#218, #222) ; arrêt d'une tâche en cours (#312) ; journal du cluster (#402).
- Options du datacenter : clavier, langue, console, plage d'identifiants, style des étiquettes, étiquettes réservées, consentement, HA, fencing, CRS, débits, réplication, WebAuthn (#199, #239, #245, #369, #383) ; actions groupées d'un nœud et Wake-on-LAN (#234).

**Déploiement**
- Docker Compose (backend, nginx) (#49) ; HTTPS facultatif par Caddy avec autorité interne, sur le port 443 avec redirection depuis 80, et un nom DNS local en plus de l'adresse (#354, #420, #421, #422).

### Sécurité
- Revue de sécurité de la V1 : `docs/securite.md` ; test qui vérifie que **toute route** de l'API répond 401 sans session (#351).
- `KAJI_SECRET_KEY` vide ou d'exemple refusée au démarrage (#351).
- Épinglage de l'empreinte SHA-256 du certificat de Proxmox par connexion (#354) ; jeton de première configuration `KAJI_SETUP_TOKEN` (#354).
- Mots de passe Argon2, cookie `HttpOnly` / `SameSite=Strict` / `Secure`, limiteur de connexions, en-têtes de sécurité et CSP, base en `600`, backend sans privilèges (#30, #49).
- Validation partout par `fullmatch` (le `$` d'une expression régulière accepte un saut de ligne final) (#52).
- Aucun secret dans l'audit, les journaux, les erreurs ni les réponses d'API (règle vérifiée par des tests dans chaque lot).

### Corrigé
- Défauts trouvés en essai réel sur un vrai cluster, entre autres : alias d'IPSet supprimable alors qu'il est cité (#170) ; position finale d'une règle de pare-feu (#176) ; commentaires HA altérés par Proxmox (#212) ; sous-réseau SDN envoyé en CIDR (#374) ; en-têtes de webhook au format de Proxmox (#375) ; redémarrage de `pvedaemon` annoncé en échec (#360, #362) ; certificat HTTPS absent pour une adresse IP ou un nom (#420, #422) ; démarrage d'une machine déjà en marche refusé tout de suite (#297).

### Retiré
- Copie d'un fichier vers un autre stockage ou nœud : l'API de Proxmox la refuse au jeton de Kaji, la route est retirée (#214, #215).

### Limites connues
- **Un seul jeton Proxmox partagé** par tous les utilisateurs de Kaji : les actions apparaissent sous le même nom dans le journal de Proxmox.
- Pas de SSO ni de double authentification pour se connecter à Kaji ; limiteur de connexions en mémoire ; aucune relecture de sécurité ni test d'intrusion par un tiers.
- Essayé sur un seul cluster de 2 nœuds, sans ZFS, Ceph ni PBS : ces fonctions sont codées et testées sur un faux Proxmox strict, pas validées en réel.
- Images de base Docker désignées par étiquette, pas par empreinte (ticket #427).
- Fonctions réservées à `root@pam` par Proxmox : moniteur QEMU, `affinity`, `hugepages`, `keyctl` / `fuse` / `mount`, création et jonction de cluster.

[Non publié]: https://github.com/Ek8Oxilive/kaji/compare/v1.0.0-rc1...main
[1.0.0-rc1]: https://github.com/Ek8Oxilive/kaji/releases/tag/v1.0.0-rc1
