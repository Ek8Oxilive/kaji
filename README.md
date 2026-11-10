# Kaji

Le gouvernail de ton homelab (« kaji » signifie gouvernail en japonais). Interface web moderne pour piloter un cluster Proxmox VE : supervision, création et gestion des VM/LXC, et paramétrage du cluster (stockage, sauvegardes, utilisateurs, réseau, firewall, HA).

**Statut : en développement (jalon M1).** La feuille de route complète est dans [PLAN.md](PLAN.md).

## Fonctionnement
- Au premier lancement, tu crées le compte admin du dashboard (mot de passe de 12 caractères minimum).
- Les clusters Proxmox s'ajoutent depuis l'interface (hôte, utilisateur, token API) : rien à mettre dans un fichier de configuration.
- Les tokens sont stockés **chiffrés** en base (Fernet, clé dérivée de `KAJI_SECRET_KEY`). Les mots de passe sont hachés en argon2id.
- Session par cookie HttpOnly / SameSite=Strict.

> **Sécurité :** Kaji détient un token Proxmox aux droits étendus. Ne l'expose pas sur Internet : réseau local ou VPN, derrière HTTPS. Crée le compte admin avant toute exposition réseau.

## Stack
FastAPI (Python) · SQLAlchemy / SQLite · React + Vite + Tailwind (à venir) · Docker Compose (à venir)

## Interface web
Deux thèmes commutables depuis l'en-tête (le choix est mémorisé dans le navigateur) : **Sombre** et **Glass**. Pour en ajouter un, il suffit de définir un jeu de variables CSS dans `frontend/src/index.css` et de l'inscrire dans `frontend/src/lib/theme.tsx`.

Pour l'essayer en local (Node 20+), après avoir lancé le backend :
```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (les appels /api sont relayés vers le backend)
```
Écrans disponibles : première configuration, connexion, gestion des connexions Proxmox, et **dashboard** : résumé du cluster, nœuds (CPU, RAM, disque), machines VM/LXC en cartes avec filtres (recherche, état, type, nœud) et actions démarrer / redémarrer / éteindre / forcer l'arrêt. Les actions destructrices demandent confirmation, l'état attendu s'affiche tout de suite et la tâche Proxmox est suivie jusqu'au bout. Les données arrivent **en temps réel** (flux SSE, indicateur « En direct ») ; si le flux est indisponible, l'interface se rabat seule sur un rafraîchissement toutes les 10 s (cadence des statistiques Proxmox). **Ctrl+K** ouvre une palette de commandes : retrouver une machine et lui appliquer une action (les actions destructrices demandent toujours confirmation), changer de thème, aller aux connexions.

**Panneau Matériel** (bouton « Matériel » sur chaque machine) : mémoire, processeurs, swap (LXC), disques (agrandissement), lecteurs CD/DVD (monter/éjecter un ISO) et cartes réseau (bridge ou VNet SDN choisi dans une liste, VLAN, firewall, MAC conservée). L'ISO se choisit dans la liste des images du nœud ; si une liste est indisponible, la saisie manuelle reste possible. Le bouton **« + Nouvelle machine »** (ou la palette Ctrl+K) propose une **VM** ou un **conteneur LXC** ; l'**assistant de création de VM** compte 4 étapes : général (nœud, nom, identifiant proposé, pool, système), matériel (cœurs, mémoire, disque et stockage, ISO), réseau (bridge ou VNet, VLAN, firewall) et récapitulatif. Windows 11 reçoit automatiquement UEFI, TPM et disque EFI. L'assistant prévient quand aucun pool n'est choisi. Un onglet **Snapshots** permet de créer, supprimer et restaurer des points de restauration (la restauration exige de retaper le nom de la machine). Le bouton **« Cloner »** (sur chaque carte, y compris les modèles) copie une machine : clone complet ou lié, vers le même nœud ou un autre. Une ligne **« Emplacement »** permet de **migrer** la machine vers un autre nœud, après les vérifications préalables de Proxmox. Une **zone dangereuse** en bas du panneau Matériel permet de supprimer une machine arrêtée : la fenêtre liste les disques détruits et exige de retaper le nom. Pour une VM, un onglet **Cloud-init** règle l'utilisateur, le mot de passe, les clés SSH, l'IP et le DNS, et ajoute ou retire le lecteur cloud-init. Les disques s'**ajoutent, se détachent (données conservées), se rattachent, se déplacent et se suppriment définitivement** (en retapant le nom de la machine). On peut aussi **ajouter ou retirer une carte réseau** et régler l'**ordre de démarrage** d'une VM. Les changements qui ne s'appliquent qu'au redémarrage sont signalés « en attente ». L'ajout/suppression de disques et de cartes réseau est prévu dans une étape suivante.

## Captures d'écran

Un tour de toutes les pages et de leurs onglets, avec les fenêtres d'action. Elles ont été prises le 2026-11-09 sur un vrai cluster Proxmox à deux nœuds, **en lecture seule** : les fenêtres ont été ouvertes puis fermées sans rien valider. **Les noms des machines et les adresses IP du cluster sont remplacés par des exemples** (`media-server`, `dns-lxc`, `10.0.0.200`…) et les noms de domaine internes (réseau privé, certificats) sont masqués.

### Tableau de bord

Première page : l'état du cluster d'un coup d'œil, et toutes les machines.

![Résumé du cluster (nœuds en ligne, machines actives, RAM), cartes des nœuds (CPU, RAM, dis](docs/captures/dashboard-1-resume.jpg)

*Résumé du cluster (nœuds en ligne, machines actives, RAM), cartes des nœuds (CPU, RAM, disque) puis liste des machines avec recherche et filtres (état, type, nœud, pool, regroupement). L'indicateur « En direct » montre que les données arrivent en temps réel.*

![Chaque machine a sa carte ](docs/captures/dashboard-2-cartes.jpg)

*Chaque machine a sa carte : état, CPU, RAM et actions rapides (cloner, redémarrer, éteindre, forcer l'arrêt, démarrer). Un clic sur la carte ouvre la page de la machine.*

![Suite des cartes ](docs/captures/dashboard-3-cartes.jpg)

*Suite des cartes : VM et conteneurs LXC, en marche ou arrêtés.*

![Bas de la liste ](docs/captures/dashboard-4-bas.jpg)

*Bas de la liste : la machine de test `kaji-sandbox` (arrêtée) et `kaji-ct`, le conteneur qui héberge Kaji.*

![**Ctrl+K** ouvre la palette de commandes ](docs/captures/palette-ctrl-k.jpg)

***Ctrl+K** ouvre la palette de commandes : retrouver une machine, l'ouvrir, la cloner ou la démarrer, changer de thème, aller à une page.*

![Le thème **Glass**](docs/captures/theme-glass.jpg)

*Le thème **Glass**. Le thème Sombre est le thème par défaut ; le choix se fait en haut à droite et il est mémorisé dans le navigateur.*

### Créer une machine

Le bouton « + Nouvelle machine » propose une VM ou un conteneur LXC. Les captures s'arrêtent au récapitulatif : rien n'a été créé.

![Le choix entre une machine virtuelle et un conteneur LXC](docs/captures/nouvelle-machine-choix.jpg)

*Le choix entre une machine virtuelle et un conteneur LXC.*

![Assistant de création de VM, étape 1 ](docs/captures/creation-vm-1-general.jpg)

*Assistant de création de VM, étape 1 : nœud, nom, identifiant proposé, pool et système d'exploitation.*

![Étape 2 ](docs/captures/creation-vm-2-materiel.jpg)

*Étape 2 : cœurs, mémoire, type de processeur, disque et stockage, image ISO.*

![Étape 3 ](docs/captures/creation-vm-3-reseau.jpg)

*Étape 3 : carte réseau (bridge ou VNet SDN), modèle, VLAN et pare-feu.*

![Étape 4 ](docs/captures/creation-vm-4-recapitulatif.jpg)

*Étape 4 : récapitulatif. La machine ne démarre après sa création que si la case est cochée.*

![Assistant de création de conteneur LXC, étape 1 ](docs/captures/creation-lxc-1-general.jpg)

*Assistant de création de conteneur LXC, étape 1 : nœud, nom d'hôte, identifiant et pool.*

![Étape 2 ](docs/captures/creation-lxc-2-modele.jpg)

*Étape 2 : modèle (avec le bouton « Télécharger un modèle… » du catalogue officiel de Proxmox), ressources, disque, conteneur non privilégié par défaut.*

![Étape 3 ](docs/captures/creation-lxc-3-reseau.jpg)

*Étape 3 : réseau (DHCP ou adresse fixe), VLAN, pare-feu, mot de passe root et clés SSH (facultatifs).*

![Étape 4 ](docs/captures/creation-lxc-4-recapitulatif.jpg)

*Étape 4 : récapitulatif avant la création.*

### Page d'une machine virtuelle

Une page par machine, avec des onglets : Matériel, Options, Performances, Console, Snapshots, Cloud-init, Sauvegardes, Tâches. Exemples avec la VM de test `kaji-sandbox` (#115).

![Onglet **Matériel** ](docs/captures/vm-materiel-1.jpg)

*Onglet **Matériel** : mémoire, processeurs, ordre de démarrage. Au-dessus, les actions de la machine (Cloner, Démarrer, Convertir en modèle…) et les notes.*

![Suite du Matériel ](docs/captures/vm-materiel-2.jpg)

*Suite du Matériel : disques (agrandir, déplacer, détacher), cartes réseau, emplacement (migrer vers un autre nœud) et zone dangereuse (supprimer la machine).*

![Onglet **Options** ](docs/captures/vm-options-1.jpg)

*Onglet **Options** : démarrage au démarrage du nœud, ordre et délais.*

![Suite des Options ](docs/captures/vm-options-2.jpg)

*Suite des Options : protection contre la suppression, tablette USB, NUMA, ACPI, KVM, système invité et agent QEMU.*

![Fin des Options ](docs/captures/vm-options-3.jpg)

*Fin des Options : hotplug, description et bouton « Enregistrer ».*

![Onglet **Performances** ](docs/captures/vm-performances.jpg)

*Onglet **Performances** : processeur, mémoire, réseau et disque, sur l'heure, le jour, la semaine, le mois ou l'année (exemple sur une VM en marche).*

![Onglet **Console** ](docs/captures/vm-console.jpg)

*Onglet **Console** : console graphique (noVNC) ; elle exige une machine en marche. Chaque ouverture est journalisée.*

![Onglet **Snapshots** ](docs/captures/vm-snapshots.jpg)

*Onglet **Snapshots** : points de restauration à créer, restaurer et supprimer.*

![Onglet **Cloud-init** ](docs/captures/vm-cloud-init.jpg)

*Onglet **Cloud-init** : utilisateur, clés SSH, réseau ; ajoute d'abord le lecteur cloud-init.*

![Onglet **Sauvegardes** ](docs/captures/vm-sauvegardes.jpg)

*Onglet **Sauvegardes** : les sauvegardes de cette machine sur les stockages du nœud.*

![Onglet **Tâches** ](docs/captures/vm-taches.jpg)

*Onglet **Tâches** : l'historique des tâches Proxmox de la machine, avec la durée de chacune.*

### Page d'un conteneur LXC

Mêmes onglets, adaptés aux conteneurs (pas de Cloud-init). Exemples avec le conteneur `dns-lxc` (#104).

![Onglet **Matériel** d'un conteneur ](docs/captures/lxc-materiel-1.jpg)

*Onglet **Matériel** d'un conteneur : mémoire, processeurs, swap et disque racine.*

![Suite ](docs/captures/lxc-materiel-2.jpg)

*Suite : agrandir ou déplacer le disque, cartes réseau, emplacement et zone dangereuse (la suppression exige un conteneur arrêté).*

![Onglet **Options** ](docs/captures/lxc-options-1.jpg)

*Onglet **Options** : démarrage, protection, et fonctionnalités (nesting modifiable ; FUSE, keyctl et montages sont réservés à `root@pam` côté Proxmox).*

![Suite des Options ](docs/captures/lxc-options-2.jpg)

*Suite des Options : système, console, fuseau horaire et description.*

![Onglet **Console** ](docs/captures/lxc-console.jpg)

*Onglet **Console** : terminal dans le navigateur (xterm.js) ou écran noVNC.*

![Onglet **Snapshots** d'un conteneur](docs/captures/lxc-snapshots.jpg)

*Onglet **Snapshots** d'un conteneur.*

![Onglet **Sauvegardes** d'un conteneur](docs/captures/lxc-sauvegardes.jpg)

*Onglet **Sauvegardes** d'un conteneur.*

![Onglet **Tâches** d'un conteneur ](docs/captures/lxc-taches.jpg)

*Onglet **Tâches** d'un conteneur : historique des démarrages, extinctions, etc.*

![Onglet Performances d'un conteneur : CPU, mémoire, réseau et disque.](docs/captures/lxc-performances.jpg)

*Onglet Performances d'un conteneur : CPU, mémoire, réseau et disque.*

### Fenêtres d'action d'une machine

Chaque action ouvre une fenêtre. Les actions destructrices demandent une confirmation, et le nom de la machine est à retaper. Ces fenêtres ont été ouvertes puis fermées sans rien valider.

![Modifier la mémoire (et le ballooning)](docs/captures/dialogue-memoire.jpg)

*Modifier la mémoire (et le ballooning).*

![Ajouter un disque ](docs/captures/dialogue-disque.jpg)

*Ajouter un disque : stockage, taille et bus.*

![Ajouter une carte réseau](docs/captures/dialogue-carte-reseau.jpg)

*Ajouter une carte réseau.*

![Migrer vers un autre nœud, avec les vérifications préalables de Proxmox (disques locaux co](docs/captures/dialogue-migrer.jpg)

*Migrer vers un autre nœud, avec les vérifications préalables de Proxmox (disques locaux copiés, stockage de destination).*

![Créer un snapshot](docs/captures/dialogue-snapshot.jpg)

*Créer un snapshot.*

![Suspendre une VM en marche ](docs/captures/dialogue-suspendre.jpg)

*Suspendre une VM en marche : elle est figée en mémoire jusqu'à ce qu'on la reprenne (bouton « Reprendre »).*

![Convertir en modèle ](docs/captures/dialogue-convertir-modele.jpg)

*Convertir en modèle : irréversible, nom de la machine à retaper.*

![Supprimer une machine ](docs/captures/dialogue-supprimer-machine.jpg)

*Supprimer une machine : la fenêtre liste les disques détruits et exige de retaper le nom.*

![Cloner ](docs/captures/cloner.jpg)

*Cloner : clone complet (le clone lié est réservé aux modèles), nœud, stockage et pool de destination.*

![Modifier les processeurs : sockets, cœurs, type de processeur et limites.](docs/captures/vm-dialogue-processeurs.jpg)

*Modifier les processeurs : sockets, cœurs, type de processeur et limites.*

![Démarrage automatique : démarrer avec le nœud, ordre et délais.](docs/captures/vm-dialogue-demarrage.jpg)

*Démarrage automatique : démarrer avec le nœud, ordre et délais.*

![Agrandir un disque : la taille ne peut qu'augmenter (irréversible).](docs/captures/vm-dialogue-agrandir.jpg)

*Agrandir un disque : la taille ne peut qu'augmenter (irréversible).*

![Déplacer un disque vers un autre stockage.](docs/captures/vm-dialogue-deplacer.jpg)

*Déplacer un disque vers un autre stockage.*

![Détacher un disque : il reste en « non utilisé » et n'est pas détruit.](docs/captures/vm-dialogue-detacher.jpg)

*Détacher un disque : il reste en « non utilisé » et n'est pas détruit.*

![Éditeur de notes d'une machine.](docs/captures/vm-notes-editeur.jpg)

*Éditeur de notes d'une machine.*

![Liste des snapshots d'une machine.](docs/captures/vm-snapshots-liste.jpg)

*Liste des snapshots d'une machine.*

![Restaurer un snapshot : confirmation avec le nom de la machine à retaper.](docs/captures/vm-snapshot-restaurer.jpg)

*Restaurer un snapshot : confirmation avec le nom de la machine à retaper.*

![Supprimer un snapshot : confirmation explicite.](docs/captures/vm-snapshot-supprimer.jpg)

*Supprimer un snapshot : confirmation explicite.*

![Cloud-init : ajouter le lecteur de configuration.](docs/captures/vm-cloud-init-lecteur-1.jpg)

*Cloud-init : ajouter le lecteur de configuration.*

![Cloud-init : réglages et retrait du lecteur](docs/captures/vm-cloud-init-retrait.jpg)

*Cloud-init : réglages (utilisateur, clés SSH, réseau, DNS) ; retirer le lecteur demande une confirmation.*

![Une machine suspendue s'affiche « En pause » avec les boutons Reprendre et Forcer.](docs/captures/vm-en-pause.jpg)

*Une machine suspendue s'affiche « En pause » avec les boutons Reprendre et Forcer.*

![Page d'un modèle : cloner, et « Supprimer le modèle » (nom à retaper).](docs/captures/modele-page.jpg)

*Page d'un modèle : cloner, et « Supprimer le modèle » (nom à retaper).*

### Stockage

Les stockages du cluster, leur contenu, les ISO et les modèles.

![Page **Stockage** ](docs/captures/stockage.jpg)

*Page **Stockage** : un stockage par carte (type, espace utilisé, contenu autorisé).*

![Un clic ouvre le tiroir du stockage ](docs/captures/stockage-tiroir.jpg)

*Un clic ouvre le tiroir du stockage : fichiers (ISO, modèles), téléversement, téléchargement depuis une URL, catalogue de modèles, élagage des sauvegardes.*

![Catalogue officiel des modèles de conteneur de Proxmox (par défaut, seulement l'architectu](docs/captures/stockage-catalogue-modeles.jpg)

*Catalogue officiel des modèles de conteneur de Proxmox (par défaut, seulement l'architecture du nœud), avec recherche et filtre par section.*

![Ajouter un stockage ](docs/captures/stockage-ajouter.jpg)

*Ajouter un stockage : type, identifiant, chemin, contenu autorisé et nœuds concernés. Rien n'est écrit sans validation.*

![Téléverser une ISO ou un modèle, avec somme de contrôle facultative](docs/captures/stockage-televerser.jpg)

*Téléverser une ISO ou un modèle, avec somme de contrôle facultative.*

![Télécharger un fichier depuis une adresse http(s) par le nœud lui-même (les adresses local](docs/captures/stockage-url.jpg)

*Télécharger un fichier depuis une adresse http(s) par le nœud lui-même (les adresses locales sont refusées).*

![Modifier un stockage : contenus autorisés, nœuds, activation.](docs/captures/stockage-modifier.jpg)

*Modifier un stockage : contenus autorisés, nœuds, activation.*

![Retirer un stockage : Kaji ne supprime jamais les fichiers, seulement la déclaration.](docs/captures/stockage-retirer.jpg)

*Retirer un stockage : Kaji ne supprime jamais les fichiers, seulement la déclaration.*

![Élaguer les sauvegardes : aperçu de ce qui serait supprimé avant toute écriture.](docs/captures/stockage-elaguer.jpg)

*Élaguer les sauvegardes : aperçu de ce qui serait supprimé avant toute écriture.*

### Sauvegardes

Lire, lancer et planifier les sauvegardes.

![Page **Sauvegardes** ](docs/captures/sauvegardes.jpg)

*Page **Sauvegardes** : toutes les sauvegardes du cluster, avec recherche et filtres. Ici, aucune sauvegarde n'existe encore.*

![Lancer une sauvegarde ](docs/captures/sauvegardes-lancer.jpg)

*Lancer une sauvegarde : machine, stockage, mode (instantané, suspension, arrêt), compression et notes.*

![Onglet **Planifiées** ](docs/captures/sauvegardes-planifiees.jpg)

*Onglet **Planifiées** : les jobs de sauvegarde automatiques.*

![Nouveau job planifié ](docs/captures/sauvegardes-nouveau-job.jpg)

*Nouveau job planifié : jours, heure, stockage, machines (précises, un pool ou toutes) et mode.*

### Tâches

Le journal des tâches Proxmox, avec le compte qui les a lancées (« Kaji » signale celles qui viennent de l'interface).

![Liste des 100 dernières tâches, avec filtres (recherche, état, nœud)](docs/captures/taches-1.jpg)

*Liste des 100 dernières tâches, avec filtres (recherche, état, nœud).*

![Suite de la liste](docs/captures/taches-2.jpg)

*Suite de la liste. Cliquer sur une tâche ouvre son journal.*

![Suite de la liste ](docs/captures/taches-3.jpg)

*Suite de la liste : créations, clonages, conversions, suppressions…*

![Journal d'une tâche : sortie complète de Proxmox, sans secret.](docs/captures/taches-journal.jpg)

*Journal d'une tâche : sortie complète de Proxmox, sans secret.*

### Ceph

![Page **Ceph** ](docs/captures/ceph.jpg)

*Page **Ceph** : sur un cluster sans Ceph, la page explique comment l'installer et l'initialiser. Ce cluster n'a pas de Ceph : les fonctions d'écriture de Ceph n'ont donc été testées qu'avec un faux Proxmox.*

![Fenêtre d'installation de Ceph (non validée en réel : pas de Ceph sur ce cluster).](docs/captures/ceph-installer.jpg)

*Fenêtre d'installation de Ceph (non validée en réel : pas de Ceph sur ce cluster).*

![Création d'un moniteur Ceph (non validée en réel).](docs/captures/ceph-moniteur.jpg)

*Création d'un moniteur Ceph (non validée en réel).*

### Réseau et pare-feu

Interfaces des nœuds, pare-feu (datacenter, nœud, machine) et SDN. Tout changement est préparé « en attente » puis appliqué avec un verrou explicite.

![Interfaces du nœud (bridges, bonds, VLAN, cartes) et pare-feu du datacenter](docs/captures/reseau-1.jpg)

*Interfaces du nœud (bridges, bonds, VLAN, cartes) et pare-feu du datacenter. L'interface d'administration est marquée : la modifier est verrouillée.*

![Alias, IPSets, groupes de sécurité, zones SDN et pare-feu du nœud](docs/captures/reseau-2.jpg)

*Alias, IPSets, groupes de sécurité, zones SDN et pare-feu du nœud.*

![Ajouter une interface ](docs/captures/reseau-interface.jpg)

*Ajouter une interface : la modification est préparée, mais n'est appliquée qu'après un second geste.*

![Alias, IPSets et groupes de sécurité du pare-feu](docs/captures/reseau-alias-ipsets.jpg)

*Alias, IPSets et groupes de sécurité du pare-feu.*

![Options du pare-feu ](docs/captures/reseau-options-pare-feu.jpg)

*Options du pare-feu : les modifications dangereuses sont verrouillées, et l'aperçu dit pourquoi.*

![Règles du pare-feu (datacenter, nœud, machine, groupe) ](docs/captures/reseau-regles.jpg)

*Règles du pare-feu (datacenter, nœud, machine, groupe) : chaque action montre d'abord ses verrous.*

![Ajouter une zone SDN (les VNets, sous-réseaux, contrôleurs et IPAM ont leurs propres fenêt](docs/captures/reseau-sdn-zone.jpg)

*Ajouter une zone SDN (les VNets, sous-réseaux, contrôleurs et IPAM ont leurs propres fenêtres).*

![SDN : créer un VNet, en attente tant qu'il n'est pas appliqué.](docs/captures/reseau-sdn-vnet.jpg)

*SDN : créer un VNet, en attente tant qu'il n'est pas appliqué.*

![SDN : appliquer ou annuler les changements en attente (verrou explicite).](docs/captures/reseau-sdn-appliquer.jpg)

*SDN : appliquer ou annuler les changements en attente (verrou explicite).*

### HA et réplication

Haute disponibilité (ressources, règles) et réplication de stockage. Toute écriture est d'abord prévisualisée et exige la phrase `COUPURE POSSIBLE` quand elle présente un risque.

![État de la HA ](docs/captures/ha-1.jpg)

*État de la HA : quorum, maître, chien de garde, gestionnaires (LRM). Avec deux nœuds, la page prévient du risque.*

![Ressources HA, règles HA et jobs de réplication](docs/captures/ha-2.jpg)

*Ressources HA, règles HA et jobs de réplication.*

![Ajouter une machine à la HA ](docs/captures/ha-ressource.jpg)

*Ajouter une machine à la HA : état demandé, redémarrages et déplacements maximum, retour sur le nœud préféré.*

![Nouvelle règle HA ](docs/captures/ha-regle.jpg)

*Nouvelle règle HA : affinité de nœuds (avec priorités) ou affinité de ressources.*

![Nouveau job de réplication ](docs/captures/ha-replication.jpg)

*Nouveau job de réplication : machine, nœud cible, planification, débit maximal (exige du stockage ZFS).*

### Cluster

Informations de corosync en lecture seule.

![Informations du cluster ](docs/captures/cluster-1.jpg)

*Informations du cluster : nom, quorum, nombre de nœuds, version de configuration, liens.*

![Nœuds (votes, adresses, liens), QDevice et commandes `pvecm` à copier pour créer, joindre ](docs/captures/cluster-2.jpg)

*Nœuds (votes, adresses, liens), QDevice et commandes `pvecm` à copier pour créer, joindre ou retirer un nœud : Kaji ne modifie pas le cluster lui-même.*

### Datacenter

![Options du datacenter ](docs/captures/datacenter-1.jpg)

*Options du datacenter : clavier, langue, visionneuse de console, e-mail d'expédition, préfixe MAC, tâches parallèles, proxy, migration.*

![Notes du datacenter et début des notifications](docs/captures/datacenter-2.jpg)

*Notes du datacenter, puis la section **Notifications** qui commence.*

![Notifications et serveurs de métriques](docs/captures/datacenter-3.jpg)

*Section **Notifications** (lecture seule) : les cibles (ici `mail-to-root`, la cible intégrée de Proxmox, qui écrit à `root@pam`) avec la règle qui les utilise, et les règles (`default-matcher`). Aucun mot de passe ni jeton n'est affiché. Ajouter, modifier, supprimer ou tester une cible viendra ensuite. Dessous, les serveurs de métriques.*

![Ajouter un serveur de métriques (InfluxDB, Graphite…) ](docs/captures/datacenter-metriques.jpg)

*Ajouter un serveur de métriques (InfluxDB, Graphite…) : les secrets ne sont jamais affichés.*

### Page d'un nœud

Tout ce qui concerne un serveur Proxmox : supervision, système, services, disques.

![En-tête du nœud (CPU, RAM, disque), notes du nœud et historique (heure, jour, semaine, moi](docs/captures/noeud-1.jpg)

*En-tête du nœud (CPU, RAM, disque), notes du nœud et historique (heure, jour, semaine, mois, année).*

![Graphiques réseau et charge, console du nœud (verrouillée derrière une case à cocher) et b](docs/captures/noeud-2.jpg)

*Graphiques réseau et charge, console du nœud (verrouillée derrière une case à cocher) et boutons redémarrer / éteindre le nœud.*

![Version de Proxmox et du noyau, heure et DNS, configuration (DNS, fuseau horaire, fichier ](docs/captures/noeud-3.jpg)

*Version de Proxmox et du noyau, heure et DNS, configuration (DNS, fuseau horaire, fichier hosts) et mises à jour disponibles.*

![Dépôts de paquets (activer, désactiver, ajouter un dépôt standard) et certificats](docs/captures/noeud-4.jpg)

*Dépôts de paquets (activer, désactiver, ajouter un dépôt standard) et certificats.*

![Installer un certificat, certificats automatiques (ACME) et services du nœud (arrêter, red](docs/captures/noeud-5.jpg)

*Installer un certificat, certificats automatiques (ACME) et services du nœud (arrêter, redémarrer, recharger).*

![Fin des services, journal système et disques (état SMART)](docs/captures/noeud-6.jpg)

*Fin des services, journal système et disques (état SMART).*

![Groupes LVM, pools LVM-thin, répertoires, ZFS, et machines du nœud](docs/captures/noeud-7.jpg)

*Groupes LVM, pools LVM-thin, répertoires, ZFS, et machines du nœud.*

![Stockages et réseau du nœud](docs/captures/noeud-8.jpg)

*Stockages et réseau du nœud.*

![Éditeur des notes d'un nœud.](docs/captures/noeud-notes-editeur.jpg)

*Éditeur des notes d'un nœud.*

![Redémarrer un nœud : machines arrêtées, perte de quorum, machines protégées et nom à retaper.](docs/captures/noeud-redemarrer.jpg)

*Redémarrer un nœud : machines arrêtées, perte de quorum, machines protégées et nom à retaper.*

### Accès

Ce que le token de Kaji peut faire, et les droits Proxmox (lecture seule). Les pages « Connexions » et « Compte », qui touchent aux tokens et aux mots de passe, ne sont pas montrées.

![Mode administrateur (session temporaire) et liste des 27 droits dont Kaji a besoin](docs/captures/acces-1.jpg)

*Mode administrateur (session temporaire) et liste des 27 droits dont Kaji a besoin.*

![Suite des droits ](docs/captures/acces-2.jpg)

*Suite des droits : snapshots, clonage, migration, sauvegardes, console, HA, réplication, **notifications (lecture)**, datacenter…*

![Fin des droits, puis utilisateurs et groupes](docs/captures/acces-3.jpg)

*Fin des droits, puis utilisateurs et groupes.*

![Droits attribués (ACL) du token de Kaji, par chemin](docs/captures/acces-4.jpg)

*Droits attribués (ACL) du token de Kaji, par chemin.*

![Rôles Proxmox et leurs privilèges](docs/captures/acces-5.jpg)

*Rôles Proxmox et leurs privilèges.*

![Fin des rôles et realms d'authentification](docs/captures/acces-6.jpg)

*Fin des rôles et realms d'authentification.*

## Déploiement
`docker compose up -d --build` lance le backend et le frontend (nginx). Guide complet, HTTPS, sauvegarde, mise à jour et mot de passe perdu : [docs/deploiement.md](docs/deploiement.md).

## Démarrage (backend)
Prérequis : Python 3.12+.

```bash
git clone https://github.com/Ek8Oxilive/kaji.git && cd kaji
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # colle le résultat dans KAJI_SECRET_KEY
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```
La documentation interactive de l'API est sur http://127.0.0.1:8000/docs.

### API (jalon M1)
Toutes les routes, sauf `/api/health` et `/api/auth/*`, demandent une session.

| Route | Rôle |
|---|---|
| `POST /api/auth/setup` · `login` · `logout` · `GET /api/auth/me` | Compte admin et session. `logout` **révoque** la session côté serveur. |
| `POST /api/auth/logout-all` | Révoque toutes les sessions du compte |
| `POST /api/auth/password` | Change le mot de passe (l'actuel est exigé) ; révoque les autres sessions |
| `GET/POST /api/connections` | Lister / ajouter un cluster Proxmox |
| `GET/PATCH/DELETE /api/connections/{id}` | Voir / modifier / supprimer (le token n'est jamais renvoyé) |
| `POST /api/connections/test` | Tester des identifiants avant de les enregistrer |
| `POST /api/connections/{id}/test` | Tester une connexion enregistrée |
| `GET /api/connections/{id}/cluster/status` | Nom du cluster, quorum, nœuds en ligne ou non |
| `GET /api/connections/{id}/nodes` | Nœuds : CPU, RAM, disque, uptime |
| `GET /api/connections/{id}/guests` | Liste unifiée des VM (qemu) et LXC, filtrable par `?node=` |
| `GET /api/connections/{id}/storages` | Stockages et usage |
| `GET /api/connections/{id}/events` | Flux temps réel (SSE) : un instantané de l'état du cluster (statut, nœuds, machines) à chaque changement. Un seul interrogateur Proxmox par cluster, partagé par tous les navigateurs ; il s'arrête quand le dernier part. |
| `POST /api/connections/{id}/guests/{node}/{qemu\|lxc}/{vmid}/{action}` | `start`, `shutdown`, `reboot`, `stop`. Renvoie l'UPID de la tâche. `stop` (coupure brutale) exige `{"confirm": true}`. |
| `GET /api/connections/{id}/tasks/{node}/{upid}` | État d'une tâche (`ok` si terminée avec succès) ; `/log` pour son journal |
| `GET /api/connections/{id}/guests/{node}/{type}/{vmid}/config` | Matériel décomposé (CPU, RAM, disques, cartes réseau) et changements en attente |
| `PATCH …/config` | Modifie CPU (cœurs, sockets, type), RAM, balloon, swap (LXC), réseau (bridge, VLAN, firewall ; la MAC est conservée), ISO monté ou éjecté. Seuls des champs validés sont acceptés. |
| `POST …/guests/{node}/{type}/{vmid}/nets` · `DELETE …/nets/{netN}?confirm=true` | Ajouter une carte réseau (index libre choisi, MAC attribuée par Proxmox, IP DHCP/statique pour un LXC) / la retirer (la MAC est perdue, confirmation exigée) |
| `PATCH …/config` avec `boot` | Ordre de démarrage d'une VM (`["scsi0","ide2","net0"]`) |
| `POST …/guests/{node}/{type}/{vmid}/disks` | Ajoute un disque (VM : bus et stockage ; LXC : point de montage avec chemin validé) |
| `POST …/disks/{key}/detach` | Détache un disque : il devient « non utilisé », **données conservées** |
| `POST …/disks/unusedN/reattach` | Rattache un disque non utilisé |
| `DELETE …/disks/unusedN?confirm=true&name=<machine>` | Détruit **définitivement** un disque non utilisé ; exige le nom exact de la machine |
| `POST …/disks/{key}/move` | Déplace un disque vers un autre stockage (`confirm` exigé, ancien emplacement conservé sauf `delete_source`) |
| `POST …/guests/{node}/{type}/{vmid}/clone` | Clone une VM ou un LXC (complet, ou lié si la source est un modèle) ; nom, identifiant (libre par défaut), nœud et stockage de destination, pool |
| `DELETE …/guests/{node}/{type}/{vmid}?confirm=true&name=<machine>` | Supprime **définitivement** une machine et ses disques. Exige : machine arrêtée, nom exact, non protégée (par Proxmox ni par `KAJI_PROTECTED_VMIDS`). Options `purge`, `destroy_unreferenced`. |
| `GET …/guests/{node}/{type}/{vmid}/migrate` | Vérifications préalables de Proxmox : nœuds possibles, disques locaux, ressources bloquantes (repli sur les nœuds en ligne si indisponibles) |
| `POST …/guests/{node}/{type}/{vmid}/migrate` | Migre la machine vers un autre nœud ; une machine en marche exige `confirm` (VM : à chaud ; LXC : arrêt, migration, redémarrage) |
| `POST …/resize` | Agrandit un disque de N Go (irréversible, exige `{"confirm": true}`) |
| `GET\|POST …/guests/{node}/{type}/{vmid}/snapshots` | Lister / créer un snapshot (avec la mémoire pour une VM en marche) |
| `DELETE …/snapshots/{name}?confirm=true` | Supprimer un snapshot (confirmation exigée) |
| `POST …/snapshots/{name}/rollback` | Restaurer la machine à ce snapshot, exige `{"confirm": true}` (tout ce qui a changé depuis est perdu) |
| `GET /api/connections/{id}/nodes/{node}/bridges` | Réseaux sélectionnables pour une carte réseau : bridges locaux et VNets SDN (la liste reste utilisable si le SDN est absent ou illisible) |
| `POST /api/connections/{id}/nodes/{node}/qemu` | Crée une VM (nom, mémoire, CPU, disque, réseau, ISO, pool, type d'OS ; Windows 11 reçoit UEFI, TPM et disque EFI). Chaque champ est validé ; l'identifiant est choisi automatiquement si absent. |
| `POST /api/connections/{id}/nodes/{node}/lxc` | Crée un conteneur LXC depuis un modèle déjà présent (non privilégié par défaut). Mot de passe root et clés SSH facultatifs : **jamais journalisés**, jamais renvoyés. |
| `GET\|PATCH …/guests/{node}/qemu/{vmid}/cloudinit` | Cloud-init d'une VM : utilisateur, mot de passe (**jamais relu ni journalisé**), clés SSH (envoyées encodées en URL comme l'exige Proxmox), IP, DNS, domaine ; `clear` supprime des réglages |
| `POST\|DELETE …/cloudinit/drive` | Ajoute (bus IDE libre) ou retire le lecteur cloud-init, sans toucher aux réglages |
| `GET /api/connections/{id}/nextid` · `/pools` · `/nodes/{node}/storages?content=` | Prochain identifiant libre, pools, stockages d'un nœud acceptant un type de contenu |
| `GET /api/connections/{id}/nodes/{node}/templates` | Modèles de conteneur : déjà présents sur les stockages du nœud, et catalogue téléchargeable (avec l'architecture) |
| `GET /api/connections/{id}/nodes/{node}/isos` | Images ISO disponibles sur les stockages actifs du nœud |
| `GET /api/audit` | Journal d'audit des actions (qui, quoi, quand, résultat) |

> **Droits Proxmox (M2).** Les actions demandent plus que la lecture seule. Pour limiter les risques, donne le rôle `PVEVMAdmin` au token **uniquement sur les machines concernées** (`pveum aclmod /vms/<vmid> -user kaji@pve -role PVEVMAdmin`) et garde `PVEAuditor` sur `/`.

Côté Proxmox, crée un utilisateur et un token dédiés (`pveum user token add kaji@pve kaji --privsep 0`), puis saisis l'hôte, `kaji@pve`, l'ID `kaji` et le secret dans Kaji.

### Configuration (`.env`)
| Variable | Rôle | Défaut |
|---|---|---|
| `KAJI_SECRET_KEY` | Chiffrement des tokens et signature des sessions. **Obligatoire**, à garder secrète. Si tu la perds, les connexions enregistrées sont à ressaisir. | – |
| `KAJI_COOKIE_SECURE` | Cookie de session en `Secure`. Mettre `false` seulement en HTTP sur le réseau local. | `true` |
| `KAJI_TRUST_PROXY` | Derrière un reverse proxy **de confiance** uniquement : le limiteur de connexions utilise l'IP ajoutée par le proxy (`X-Forwarded-For`). Sinon l'en-tête est ignoré, car falsifiable. | `false` |
| `KAJI_AUDIT_RETENTION_DAYS` | Durée de conservation de l'audit ; les entrées plus anciennes sont supprimées (0 = indéfiniment) | `365` |
| `KAJI_PROTECTED_VMIDS` | Identifiants de machines que Kaji refuse de supprimer, quoi qu'il arrive (ex. `105,108`). **Recommandé** pour tes machines importantes. | vide |
| `DATABASE_URL` | Base de données | `sqlite:///./kaji.db` |
| `KAJI_SESSION_HOURS` | Durée de session | `12` |

## Tests
```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

## Contribuer
- Une branche par fonctionnalité (`feat/...`, `fix/...`), une PR par bloc cohérent, aucun commit direct sur `main`.
- Messages de commit en [Conventional Commits](https://www.conventionalcommits.org/), avec le **jalon** de [PLAN.md](PLAN.md) et la zone en scope : `type(Mx/zone): message`.
  - Exemples : `feat(M2/actions): démarrer et arrêter une VM`, `fix(M1/auth): expiration du cookie`, `docs(M0): précise le démarrage`.
  - Types : `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`. Hors jalon (outillage, docs générales) : `chore(repo): ...`.
- Chaque PR est rattachée au **milestone GitHub** correspondant (M0 à M10).
- La CI (pytest) doit être verte avant merge.

## Licence
[MIT](LICENSE)

Le bouton **« Compte »** (bas de la barre latérale) ouvre une fenêtre pour **changer le mot de passe** (l'actuel est exigé, 12 caractères minimum) et **déconnecter toutes les sessions**.

## Durcissement
- **Sessions révocables** : chaque jeton renvoie à une session enregistrée en base ; la déconnexion, le changement de mot de passe et `logout-all` les suppriment, un jeton copié devient donc inutilisable.
- **Base SQLite en `600`** (hash du mot de passe, tokens chiffrés, audit) : créée ainsi, ou resserrée au démarrage.
- **Audit purgé** au-delà de `KAJI_AUDIT_RETENTION_DAYS`.
- **En-têtes** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, et `Cache-Control: no-store` sur toute l'API.
- Dépendances **à version fixée**, mises à jour par Dependabot.
- **Migrations de schéma** : versionnées, **sauvegardées** (copie `kaji.db.bak-vN-…` en `600` avant toute migration, les 5 dernières sont gardées), **atomiques** (une transaction par migration, schéma compris) ; Kaji refuse de démarrer sur une base plus récente que le code. `python -m app.migrations status` (ou `upgrade`) depuis `backend/`.
- Non couvert : l'authentification à deux facteurs, la récupération d'un mot de passe oublié (supprimer `kaji.db` recrée le compte, mais efface aussi les connexions).

## Sécurité des secrets
Les erreurs de validation de l'API **ne renvoient jamais les valeurs saisies** (mots de passe, secrets de token) : par défaut FastAPI recopie le corps de la requête dans l'erreur, ce que Kaji désactive. Les mots de passe de conteneur ne sont ni journalisés ni écrits dans l'audit.
