# Parité avec l'interface de Proxmox

**But : ne perdre aucune fonctionnalité de l'interface de Proxmox VE.** Ce document est le tableau de suivi : chaque fonction de
l'interface native, son état dans Kaji, et le jalon qui la livre. Il se met à jour à chaque PR qui livre une fonction. Il est
dressé d'après l'interface de Proxmox VE 9 (le cluster de test est en 9.1.9) ; **une fonction oubliée ici doit être ajoutée**, pas
ignorée.

**États** : ✅ fait (validé en réel) · 🟡 partiel · ⬜ prévu (jalon indiqué) · ➖ hors périmètre (autre produit).

**Limite honnête.** Le but est très large : l'interface de Proxmox est le fruit de plus de dix ans de développement. Le plan
l'atteint par étapes, **ordonnées par usage quotidien**. Plusieurs jalons (réseau, firewall, HA, Ceph, cluster) peuvent **couper
l'accès ou casser le cluster** s'ils sont mal testés : ils exigent un banc d'essai imbriqué (voir « Prérequis »).

## Prérequis : un banc d'essai jetable

Réseau, firewall, HA, Ceph et gestion du cluster ne se testent **pas** sur le cluster réel : une erreur peut couper la connexion
à tous les nœuds. Avant M7, M8, M10 et M12 : **un Proxmox imbriqué** (2 à 3 VM Proxmox dans le cluster, sur un réseau isolé),
détruit et recréé à volonté. **Décision du propriétaire attendue** (ressources : environ 8 à 12 Go de RAM et 100 Go de disque).

## Datacenter

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Résumé du cluster (nœuds, quorum, ressources) | ✅ | Dashboard |
| Notes du datacenter | ✅ (lecture et édition, validées en réel le 2026-11-09, `docs/api/datacenter.md`) | M15 |
| Cluster : créer, joindre, liens corosync, retirer un nœud | ✅ côté code (lecture : `docs/api/cluster.md` ; créer / joindre / retirer un nœud avec verrous, `dry_run` et phrase `COUPURE POSSIBLE` : `docs/api/cluster-ecriture.md`, option B de `docs/m10-cluster.md` ; faux Proxmox seulement, jamais écrit en réel, droit de Proxmox non documenté) | M10 |
| Options du datacenter (clavier, langue, console, proxy HTTP, e-mail d'envoi, préfixe MAC, migration, tâches parallèles) | 🟡 (lecture et édition ; **clavier validé en réel**, les autres champs validés seulement par refus et faux Proxmox ; **HA (`shutdown_policy`), fencing, CRS, débits, réseau de réplication : modifiables (lot #365, `docs/api/datacenter.md`, section « Haute disponibilité, ordonnancement et débits », confirmation décidée par le serveur ; **validés en réel le 2026-11-13** (écrits, relus, retirés, état d'origine rétabli) sauf réplication `insecure` confirmée, fencing `hardware` / `both` écrit et effet avec de vraies ressources HA : jamais essayés)** ; plage des identifiants libres, style des étiquettes (lot #237), droits des étiquettes, étiquettes réservées et texte de consentement (lot #243) : **validés en réel le 2026-11-10** (écrits, relus à l'identique, retirés ; modes `none`, `existing`, `free` et `case_sensitive` non essayés) ; **WebAuthn : modifiable (lot #381, section « WebAuthn » de la page Datacenter, phrase `COUPURE POSSIBLE` pour changer ou retirer une valeur déjà définie, origine cohérente avec l'identifiant) ; code seulement, jamais écrit en réel (change l'id = casse les credentials)** ; U2F (ancien mécanisme) : hors périmètre) | M15 |
| Stockage : liste, usage, contenu | ✅ (lecture) | M5 |
| Stockage : ajouter, modifier, supprimer (dir, LVM, LVM-thin, ZFS, NFS, CIFS, iSCSI, CephFS, RBD, PBS) | ✅ (validé en réel pour `dir` ; les autres types : non validés en réel) | M5 |
| Sauvegardes planifiées (jobs) | ✅ | M5 |
| Sauvegardes : liste, lancer, restaurer, supprimer, protéger | ✅ (protection : écriture non validée en réel) | M5 |
| Intégration d'un serveur Proxmox Backup Server (stockage, chiffrement, vérification) | 🟡 (aucun PBS pour valider en réel ; vérification : lecture seule, planification côté PBS) | M5 |
| Réplication (jobs ZFS) | ✅ code (lecture + écriture : créer, modifier, supprimer, lancer maintenant, `docs/api/replication-ecriture.md` ; **jamais écrit en réel : pas de ZFS**, bloqueurs annoncés par `dry_run`) | M8 |
| Permissions : utilisateurs, groupes, rôles, ACL, pools, realms (lecture) | ✅ | M6 |
| Permissions : écriture, tokens API, double authentification, realms LDAP/AD/OpenID | 🟡 (session administrateur, écriture d'une ACL, utilisateurs, groupes, appartenances et tokens API livrés, non validés en réel ; **realms LDAP / AD / OpenID : lire, créer, modifier, supprimer, synchroniser livrés (lot #379, `docs/api/realms.md`, verrous décidés par le serveur, session administrateur) ; code seulement, jamais écrit en réel** (le jeton de Kaji n'a pas `Realm.Allocate`, aucun annuaire sur le cluster) ; **double authentification des utilisateurs : lire, générer un secret TOTP, ajouter TOTP et codes de secours, activer / désactiver, supprimer livrés (lot #384, `docs/api/tfa.md`, session administrateur, phrase `COUPURE POSSIBLE` quand elle s'active sur un compte sans entrée active) ; **écriture impossible avec un jeton : essayée en réel le 2026-11-13, Proxmox refuse (`allowtoken: 0` pour la TFA, `docs/api/tfa.md`) ; lecture seule dans Kaji** ; clés WebAuthn / U2F et YubiKey hors périmètre) | M6 |
| Pools de ressources (créer, commentaire, ajouter / retirer des machines et des stockages, supprimer un pool vide et sans droit) | ✅ (validé en réel le 2026-11-12, `docs/api/pools.md` : création, ajout de machine et de stockage, déplacement entre deux pools, retraits avec confirmation, suppression d'un pool vide, refus ; interface ouverte ; suppression d'un pool non vide ou avec droits : couverte par les tests seulement) | M6 |
| HA : ressources, groupes ou règles, fencing | ✅ (lecture + écriture : ressources, règles, migrer, relocaliser, `docs/api/ha-ecriture.md` ; verrous : < 3 nœuds = `COUPURE POSSIBLE`, machine de Kaji interdite ; **validé en réel le 2026-11-09 sur une VM jetable** ; groupes remplacés par les règles) | M8 |
| ACME (certificats automatiques) | 🟡 (comptes, domaines du nœud, commande, renouvellement codés, jamais exécutés en réel ; plugins DNS : lecture seule) | M11 |
| Pare-feu : règles, alias, IPSet, groupes de sécurité, options | 🟡 (lecture validée en réel ; alias, IPSets, groupes et options : écriture livrée et validée en réel sur objets inertes ; règles : écriture livrée (M7-3b), `docs/api/pare-feu-regles.md`) | M7 |
| Serveurs de métriques (InfluxDB, Graphite, OpenTelemetry) | 🟡 (lister, ajouter, modifier, supprimer ; secrets en écriture seule, `docs/api/metriques.md` ; **InfluxDB et Graphite désactivés validés en réel (2026-11-12)** ; OpenTelemetry : Proxmox teste la connexion dès la création, même désactivé, donc non validé sans collecteur joignable ; serveur actif jamais écrit en réel) | M13 |
| Notifications : cibles et règles | 🟡 (lecture validée en réel ; écriture : cibles sendmail et gotify (désactivées) et règles **validées en réel le 2026-11-12** ; **SMTP (sans authentification) et webhook (sans secret) désactivés : créés, modifiés, supprimés en réel le 2026-11-13** (lot #373) ; **défaut trouvé et corrigé** : les en-têtes et secrets d'un webhook s'écrivent `name=<nom>,value=<base64>`, pas `<nom>=<base64>` ; **en-têtes d'un webhook validés en réel après correction** (créé avec `Content-Type`, remplacé par deux en-têtes, supprimé) ; jamais essayés : secrets d'un webhook, SMTP avec identifiants, test d'envoi (attend un relais SMTP, `docs/v1-actions-enzo.md`), `docs/api/notifications.md`) | M13 |
| SDN : zones, VNets, sous-réseaux, contrôleurs, IPAM, DNS, fabrics | 🟡 (zones, VNets, sous-réseaux, contrôleurs, IPAM, DNS, fabrics, appliquer, annuler : code livré, `docs/api/sdn.md`, **validé en réel le 2026-11-13 pour zone `simple` + VNet en attente puis `rollback`** (droit `PVESDNAdmin` sur `/sdn` à l'utilisateur ET au jeton) ; **sous-réseau validé en réel (API et interface) : le réseau part en CIDR, Proxmox fabrique l'identifiant** ; **zones `vlan` / `qinq` / `vxlan` / `evpn`, contrôleur `evpn` et fabrics `openfabric` / `ospf` créés en attente en réel** (fabrics : second défaut corrigé, la lecture ne trouvait pas l'objet neuf) ; appliquer, IPAM, DNS, nœuds de fabric, contrôleurs `bgp` / `isis` : jamais essayés en réel) | M7 |
| Correspondances de ressources (PCI, USB, répertoires : lire, créer, modifier, supprimer, matériel détecté ; **les utiliser dans une VM : fait**, section de l'onglet Matériel, `docs/api/passthrough.md`) | 🟡 (codé, `docs/api/correspondances.md` ; validé en réel le 2026-11-10 et 2026-11-11, sauf VM en marche, `mdev` et démarrer une VM avec un périphérique : voir `docs/REPRISE.md`) | M14 |
| Abonnement / support | ➖ | — |

## Nœud

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Résumé (état, graphiques CPU, RAM, réseau, disque dans le temps) | ✅ (jauges et historique heure à année) | M13 |
| Notes du nœud | ✅ (validé en réel le 2026-11-10 : écrire, relire, vider ; texte absent de l'audit) | M13 |
| Shell du nœud (droit `Sys.Console` ; compte Unix du nœud demandé au `login:`) | 🟡 (codé, validation en réel à faire) | M9 |
| Réseau : interfaces, bridges, bonds, VLAN, appliquer / annuler | 🟡 (lecture des interfaces et des modifications en attente validée en réel ; écriture livrée (M7-4, `docs/api/reseau-ecriture.md`) : préparer, appliquer avec verrous, annuler ; l'application n'a jamais été exécutée en réel) | M7 |
| Certificats (personnalisés, ACME) | 🟡 (lecture ; personnalisé : **installer et retirer validés en réel le 2026-11-12** (`enzo2`, certificat auto-signé jetable : contrôle local, refus sans `confirm` 400 et clé invalide 422, installation 200 (`pveproxy-ssl.pem` apparu), second dépôt 409, retrait 200 (retour aux deux certificats d'origine), second retrait 409, aucune clé dans l'audit) ; chaîne signée par une autorité, `restart: false` et remplacement `replace_existing` : non essayés ; ACME : voir plus haut) | M11 |
| DNS, hôtes, fuseau horaire, heure | ✅ (**validé en réel le 2026-11-12** sur `enzo2` : fuseau `Europe/Paris` → `UTC` → `Europe/Paris` relu à chaque étape ; DNS et `hosts` réécrits à l'identique (contenu, `digest` et DNS inchangés) ; refus sans `confirm` : 400 ; `digest` périmé : d'abord un 502 (Proxmox 500), **corrigé en 409 (lot #261, tests seulement, à revérifier après déploiement)** ; nouvelles valeurs de DNS ou de `hosts` non essayées ; **synchronisation NTP : hors de l'API de Proxmox 9** (`/nodes/{n}/time` n'accepte que `timezone`, vérifié dans `apidoc.js` le 2026-11-12) ; elle se règle dans la configuration de `chrony` sur le nœud ; Kaji peut redémarrer le service `chrony` (validé en réel), lire l'heure et **générer les commandes `chrony` à copier** (bouton « Serveurs NTP… », `docs/api/ntp-noeud.md`, format Debian non vu en réel)) | M11 |
| Mises à jour (apt) et dépôts | 🟡 (liste, actualiser ; **dépôts : activer / désactiver validés en réel le 2026-11-12** (`enzo2`, dépôt en doublon `pve-no-subscription.list` désactivé puis réactivé, état relu identique, audit sans détail) ; **ajouter un dépôt standard validé en réel le 2026-11-12** (`enzo2`, « Ceph Squid No-Subscription » : refus sans `confirm` 400, `digest` périmé 409, nom inconnu 404, ajout 200 ajouté ACTIF dans le fichier `ceph.sources` existant, second ajout 409, puis désactivé ; **Proxmox n'a pas de suppression de dépôt : l'entrée désactivée reste**) ; installer = commande à lancer dans la console du nœud, car l'API de Proxmox n'a pas d'installation ; dépôt personnalisé : **commandes à copier** (l'API de Proxmox n'écrit que les dépôts standard) : fichier `.sources` et commandes générés, rien écrit, `docs/api/depot-apt-perso.md`, lot #336) | M11 |
| Firmware | ➖ (aucune route dans l'API de Proxmox 9.1.9 : `GET /nodes/{n}/firmware` → 501) | — |
| Journal système (syslog) | ✅ (lecture validée en réel le 2026-11-10 sur `enzo2` : 20 lignes sur 73 707, droit `Sys.Syslog`) | M11 |
| Services (démarrer, arrêter, redémarrer) | 🟡 (**liste validée en réel le 2026-11-12** : état, risque, `stoppable` ; **redémarrer `chrony` (niveau « normal ») validé en réel le 2026-11-12** sur `enzo2` : refus sans `confirm`, puis tâche `srvrestart` terminée en OK, service revenu en `running` ; **redémarrer `cron`, arrêter puis démarrer `ksmtuned` validés en réel le 2026-11-12** (`enzo2`, accord d'Enzo : refus sans `confirm` 400, tâches `srvrestart` / `srvstop` / `srvstart` acceptées, état `dead` puis `running` relu, état d'origine rétabli) ; **recharger `cron` validé en réel le 2026-11-12** (tâche `srvreload` terminée en OK, service resté `running`, refus sans `confirm` 400) ; **services « sensibles » validés en réel le 2026-11-12** (`enzo2` : `pvestatd`, `pvescheduler`, `spiceproxy` redémarrés, tâche OK, retour en `running`, refus sans `confirm` 400) ; **`pveproxy` et `pvedaemon` redémarrés aussi** (`pveproxy` : tâche OK ; `pvedaemon` : service revenu en `running` mais **Proxmox marque la tâche « failed: received interrupt »**, car le démon qui exécute la tâche se redémarre lui-même : **l'interface relit alors l'état du service et l'annonce réussi s'il est `running`** (lot du 2026-11-13, vérifié en réel par l'interface ; le suivi de la tâche peut aussi échouer en « 595 Connection refused » pendant le redémarrage : même traitement)) ; services vitaux (`corosync`, `pve-cluster`) et les refus d'arrêt / de nom retapé : jamais exécutés en réel, couverts par le faux Proxmox seulement) | M11 |
| Disques : liste, SMART, initialiser GPT, effacer, LVM, LVM-thin, répertoire, ZFS | 🟡 (lecture complète, **liste et SMART validés en réel le 2026-11-10 sur `enzo2`** ; GPT, effacer, créer et supprimer (volume vide) LVM / LVM-thin / répertoire / ZFS, codés et jamais exécutés en réel) | M11 |
| Ceph (état, configuration, moniteurs, OSD, CephFS, pools, journaux) — cadré dans `docs/m12-ceph.md` | 🟡 (lecture et écriture C2 / C3 / initialisation et destruction C4 codées, `docs/api/ceph.md`, `docs/api/ceph-destruction.md` ; **jamais validées en réel : pas de Ceph sur le cluster** ; détruire un CephFS : pas d'API chez Proxmox, ligne de commande) | M12 |
| Pare-feu du nœud | 🟡 (options et règles : lecture et écriture avec verrous, section de la page Nœud et page « Réseau », `docs/api/pare-feu-noeud.md` ; jamais activé en réel ; section vue en réel en lecture seule le 2026-11-12, aperçu des verrous compris) | M7 |
| Réplication du nœud | 🟡 (section de la page Nœud : jobs source ou cible, état, nouveau / modifier / lancer / supprimer avec aperçu et verrous, `docs/api/replication-noeud.md` ; jamais écrit en réel : pas de ZFS ; section et aperçu `dry_run` vus en réel le 2026-11-12) | M8 |
| Historique des tâches du nœud (journal, état, suivi en direct) | ✅ | M13 |
| Actions groupées (tout démarrer, tout arrêter, tout migrer) et Wake-on-LAN | 🟡 (liste de machines explicite, aperçu `dry_run`, protégées refusées, nom du nœud retapé ; `docs/api/actions-groupees.md` ; **démarrer, arrêter et migrer validés en réel le 2026-11-10** sur la VM 115 seule ; migration à chaud, arrêt sans `force-stop` et Wake-on-LAN non essayés) | M15 |
| Redémarrer / éteindre le nœud | 🟡 (codé, jamais exécuté en réel) | M11 |

## Machine virtuelle (QEMU)

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Démarrer, éteindre, redémarrer, arrêt forcé | ✅ | M2 |
| Réinitialiser (reset), suspendre, reprendre, hiberner | ✅ (validé en réel le 2026-11-09, VM 115 : reset, suspendre, reprendre (à la souris, #201 corrigé, « En pause »), hiberner (réussi, sans agent invité) ; Éteindre et Redémarrer ne sont pas proposés sur une VM en pause ; aussi dans un repli « Plus d'actions » de chaque carte (lot #318) ; `docs/api/alimentation-vm.md`) | M14 |
| Console : noVNC ✅ ; xterm.js (conteneur ✅, **port série socket d'une VM** : session ouverte en réel le 2026-11-12, aucun système n'y répond, `docs/api/console.md`) ; **SPICE** : codé, fichier `.vv` pour virt-viewer, `docs/api/console-spice.md` | 🟡 | M9 / M14 |
| Créer (assistant complet) | ✅ (VM et LXC créés puis supprimés en réel ; **démarrage depuis une ISO validé le 2026-11-12** : Alpine 3.24, écran noVNC jusqu'à `login:`) | M4 |
| Matériel : CPU, RAM, disques (ajouter, déplacer, agrandir, détacher, supprimer), cartes réseau, CD/DVD, ordre de démarrage | ✅ (validé en réel : CPU, RAM, ajouter/détacher/supprimer un disque ; **déplacer un disque (`local-lvm` ↔ `dir`, source supprimée), l'agrandir (+1 Go) et ajouter / retirer une carte réseau validés le 2026-11-12**) | M4 |
| Matériel : options fines d'un disque (cache, discard, iothread, ssd, aio, sauvegarde, limites de débit), d'une carte réseau (débit, MTU, files multiples, câble débranché, trunks) et du CPU (cpuunits, cpulimit, affinity, hugepages) | 🟡 (lot #377, `docs/api/options-materiel.md` : **disque (cache, discard, iothread, ssd, limites), carte réseau (débit, MTU, files, trunks, câble débranché) et CPU (cpuunits, cpulimit) validés en réel le 2026-11-13** ; **`affinity` et `hugepages` : réservés à `root@pam`, refusés au token de Kaji (non proposés)** ; drapeaux du processeur, options de disque de conteneur et rafales : non gérés) | M14 |
| Matériel avancé : passthrough PCI et USB **par correspondance** (`hostpciN`, `usbN`, `virtiofsN`) | 🟡 (`docs/api/passthrough.md` ; **PCI, USB et répertoire ajoutés, modifiés et retirés en réel le 2026-11-11** sur la VM 115 arrêtée ; VM en marche, `pcie` / `x-vga` / `mdev` et démarrer avec un périphérique non essayés ; les périphériques bruts sont réservés à root@pam) | M14 |
| Matériel avancé : carte d'affichage, ports série, audio, RNG, watchdog | 🟡 (onglet « Périphériques » : ports série **socket seulement**, générateur aléatoire `/dev/urandom` seulement, `docs/api/peripheriques.md`, ticket #225 ; **écrit, relu et retiré en réel le 2026-11-10** sur la VM 115 arrêtée ; `vga: none`, VM en marche et options fines non essayés) | M14 |
| Matériel avancé : BIOS, disque EFI, TPM | 🟡 (onglet « Périphériques » : `bios`, `efidisk0` et `tpmstate0` en AJOUT seulement si absent, retrait confirmé ; `docs/api/peripheriques.md`, ticket #268 ; **créés, relus et retirés en réel le 2026-11-10** sur la VM 115 ; démarrage d'un système UEFI non essayé ; hotplug : onglet Options) | M14 |
| Options (démarrage automatique, ordre de démarrage, OS, QEMU Agent, tablette, protection, mémoire NUMA…) | ✅ validé en réel (VM 115 : démarrage automatique, tablette, ordre de démarrage, agent, protection avec confirmation, refus des valeurs invalides ; `docs/api/options.md`, lot #144) ; `keyboard` et `reboot` : validés en réel le 2026-11-12 (lot #315) ; `vga` : onglet Périphériques ; `tags` et `name` : déjà gérés ailleurs | M14 |
| Cloud-init (utilisateur, mot de passe, clés SSH, IP, DNS) | ✅ (validé en réel, mot de passe et clés SSH non essayés ; retirer `upgrade` : 🟡 non validé en réel, lot M14 #143) | M4 |
| Cloud-init avancé (snippets `cicustom` : lire, choisir un snippet existant par partie, retirer ; téléversement impossible par l'API) | 🟡 (`docs/api/cloudinit-avance.md` ; **choisir et retirer un snippet pour `user` validés en réel le 2026-11-10** ; `network`, `meta`, `vendor` et démarrer la VM avec un snippet non essayés ; les snippets ne se téléversent pas par l'API) | M14 |
| Snapshots (créer, supprimer, restaurer) | ✅ (validé en réel) | M4 |
| Clone (complet, lié), convertir en modèle | ✅ (clone complet validé en réel, **clone lié validé le 2026-11-12 (`lvm-thin`)** ; **convertir en modèle validé en réel le 2026-11-09** (VM 117 et LXC 119, refus compris, à la souris) ; écarts corrigés et revérifiés le 2026-11-09 : fenêtre de conversion (#202), « Supprimer le modèle » (#203), démarrage d'un modèle refusé en 409 (#204) ; supprimer un modèle ayant un clone lié : **Proxmox l'accepte sur `lvm-thin`** (le clone reste intact), Kaji ne le signale pas ; `docs/api/alimentation-vm.md`) | M4 / M14 |
| Migration (en ligne, hors ligne, **distante** vers un autre cluster) | ✅ (hors ligne validée en réel ; **à chaud validée le 2026-11-12** (VM 115, disque local copié, 25 s, arrêt de 4 ms, aller-retour) ; **distante : code livré (lot #390, bouton « Autre cluster… », `docs/api/migration-distante.md`, empreinte du certificat distant obligatoire, jeton distant en écriture seule, `delete` verrouillé par le nom retapé et la phrase), jamais essayée en réel : un seul cluster, fonction expérimentale chez Proxmox**) | M4 / M14 |
| Sauvegarde et restauration de la machine | ✅ | M5 |
| Réplication de la machine | 🟡 (onglet « Réplication » : jobs de la machine, nouveau / modifier / lancer / supprimer avec aperçu et verrous ; `docs/api/onglets-machine.md` ; onglet et aperçu `dry_run` vus en réel le 2026-11-10 ; ZFS absent : jamais écrit en réel) | M8 |
| Pare-feu de la machine (règles, options, IPSet) | 🟡 (options et règles en écriture ; IPSet de machine livré en M7-2 ; **onglet de la machine vu en réel le 2026-11-11** : règle créée puis supprimée, alias créé puis supprimé ; options de la machine et pare-feu activé : jamais écrits en réel) | M7 |
| Permissions de la machine | 🟡 (onglet « Permissions » : ACL sur la machine et héritées, écriture par la fenêtre de la page « Accès » ; `docs/api/onglets-machine.md` ; onglet vu en réel le 2026-11-10 (4 entrées héritées) ; écriture jamais essayée en réel) | M6 |
| Moniteur QEMU (`qm monitor`) | 🟡 (codé : commandes « info » de la liste blanche, onglet « Moniteur », garde-fous validés en réel ; **Proxmox 9 refuse le moniteur au token de Kaji** (403, probablement réservé à `root@pam`), donc inutilisable d'ici sans token root ; **l'onglet affiche `qm monitor <id>` et la commande à taper dedans, à copier dans la console du nœud** (le one-liner avec `echo` n'affiche rien : retiré le 2026-11-13 ; **`qm monitor <id>` puis `info status` validé par Enzo dans la console du nœud le 2026-11-13** : `VM status: running`) (lot du 2026-11-12, Enzo garde la fonction) ; commandes libres : jamais ; `docs/api/moniteur-qemu.md`) | M14 |
| Historique des tâches de la machine | ✅ (onglet « Tâches », journal en direct ; consoles masquées par défaut) | M13 |
| Étiquettes (tags) et notes | ✅ (validé en réel le 2026-11-10 sur la VM 115 : ajouter et retirer une étiquette, écrire et restaurer les notes, HTML affiché comme texte ; empreinte périmée entre étiquettes et notes corrigée) | M13 |
| Résumé avec graphiques d'historique | ✅ (onglet « Performances ») | M13 |
| Supprimer | ✅ (validé en réel : nom retapé exigé) | M4 |

## Conteneur (LXC)

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Démarrer, éteindre, redémarrer, arrêt forcé | ✅ | M2 |
| Console : noVNC et terminal xterm.js | ✅ | M9 |
| Créer depuis un modèle (privilégié ou non) | ✅ (téléchargement d'un modèle du catalogue officiel : fait et validé en réel le 2026-11-09, `docs/api/modeles-lxc.md`) | M4 / M14 |
| Ressources, disques, points de montage, réseau, DNS | ✅ | M4 |
| Options et fonctionnalités (démarrage automatique, nesting, FUSE, keyctl, montages CIFS/NFS) | 🟡 validé en réel (2026-11-08 et 2026-11-09) sauf **`keyctl`, `fuse` et `mount`** : Proxmox les refuse au token de Kaji (ils exigent `root@pam`) ; Kaji répond 403 avec un message clair pour les trois (`mount` observé le 2026-11-09, lot #164) ; nesting (interface), démarrage, tty, cmode, protection, fuseau OK ; cas « keyctl déjà actif puis changer nesting » non essayé (`docs/api/options.md`, lots #145 et #164) | M14 |
| Snapshots, clone, migration, sauvegarde, restauration, suppression | ✅ | M4 / M5 |
| Pare-feu (onglet de la machine : options, règles, alias, IPSets, `docs/api/pare-feu-machine.md`), réplication, permissions, historique (Performances), tags | 🟡 (réplication, permissions, historique et tags ✅ ; **pare-feu : onglet codé, voir `docs/REPRISE.md` pour le vu en réel**) | M7 / M8 / M6 / M13 |

## Stockage et fichiers

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Contenu : voir ISO, modèles, disques, sauvegardes, snippets | ✅ | M5 |
| **Téléverser** une ISO ou un modèle, **télécharger depuis une URL** (avec somme de contrôle) | ✅ (téléversement et téléchargement par URL validés en réel, avec sha256) | M5 |
| Modèles LXC officiels (TurnKey, distributions) : télécharger | ✅ (validé en réel le 2026-11-09 : catalogue de 136 entrées, téléchargement d'Alpine en 2 s, 409 et 422 sans tâche, dialogue de l'assistant LXC ; l'architecture du nœud filtre le catalogue (#205 corrigé, revérifié : 134 modèles amd64, 136 avec la case) ; `docs/api/modeles-lxc.md`) | M14 |
| Supprimer un volume, actions sur un volume, élagage (prune) manuel | ✅ (suppression de fichier validée en réel ; protection et élagage : non validés en réel, aucune sauvegarde ; copie d'un volume vers un autre stockage ou nœud : **non retenue**, absente de l'interface de Proxmox et l'API expérimentale refuse le token de Kaji (403 constaté en réel), `docs/api/volumes.md`) | M5 |

## Transverses

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Barre de tâches en bas (tâches en cours, journal d'une tâche) | 🟡 (page « Tâches », tiroir de journal et **barre permanente** repliable en bas de chaque page, `docs/api/barre-de-taches.md` ; arrêter une tâche en cours : validé en réel le 2026-11-12 (liste blanche de types, `docs/api/taches.md`)) | M13 |
| Recherche globale | ✅ (palette Ctrl+K, validée en réel) | M3 |
| Vues par dossier, par pool, par stockage | 🟡 (regroupement par nœud, pool, étiquette, type, **stockage** (lot #252, `docs/api/vue-par-stockage.md`)) | M13 |
| Thèmes clair / sombre | ✅ (Sombre, Glass, **Clair** et **Auto** (suit le système), mémorisés, `docs/themes.md`) | M3 |
| Langues | ✅ (français et anglais, sélecteur FR \| EN, `docs/interface-langue.md` ; messages du serveur construits avec des valeurs : français) | M15 |
| Interface adaptée aux petits écrans (téléphone) | 🟡 (menu tiroir, grilles en une colonne, `docs/interface-mobile.md` ; vue en réel à ~390 px seulement : pas de vrai téléphone, ni Safari / iOS, ni mode paysage) | M15 |
| Tableau de bord temps réel | ✅ (flux SSE validé en réel : un instantané toutes les 5 s) | M3 |
| Journal d'audit des actions de Kaji | ✅ (Kaji uniquement : hors Proxmox) | M1 |

## Hors périmètre (autres produits)

Proxmox Backup Server (son interface d'administration), Proxmox Mail Gateway, Proxmox Datacenter Manager : **produits distincts**,
pas des fonctions de Proxmox VE. Kaji gère en revanche leur **intégration** dans Proxmox VE (stockage PBS, M5).

## Ordre proposé (par usage quotidien)

1. **M6 lot A** (en cours) : droits de Kaji expliqués, commandes à copier, profil de droits recommandé.
2. **M9 : console** (noVNC, xterm.js) : la fonction la plus regrettée dès qu'on quitte l'interface native.
3. **M13 : journal des tâches, graphiques d'historique, tags, notifications.**
4. **M11 : système des nœuds** (mises à jour, dépôts, certificats, DNS, heure, services, disques).
5. **M5 (reste)** : téléverser / télécharger ISO et modèles, ajouter un stockage.
6. **M6 (suite)** : écriture des droits par session (voir `docs/m6-ecriture.md`).
7. **M7 : réseau, firewall, SDN** : **seulement avec le banc d'essai imbriqué**.
8. **M8 : HA et réplication**, puis **M12 : Ceph** et **M10 : cluster** : idem, banc d'essai obligatoire.
9. **M14 : options avancées des machines**, **M15 : options du datacenter et divers.**

## Décisions à prendre

1. **Banc d'essai Proxmox imbriqué : on le monte ?** *(recommandé : oui, avant M7)*
2. **L'ordre ci-dessus te convient-il ?** (en particulier : console avant le réseau).
3. **Ceph : as-tu Ceph ou comptes-tu en utiliser ?** Sans Ceph sur ton cluster, M12 ne pourra se tester que sur le banc imbriqué.
