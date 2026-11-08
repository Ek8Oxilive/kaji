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
| Notes du datacenter | ⬜ | M15 |
| Cluster : créer, joindre, liens corosync, retirer un nœud | ⬜ | M10 |
| Options du datacenter (clavier, langue, console, proxy HTTP, préfixe MAC, migration, HA, tâches parallèles) | ⬜ | M15 |
| Stockage : liste, usage, contenu | ✅ (lecture) | M5 |
| Stockage : ajouter, modifier, supprimer (dir, LVM, LVM-thin, ZFS, NFS, CIFS, iSCSI, CephFS, RBD, PBS) | ✅ (validé en réel pour `dir` ; les autres types : non validés en réel) | M5 |
| Sauvegardes planifiées (jobs) | ✅ | M5 |
| Sauvegardes : liste, lancer, restaurer, supprimer, protéger | ✅ (protection : écriture non validée en réel) | M5 |
| Intégration d'un serveur Proxmox Backup Server (stockage, chiffrement, vérification) | 🟡 (aucun PBS pour valider en réel ; vérification : lecture seule, planification côté PBS) | M5 |
| Réplication (jobs ZFS) | ⬜ | M8 |
| Permissions : utilisateurs, groupes, rôles, ACL, pools, realms (lecture) | ✅ | M6 |
| Permissions : écriture, tokens API, double authentification, realms LDAP/AD/OpenID | ⬜ | M6 |
| HA : ressources, groupes ou règles, fencing | ⬜ | M8 |
| ACME (certificats automatiques) | 🟡 (comptes, domaines du nœud, commande, renouvellement codés, jamais exécutés en réel ; plugins DNS : lecture seule) | M11 |
| Pare-feu : règles, alias, IPSet, groupes de sécurité, options | ⬜ | M7 |
| Serveurs de métriques (InfluxDB, Graphite) | ⬜ | M13 |
| Notifications : cibles et règles | ⬜ | M13 |
| SDN : zones, VNets, sous-réseaux, contrôleurs, IPAM, DNS, fabrics | ⬜ | M7 |
| Correspondances de ressources (PCI, USB) | ⬜ | M14 |
| Abonnement / support | ➖ | — |

## Nœud

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Résumé (état, graphiques CPU, RAM, réseau, disque dans le temps) | ✅ (jauges et historique heure à année) | M13 |
| Notes du nœud | 🟡 (lecture et édition codées, jamais exécutées en réel) | M13 |
| Shell du nœud (droit `Sys.Console` ; compte Unix du nœud demandé au `login:`) | 🟡 (codé, validation en réel à faire) | M9 |
| Réseau : interfaces, bridges, bonds, VLAN, appliquer / annuler | 🟡 (lecture des bridges) | M7 |
| Certificats (personnalisés, ACME) | 🟡 (lecture ; personnalisé : installer / retirer codé, jamais exécuté en réel ; ACME : voir plus haut) | M11 |
| DNS, hôtes, fuseau horaire, heure | 🟡 (codé, jamais exécuté en réel ; synchronisation NTP ⬜) | M11 |
| Mises à jour (apt) et dépôts | 🟡 (liste, actualiser, dépôts : activer / désactiver / ajouter un standard, codés et jamais exécutés en réel ; installer = commande à lancer dans la console du nœud, car l'API de Proxmox n'a pas d'installation ; dépôt personnalisé ⬜) | M11 |
| Firmware | ➖ (aucune route dans l'API de Proxmox 9.1.9 : `GET /nodes/{n}/firmware` → 501) | — |
| Journal système (syslog) | 🟡 (lecture, droit `Sys.Syslog`) | M11 |
| Services (démarrer, arrêter, redémarrer) | 🟡 (codé, validation en réel à faire) | M11 |
| Disques : liste, SMART, initialiser GPT, effacer, LVM, LVM-thin, répertoire, ZFS | 🟡 (lecture complète ; GPT, effacer, créer et supprimer (volume vide) LVM / LVM-thin / répertoire / ZFS, codés et jamais exécutés en réel) | M11 |
| Ceph (état, configuration, moniteurs, OSD, CephFS, pools, journaux) — cadré dans `docs/m12-ceph.md` | ⬜ | M12 |
| Pare-feu du nœud | ⬜ | M7 |
| Réplication du nœud | ⬜ | M8 |
| Historique des tâches du nœud (journal, état, suivi en direct) | ✅ | M13 |
| Actions groupées (tout démarrer, tout arrêter, tout migrer) et Wake-on-LAN | ⬜ | M15 |
| Redémarrer / éteindre le nœud | 🟡 (codé, jamais exécuté en réel) | M11 |

## Machine virtuelle (QEMU)

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Démarrer, éteindre, redémarrer, arrêt forcé | ✅ | M2 |
| Réinitialiser (reset), suspendre, hiberner | ⬜ | M14 |
| Console : noVNC ✅ ; xterm.js (port série), SPICE ⬜ | 🟡 | M9 / M14 |
| Créer (assistant complet) | ✅ | M4 |
| Matériel : CPU, RAM, disques (ajouter, déplacer, agrandir, détacher, supprimer), cartes réseau, CD/DVD, ordre de démarrage | ✅ | M4 |
| Matériel avancé : passthrough PCI et USB, TPM, disque EFI, port série, audio, GPU virtuel, hotplug | ⬜ | M14 |
| Options (démarrage automatique, ordre de démarrage, OS, QEMU Agent, tablette, protection, mémoire NUMA…) | ⬜ | M14 |
| Cloud-init (utilisateur, mot de passe, clés SSH, IP, DNS) | ✅ | M4 |
| Cloud-init avancé (snippets `cicustom`) | ⬜ | M14 |
| Snapshots (créer, supprimer, restaurer) | ✅ | M4 |
| Clone (complet, lié), convertir en modèle | ✅ (convertir : ⬜) | M4 / M14 |
| Migration (en ligne, hors ligne, **distante** vers un autre cluster) | ✅ (distante : ⬜) | M4 / M14 |
| Sauvegarde et restauration de la machine | ✅ | M5 |
| Réplication de la machine | ⬜ | M8 |
| Pare-feu de la machine (règles, options, IPSet) | ⬜ | M7 |
| Permissions de la machine | ⬜ | M6 |
| Moniteur QEMU (`qm monitor`) | ⬜ | M14 |
| Historique des tâches de la machine | ✅ (onglet « Tâches », journal en direct ; consoles masquées par défaut) | M13 |
| Étiquettes (tags) et notes | 🟡 (lecture et édition codées, jamais exécutées en réel) | M13 |
| Résumé avec graphiques d'historique | ✅ (onglet « Performances ») | M13 |
| Supprimer | ✅ | M4 |

## Conteneur (LXC)

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Démarrer, éteindre, redémarrer, arrêt forcé | ✅ | M2 |
| Console : noVNC et terminal xterm.js | ✅ | M9 |
| Créer depuis un modèle (privilégié ou non) | ✅ (téléchargement de modèle : ⬜) | M4 / M14 |
| Ressources, disques, points de montage, réseau, DNS | ✅ | M4 |
| Options et fonctionnalités (démarrage automatique, nesting, FUSE, keyctl, montages CIFS/NFS) | ⬜ | M14 |
| Snapshots, clone, migration, sauvegarde, restauration, suppression | ✅ | M4 / M5 |
| Pare-feu, réplication, permissions, historique, tags | ⬜ | M7 / M8 / M6 / M13 |

## Stockage et fichiers

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Contenu : voir ISO, modèles, disques, sauvegardes, snippets | ✅ | M5 |
| **Téléverser** une ISO ou un modèle, **télécharger depuis une URL** (avec somme de contrôle) | ✅ (téléversement et téléchargement par URL validés en réel, avec sha256) | M5 |
| Modèles LXC officiels (TurnKey, distributions) : télécharger | ⬜ | M14 |
| Supprimer un volume, actions sur un volume, élagage (prune) manuel | ✅ (suppression de fichier validée en réel ; protection et élagage : non validés en réel, aucune sauvegarde ; copie d'un volume : ⬜) | M5 |

## Transverses

| Fonction de Proxmox | État | Jalon |
|---|---|---|
| Barre de tâches en bas (tâches en cours, journal d'une tâche) | 🟡 (page « Tâches » et tiroir de journal ; pas de barre permanente) | M13 |
| Recherche globale | ✅ (palette Ctrl+K) | M3 |
| Vues par dossier, par pool, par stockage | 🟡 (regroupement par nœud, pool, étiquette, type ; par stockage ⬜) | M13 |
| Thèmes clair / sombre | ✅ (sombre et Glass) | M3 |
| Langues | ⬜ (français seulement) | M15 |
| Tableau de bord temps réel | ✅ (flux SSE) | M3 |
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
