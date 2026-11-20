# Captures d'écran

> Retour au [README](../README.md). Un tour de toutes les pages de Kaji. **Le dépôt est public : noms de machines et adresses IP sont remplacés par des exemples.**

Un tour de toutes les pages et de leurs onglets, avec les fenêtres d'action. Elles ont été prises le 2026-11-09 sur un vrai cluster Proxmox à deux nœuds, **en lecture seule** : les fenêtres ont été ouvertes puis fermées sans rien valider. **Les noms des machines et les adresses IP du cluster sont remplacés par des exemples** (`media-server`, `dns-lxc`, `10.0.0.200`…) et les noms de domaine internes (réseau privé, certificats) sont masqués.

### Tableau de bord

Première page : l'état du cluster d'un coup d'œil, et toutes les machines.

![Résumé du cluster (nœuds en ligne, machines actives, RAM), cartes des nœuds (CPU, RAM, dis](captures/dashboard-1-resume.jpg)

*Résumé du cluster (nœuds en ligne, machines actives, RAM), cartes des nœuds (CPU, RAM, disque) puis liste des machines avec recherche et filtres (état, type, nœud, pool, regroupement). L'indicateur « En direct » montre que les données arrivent en temps réel.*

![Chaque machine a sa carte ](captures/dashboard-2-cartes.jpg)

*Chaque machine a sa carte : état, CPU, RAM et actions rapides (cloner, redémarrer, éteindre, forcer l'arrêt, démarrer). Un clic sur la carte ouvre la page de la machine.*

![Suite des cartes ](captures/dashboard-3-cartes.jpg)

*Suite des cartes : VM et conteneurs LXC, en marche ou arrêtés.*

![Bas de la liste ](captures/dashboard-4-bas.jpg)

*Bas de la liste : la machine de test `kaji-sandbox` (arrêtée) et `kaji-ct`, le conteneur qui héberge Kaji.*

![**Ctrl+K** ouvre la palette de commandes ](captures/palette-ctrl-k.jpg)

***Ctrl+K** ouvre la palette de commandes : retrouver une machine, l'ouvrir, la cloner ou la démarrer, changer de thème, aller à une page.*

![Le thème **Glass**](captures/theme-glass.jpg)

*Le thème **Glass**. Le thème Sombre est le thème par défaut ; le choix se fait en haut à droite et il est mémorisé dans le navigateur.*

![Filtres du tableau de bord (recherche, état, type, nœud, pool) et regroupement **par nœud**](captures/dashboard-par-noeud.jpg)

*Filtres du tableau de bord (recherche, état, type, nœud, pool) et regroupement **par nœud** : chaque nœud a sa liste de machines.*

![Regroupement **par pool**](captures/dashboard-par-pool.jpg)

*Regroupement **par pool** : ici le pool `kaji-test` (le bac à sable) et les machines sans pool.*

![Regroupement **par stockage**](captures/dashboard-par-stockage.jpg)

*Regroupement **par stockage** : les machines sont classées selon le stockage qui porte leurs disques (ici tout est sur `local-lvm`). Une machine dont les disques sont sur plusieurs stockages apparaît dans chacun.*

![Regroupement **par type**](captures/dashboard-par-type.jpg)

*Regroupement **par type** : conteneurs LXC d'un côté, machines virtuelles de l'autre (les modèles ont leur groupe). Les regroupements par nœud, pool, étiquette et stockage se choisissent dans la même liste.*

![Repli « Plus d'actions » d'une carte](captures/dashboard-plus-d-actions.jpg)

*Chaque carte a un repli **« Plus d'actions »** : sur une VM en marche, Suspendre, Hiberner et Réinitialiser (Reprendre quand elle est en pause, Convertir en modèle quand elle est arrêtée), avec les mêmes confirmations que sur la page de la machine.*

### Thèmes : Sombre, Glass, Clair et Auto

Quatre thèmes (`docs/themes.md`) : **Sombre**, **Glass**, **Clair** (contrastes WCAG AA vérifiés) et **Auto**, qui suit le réglage clair / sombre du système. Le sélecteur est en haut de chaque page (dans le menu ☰ sur petit écran) et dans la palette de commandes (Ctrl K).

![Tableau de bord en thème clair](captures/theme-clair-tableau-de-bord.jpg)

*Tableau de bord en thème Clair : cartes blanches, accent bleu foncé, pastilles d'état lisibles sur fond clair.*

![Graphiques en thème clair](captures/theme-clair-graphiques.jpg)

*Graphiques du nœud en thème Clair : les deux séries (bleu et orange) ont leurs propres teintes, plus foncées, pour rester distinctes sur fond blanc.*

![Assistant de création en thème clair](captures/theme-clair-fenetre.jpg)

*Fenêtres, champs et avertissements en thème Clair.*

![Menu avec les quatre thèmes](captures/theme-clair-menu.jpg)

*Dans le menu ☰ d'un petit écran, le sélecteur propose Sombre, Glass, Clair et Auto.*

### Petits écrans et langue (français / anglais)

Sous 768 px (téléphone, petit PC), la barre latérale devient une barre du haut avec un menu ☰ qui ouvre un tiroir de navigation ; la barre de tâches est repliée par défaut. Le sélecteur **FR | EN** est à côté du thème ; le choix est gardé dans le navigateur (`docs/interface-mobile.md`, `docs/interface-langue.md`).

![Tableau de bord en anglais sur petit écran](captures/mobile-anglais.jpg)

*Tableau de bord en anglais sur petit écran : barre du haut (menu, sélecteur FR | EN, thème), cartes en deux colonnes, barre de tâches en bas.*

![Menu tiroir de la navigation sur petit écran](captures/mobile-menu.jpg)

*Le menu ☰ ouvre la navigation dans un tiroir (fermé par ✕, Échap, un clic à l'extérieur ou le choix d'une page).*

![Tableau de bord en français à environ 390 px](captures/mobile-francais.jpg)

*Le même écran en français à environ 390 px de large : les boutons passent à la ligne au lieu de déborder, la barre de tâches est repliée.*

### Créer une machine

Le bouton « + Nouvelle machine » propose une VM ou un conteneur LXC. Les captures s'arrêtent au récapitulatif : rien n'a été créé.

![Le choix entre une machine virtuelle et un conteneur LXC](captures/nouvelle-machine-choix.jpg)

*Le choix entre une machine virtuelle et un conteneur LXC.*

![Assistant de création de VM, étape 1 ](captures/creation-vm-1-general.jpg)

*Assistant de création de VM, étape 1 : nœud, nom, identifiant proposé, pool et système d'exploitation.*

![Étape 2 ](captures/creation-vm-2-materiel.jpg)

*Étape 2 : cœurs, mémoire, type de processeur, disque et stockage, image ISO.*

![Étape 3 ](captures/creation-vm-3-reseau.jpg)

*Étape 3 : carte réseau (bridge ou VNet SDN), modèle, VLAN et pare-feu.*

![Étape 4 ](captures/creation-vm-4-recapitulatif.jpg)

*Étape 4 : récapitulatif. La machine ne démarre après sa création que si la case est cochée.*

![Assistant de création de conteneur LXC, étape 1 ](captures/creation-lxc-1-general.jpg)

*Assistant de création de conteneur LXC, étape 1 : nœud, nom d'hôte, identifiant et pool.*

![Étape 2 ](captures/creation-lxc-2-modele.jpg)

*Étape 2 : modèle (avec le bouton « Télécharger un modèle… » du catalogue officiel de Proxmox), ressources, disque, conteneur non privilégié par défaut.*

![Étape 3 ](captures/creation-lxc-3-reseau.jpg)

*Étape 3 : réseau (DHCP ou adresse fixe), VLAN, pare-feu, mot de passe root et clés SSH (facultatifs).*

![Étape 4 ](captures/creation-lxc-4-recapitulatif.jpg)

*Étape 4 : récapitulatif avant la création.*

### Page d'une machine virtuelle

Une page par machine, avec des onglets : Matériel, Options, Périphériques (VM), Performances, Console, Snapshots, Cloud-init, Sauvegardes, Tâches. Exemples avec la VM de test `kaji-sandbox` (#115).

![Onglet **Matériel** ](captures/vm-materiel-1.jpg)

*Onglet **Matériel** : mémoire, processeurs, ordre de démarrage. Au-dessus, les actions de la machine (Cloner, Démarrer, Convertir en modèle…) et les notes.*

![Suite du Matériel ](captures/vm-materiel-2.jpg)

*Suite du Matériel : disques (agrandir, déplacer, détacher), cartes réseau, emplacement (migrer vers un autre nœud) et zone dangereuse (supprimer la machine).*

![Périphériques PCI, USB et répertoires d'une VM](captures/vm-passthrough-liste.jpg)

*Matériel d'une VM, section « Périphériques PCI, USB et répertoires » : trois périphériques ajoutés par correspondance (PCI sans ROM, USB sans USB 3, répertoire en cache auto). Les changements ne s'appliquent qu'après un arrêt complet de la machine.*

![Ajouter un périphérique PCI par correspondance](captures/vm-passthrough-ajout.jpg)

*Ajouter un périphérique PCI : on choisit une correspondance du datacenter et les options (PCIe, ROM, carte graphique principale) ; l'aperçu montre la ligne écrite dans la configuration.*

![Retirer un périphérique](captures/vm-passthrough-retrait.jpg)

*Retirer un périphérique de la configuration de la VM : le périphérique lui-même et la correspondance ne sont pas touchés.*

![Onglet **Options** ](captures/vm-options-1.jpg)

*Onglet **Options** : démarrage au démarrage du nœud, ordre et délais.*

![Suite des Options ](captures/vm-options-2.jpg)

*Suite des Options : protection contre la suppression, tablette USB, NUMA, ACPI, KVM, système invité et agent QEMU.*

![Fin des Options ](captures/vm-options-3.jpg)

*Fin des Options : hotplug, description et bouton « Enregistrer ».*

![Onglet Périphériques d'une machine](captures/vm-peripheriques-1.jpg)

*Onglet **Périphériques** (VM) : carte d'affichage (type, mémoire, presse-papiers), **ports série en mode socket seulement** (jamais un périphérique de l'hôte) et carte son virtuelle. Les changements sont lus chez Proxmox après l'enregistrement.*

![Options d'un disque de VM](captures/vm-options-disque.jpg)

*Matériel d'une VM, **Options…** d'un disque : cache, discard, E/S asynchrones, iothread, SSD, détection des zéros, sauvegarde, lecture seule, réplication et limites de débit et d'IOPS. Seules les options modifiées sont envoyées (volume et taille conservés) ; « Défaut de Proxmox » retire l'option.*

![Options d'une carte réseau](captures/vm-options-reseau.jpg)

*Bouton **Options…** d'une carte réseau (VM ou conteneur) : limite de débit, MTU, files multiples, VLAN autorisés (trunks) et câble débranché ; l'adresse MAC, le bridge et le VLAN ne changent pas.*

![Options du processeur d'une VM](captures/vm-options-cpu.jpg)

*Options du processeur : poids (`cpuunits`) et limite d'utilisation (`cpulimit`). Les cœurs autorisés (`affinity`) et les hugepages ne sont pas proposés : Proxmox les réserve à `root@pam`. Un réglage risqué (cache `unsafe`, sauvegarde désactivée, câble débranché) demande d'abord une case « J'accepte ».*

![Migrer une VM vers un autre cluster](captures/vm-migration-distante.jpg)

*Bouton **Autre cluster…** (onglet Matériel) : migration vers un autre cluster Proxmox, fonction expérimentale chez Proxmox. Le jeton du cluster distant est en écriture seule, l'empreinte de son certificat est obligatoire, les adresses de boucle locale ou réservées sont refusées, et supprimer l'original exige le nom retapé et la phrase `COUPURE POSSIBLE`. Fenêtre ouverte puis fermée sans valider.*

![Générateur aléatoire et watchdog](captures/vm-peripheriques-2.jpg)

*Suite de l'onglet : **générateur aléatoire** (source toujours `/dev/urandom`, non modifiable) et **watchdog** matériel virtuel (modèle, action). Une demande qui retirerait l'affichage de la console (`none`) exige une confirmation décidée par le serveur.*

![Carte **Démarrage et sécurité**](captures/vm-efi-tpm-ajout.jpg)

*Carte **Démarrage et sécurité** : BIOS (`seabios` ou `ovmf`), **ajout d'un disque EFI** (stockage, taille des variables, clés pré-enrôlées) et **d'un TPM virtuel** (stockage, version).*

![Changer le BIOS exige une **confirmation décidée par le serveur**](captures/vm-efi-tpm-confirmation.jpg)

*Changer le BIOS exige une **confirmation décidée par le serveur** : rien n'est écrit tant qu'on ne clique pas sur « Confirmer et enregistrer ».*

![Une fois créés](captures/vm-efi-tpm-present.jpg)

*Une fois créés, le disque EFI et le TPM sont affichés (« Présent sur… »). Un existant n'est jamais remplacé : on peut seulement le **retirer** (confirmation), son volume reste alors en « non utilisé » dans l'onglet Matériel.*

![Onglet **Performances** ](captures/vm-performances.jpg)

*Onglet **Performances** : processeur, mémoire, réseau et disque, sur l'heure, le jour, la semaine, le mois ou l'année (exemple sur une VM en marche).*

![Onglet **Console** ](captures/vm-console.jpg)

*Onglet **Console** : console graphique (noVNC) ; elle exige une machine en marche. Chaque ouverture est journalisée.*

![Terminal série d'une VM](captures/vm-terminal-serie.jpg)

*Bouton « Terminal série » de l'onglet Console d'une VM : terminal (xterm.js) sur son port série de type socket (ajouté dans l'onglet Périphériques, VM démarrée). Ici, une VM de test sans système : Proxmox répond « starting serial terminal on interface serial0 ».*

![Onglet Console d'une VM avec le bouton SPICE](captures/vm-console-spice.jpg)

*Onglet Console d'une VM : « Ouvrir la console » (noVNC), **« SPICE (virt-viewer) »** et « Terminal série ». Le bouton SPICE télécharge un fichier `.vv` (ticket à usage unique, ~40 s) à ouvrir tout de suite avec virt-viewer ; la VM doit avoir une carte d'affichage `qxl` (onglet Périphériques). Un conteneur a aussi ce bouton (`docs/api/console-spice.md`).*

![Onglet **Snapshots** ](captures/vm-snapshots.jpg)

*Onglet **Snapshots** : points de restauration à créer, restaurer et supprimer.*

![Onglet **Cloud-init** ](captures/vm-cloud-init.jpg)

*Onglet **Cloud-init** : utilisateur, clés SSH, réseau ; ajoute d'abord le lecteur cloud-init.*

![Onglet **Sauvegardes** ](captures/vm-sauvegardes.jpg)

*Onglet **Sauvegardes** : les sauvegardes de cette machine sur les stockages du nœud.*

![Onglet **Tâches** ](captures/vm-taches.jpg)

*Onglet **Tâches** : l'historique des tâches Proxmox de la machine, avec la durée de chacune.*

![Onglet Réplication d'une machine](captures/vm-replication.jpg)

*Onglet **Réplication** : les jobs de la machine (ici aucun), avec le bouton « Nouveau job… ».*

![Nouveau job de réplication, aperçu bloqué](captures/vm-replication-nouveau-job.jpg)

*Nouveau job de réplication : l'**aperçu** dit ce qui bloque sans rien écrire. Ici, aucun stockage ZFS sur le cluster et le disque est sur `local-lvm` : « Appliquer » reste grisé.*

![Onglet Permissions d'une machine](captures/vm-permissions.jpg)

*Onglet **Permissions** : les droits qui s'appliquent à la machine, posés sur elle ou hérités de `/vms` et de `/`. « Modifier une ACL… » ouvre la fenêtre de la page Accès avec le chemin de la machine prérempli.*

![Étiquettes d'une machine](captures/vm-etiquettes-editeur.jpg)

*Étiquettes d'une machine : « Modifier » à côté du nom ouvre un champ pour ajouter une étiquette, puis Enregistrer.*

![Onglet Moniteur d'une VM](captures/vm-moniteur.jpg)

*Onglet **Moniteur** (VM en marche) : commandes `info …` de QEMU en lecture seule, choisies dans une liste (jamais de commande libre). Proxmox 9 refuse ces commandes au jeton de Kaji (403, message explicatif) : l'onglet affiche donc aussi **les commandes à copier** : `qm monitor <id>` (ouvre le moniteur dans la console du nœud) puis la commande choisie à taper dedans.*

![Options d'une VM : clavier et redémarrage](captures/vm-options-clavier-reboot.jpg)

*Onglet **Options** : disposition du clavier de la console VNC (retirable) et « Autoriser le redémarrage » ; le désactiver demande une confirmation décidée par le serveur.*

### Page d'un conteneur LXC

Mêmes onglets, adaptés aux conteneurs (pas de Cloud-init). Exemples avec le conteneur `dns-lxc` (#104).

![Onglet **Matériel** d'un conteneur ](captures/lxc-materiel-1.jpg)

*Onglet **Matériel** d'un conteneur : mémoire, processeurs, swap et disque racine.*

![Suite ](captures/lxc-materiel-2.jpg)

*Suite : agrandir ou déplacer le disque, cartes réseau, emplacement et zone dangereuse (la suppression exige un conteneur arrêté).*

![Onglet **Options** ](captures/lxc-options-1.jpg)

*Onglet **Options** : démarrage, protection, et fonctionnalités (nesting modifiable ; FUSE, keyctl et montages sont réservés à `root@pam` côté Proxmox).*

![Suite des Options ](captures/lxc-options-2.jpg)

*Suite des Options : système, console, fuseau horaire et description.*

![Onglet **Console** ](captures/lxc-console.jpg)

*Onglet **Console** : terminal dans le navigateur (xterm.js) ou écran noVNC.*

![Onglet **Snapshots** d'un conteneur](captures/lxc-snapshots.jpg)

*Onglet **Snapshots** d'un conteneur.*

![Onglet **Sauvegardes** d'un conteneur](captures/lxc-sauvegardes.jpg)

*Onglet **Sauvegardes** d'un conteneur.*

![Onglet **Tâches** d'un conteneur ](captures/lxc-taches.jpg)

*Onglet **Tâches** d'un conteneur : historique des démarrages, extinctions, etc.*

![Onglet Performances d'un conteneur : CPU, mémoire, réseau et disque.](captures/lxc-performances.jpg)

*Onglet Performances d'un conteneur : CPU, mémoire, réseau et disque.*

### Fenêtres d'action d'une machine

Chaque action ouvre une fenêtre. Les actions destructrices demandent une confirmation, et le nom de la machine est à retaper. Ces fenêtres ont été ouvertes puis fermées sans rien valider.

![Modifier la mémoire (et le ballooning)](captures/dialogue-memoire.jpg)

*Modifier la mémoire (et le ballooning).*

![Ajouter un disque ](captures/dialogue-disque.jpg)

*Ajouter un disque : stockage, taille et bus.*

![Ajouter une carte réseau](captures/dialogue-carte-reseau.jpg)

*Ajouter une carte réseau.*

![Migrer vers un autre nœud, avec les vérifications préalables de Proxmox (disques locaux co](captures/dialogue-migrer.jpg)

*Migrer vers un autre nœud, avec les vérifications préalables de Proxmox (disques locaux copiés, stockage de destination).*

![Créer un snapshot](captures/dialogue-snapshot.jpg)

*Créer un snapshot.*

![Suspendre une VM en marche ](captures/dialogue-suspendre.jpg)

*Suspendre une VM en marche : elle est figée en mémoire jusqu'à ce qu'on la reprenne (bouton « Reprendre »).*

![Convertir en modèle ](captures/dialogue-convertir-modele.jpg)

*Convertir en modèle : irréversible, nom de la machine à retaper.*

![Supprimer une machine ](captures/dialogue-supprimer-machine.jpg)

*Supprimer une machine : la fenêtre liste les disques détruits et exige de retaper le nom.*

![Cloner ](captures/cloner.jpg)

*Cloner : clone complet (le clone lié est réservé aux modèles), nœud, stockage et pool de destination.*

![Modifier les processeurs : sockets, cœurs, type de processeur et limites.](captures/vm-dialogue-processeurs.jpg)

*Modifier les processeurs : sockets, cœurs, type de processeur et limites.*

![Démarrage automatique : démarrer avec le nœud, ordre et délais.](captures/vm-dialogue-demarrage.jpg)

*Démarrage automatique : démarrer avec le nœud, ordre et délais.*

![Agrandir un disque : la taille ne peut qu'augmenter (irréversible).](captures/vm-dialogue-agrandir.jpg)

*Agrandir un disque : la taille ne peut qu'augmenter (irréversible).*

![Déplacer un disque vers un autre stockage.](captures/vm-dialogue-deplacer.jpg)

*Déplacer un disque vers un autre stockage.*

![Détacher un disque : il reste en « non utilisé » et n'est pas détruit.](captures/vm-dialogue-detacher.jpg)

*Détacher un disque : il reste en « non utilisé » et n'est pas détruit.*

![Éditeur de notes d'une machine.](captures/vm-notes-editeur.jpg)

*Éditeur de notes d'une machine.*

![Liste des snapshots d'une machine.](captures/vm-snapshots-liste.jpg)

*Liste des snapshots d'une machine.*

![Restaurer un snapshot : confirmation avec le nom de la machine à retaper.](captures/vm-snapshot-restaurer.jpg)

*Restaurer un snapshot : confirmation avec le nom de la machine à retaper.*

![Supprimer un snapshot : confirmation explicite.](captures/vm-snapshot-supprimer.jpg)

*Supprimer un snapshot : confirmation explicite.*

![Cloud-init : ajouter le lecteur de configuration.](captures/vm-cloud-init-lecteur-1.jpg)

*Cloud-init : ajouter le lecteur de configuration.*

![Cloud-init : réglages et retrait du lecteur](captures/vm-cloud-init-retrait.jpg)

*Cloud-init : réglages (utilisateur, clés SSH, réseau, DNS) ; retirer le lecteur demande une confirmation.*

![Cloud-init : snippets personnalisés (cicustom)](captures/vm-cloud-init-snippets.jpg)

*Cloud-init : section « Snippets personnalisés (avancé) » : pour chaque partie (user-data, network-config, meta-data, vendor-data), on choisit un snippet déjà présent dans un stockage « Snippets » du nœud, ou « Aucun » pour laisser Proxmox générer le fichier. Les snippets se déposent à la main : l'API Proxmox ne permet pas de les téléverser.*

![Cloud-init : un snippet choisi pour user-data](captures/vm-cloud-init-snippet-choisi.jpg)

*Cloud-init : un snippet existant (ici un fichier d'essai de 37 octets dans un stockage « Snippets ») choisi pour la partie user-data, relu depuis Proxmox après enregistrement ; « Aucun » le retire.*

![Une machine suspendue s'affiche « En pause » avec les boutons Reprendre et Forcer.](captures/vm-en-pause.jpg)

*Une machine suspendue s'affiche « En pause » avec les boutons Reprendre et Forcer.*

![Page d'un modèle : cloner, et « Supprimer le modèle » (nom à retaper).](captures/modele-page.jpg)

*Page d'un modèle : cloner, et « Supprimer le modèle » (nom à retaper).*

### Stockage

Les stockages du cluster, leur contenu, les ISO et les modèles.

![Page **Stockage** ](captures/stockage.jpg)

*Page **Stockage** : un stockage par carte (type, espace utilisé, contenu autorisé).*

![Un clic ouvre le tiroir du stockage ](captures/stockage-tiroir.jpg)

*Un clic ouvre le tiroir du stockage : fichiers (ISO, modèles), téléversement, téléchargement depuis une URL, catalogue de modèles, élagage des sauvegardes.*

![Catalogue officiel des modèles de conteneur de Proxmox (par défaut, seulement l'architectu](captures/stockage-catalogue-modeles.jpg)

*Catalogue officiel des modèles de conteneur de Proxmox (par défaut, seulement l'architecture du nœud), avec recherche et filtre par section.*

![Ajouter un stockage ](captures/stockage-ajouter.jpg)

*Ajouter un stockage : type, identifiant, chemin, contenu autorisé et nœuds concernés. Rien n'est écrit sans validation.*

![Téléverser une ISO ou un modèle, avec somme de contrôle facultative](captures/stockage-televerser.jpg)

*Téléverser une ISO ou un modèle, avec somme de contrôle facultative.*

![Télécharger un fichier depuis une adresse http(s) par le nœud lui-même (les adresses local](captures/stockage-url.jpg)

*Télécharger un fichier depuis une adresse http(s) par le nœud lui-même (les adresses locales sont refusées).*

![Modifier un stockage : contenus autorisés, nœuds, activation.](captures/stockage-modifier.jpg)

*Modifier un stockage : contenus autorisés, nœuds, activation.*

![Retirer un stockage : Kaji ne supprime jamais les fichiers, seulement la déclaration.](captures/stockage-retirer.jpg)

*Retirer un stockage : Kaji ne supprime jamais les fichiers, seulement la déclaration.*

![Élaguer les sauvegardes : aperçu de ce qui serait supprimé avant toute écriture.](captures/stockage-elaguer.jpg)

*Élaguer les sauvegardes : aperçu de ce qui serait supprimé avant toute écriture.*

![Supprimer un fichier d'un stockage (ISO, modèle)](captures/stockage-fichier-supprimer.jpg)

*Supprimer un fichier d'un stockage (ISO, modèle) : suppression définitive, le nom du fichier est à retaper. Kaji ne vérifie pas si une machine l'utilise.*

### Sauvegardes

Lire, lancer et planifier les sauvegardes.

![Page **Sauvegardes** ](captures/sauvegardes.jpg)

*Page **Sauvegardes** : toutes les sauvegardes du cluster, avec recherche et filtres. Ici, aucune sauvegarde n'existe encore.*

![Lancer une sauvegarde ](captures/sauvegardes-lancer.jpg)

*Lancer une sauvegarde : machine, stockage, mode (instantané, suspension, arrêt), compression et notes.*

![Onglet **Planifiées** ](captures/sauvegardes-planifiees.jpg)

*Onglet **Planifiées** : les jobs de sauvegarde automatiques.*

![Nouveau job planifié ](captures/sauvegardes-nouveau-job.jpg)

*Nouveau job planifié : jours, heure, stockage, machines (précises, un pool ou toutes) et mode.*

### Tâches

Le journal des tâches Proxmox, avec le compte qui les a lancées (« Kaji » signale celles qui viennent de l'interface).

![Liste des 100 dernières tâches, avec filtres (recherche, état, nœud)](captures/taches-1.jpg)

*Liste des 100 dernières tâches, avec filtres (recherche, état, nœud).*

![Suite de la liste](captures/taches-2.jpg)

*Suite de la liste. Cliquer sur une tâche ouvre son journal.*

![Suite de la liste ](captures/taches-3.jpg)

*Suite de la liste : créations, clonages, conversions, suppressions…*

![Journal d'une tâche : sortie complète de Proxmox, sans secret.](captures/taches-journal.jpg)

*Journal d'une tâche : sortie complète de Proxmox, sans secret.*

![Barre de tâches permanente en bas de la page d'une machine](captures/barre-de-taches.jpg)

*Barre de tâches permanente, en bas de chaque page (ici, une machine) : tâches en cours et dernières tâches avec leur état, leur machine, leur nœud et leur durée. Repliable, elle défile au lieu de masquer la page.*

![Journal d'une tâche ouvert depuis la barre](captures/barre-de-taches-journal.jpg)

*Un clic sur une tâche de la barre ouvre son journal en plein écran, comme dans la page « Tâches » (ici, la suppression d'un snapshot d'essai).*

![Arrêter une tâche en cours](captures/tache-arreter.jpg)

*Une tâche **en cours** (ici un téléchargement d'ISO) a un bouton **« Arrêter la tâche »** dans son journal, avec une confirmation en ligne. Seuls certains types de tâches sont arrêtables (téléchargement, sauvegarde, migration, clonage…), jamais une console ni une machine protégée.*

### Ceph

![Page **Ceph** ](captures/ceph.jpg)

*Page **Ceph** : sur un cluster sans Ceph, la page explique comment l'installer et l'initialiser. Ce cluster n'a pas de Ceph : les fonctions d'écriture de Ceph n'ont donc été testées qu'avec un faux Proxmox.*

![Fenêtre d'installation de Ceph (non validée en réel : pas de Ceph sur ce cluster).](captures/ceph-installer.jpg)

*Fenêtre d'installation de Ceph (non validée en réel : pas de Ceph sur ce cluster).*

![Création d'un moniteur Ceph (non validée en réel).](captures/ceph-moniteur.jpg)

*Création d'un moniteur Ceph (non validée en réel).*

### Réseau et pare-feu

Interfaces des nœuds, pare-feu (datacenter, nœud, machine) et SDN. Tout changement est préparé « en attente » puis appliqué avec un verrou explicite.

![Interfaces du nœud (bridges, bonds, VLAN, cartes) et pare-feu du datacenter](captures/reseau-1.jpg)

*Interfaces du nœud (bridges, bonds, VLAN, cartes) et pare-feu du datacenter. L'interface d'administration est marquée : la modifier est verrouillée.*

![Alias, IPSets, groupes de sécurité, zones SDN et pare-feu du nœud](captures/reseau-2.jpg)

*Alias, IPSets, groupes de sécurité, zones SDN et pare-feu du nœud.*

![Ajouter une interface ](captures/reseau-interface.jpg)

*Ajouter une interface : la modification est préparée, mais n'est appliquée qu'après un second geste.*

![Alias, IPSets et groupes de sécurité du pare-feu](captures/reseau-alias-ipsets.jpg)

*Alias, IPSets et groupes de sécurité du pare-feu.*

![Options du pare-feu ](captures/reseau-options-pare-feu.jpg)

*Options du pare-feu : les modifications dangereuses sont verrouillées, et l'aperçu dit pourquoi.*

![Onglet Pare-feu d'une machine](captures/pare-feu-machine-onglet.jpg)

*Onglet Pare-feu d'une machine (VM et LXC) : options, règles, alias et IPSets de la machine, avec un rappel que le pare-feu ne filtre rien tant que celui du datacenter est désactivé.*

![Options du pare-feu d'une machine](captures/pare-feu-machine-options.jpg)

*Options du pare-feu d'une machine (DHCP, filtres IP et MAC, NDP, annonces de routeur, politiques) : l'aperçu des verrous annonce qu'aucun n'est levé tant que le niveau est désactivé.*

![Règles du pare-feu d'une machine](captures/pare-feu-machine-regle.jpg)

*Règles du pare-feu d'une machine : la machine est préremplie, la règle créée (désactivée par défaut) est relue chez Proxmox.*

![Suppression d'un alias du pare-feu d'une machine](captures/pare-feu-machine-suppression.jpg)

*Supprimer un alias de la machine : le nom est à retaper pour confirmer, « Appliquer » reste grisé tant que ce n'est pas fait.*

![Règles du pare-feu (datacenter, nœud, machine, groupe) ](captures/reseau-regles.jpg)

*Règles du pare-feu (datacenter, nœud, machine, groupe) : chaque action montre d'abord ses verrous.*

![Ajouter une zone SDN (les VNets, sous-réseaux, contrôleurs et IPAM ont leurs propres fenêt](captures/reseau-sdn-zone.jpg)

*Ajouter une zone SDN (les VNets, sous-réseaux, contrôleurs et IPAM ont leurs propres fenêtres).*

![SDN : créer un VNet, en attente tant qu'il n'est pas appliqué.](captures/reseau-sdn-vnet.jpg)

*SDN : créer un VNet, en attente tant qu'il n'est pas appliqué.*

![SDN : appliquer ou annuler les changements en attente (verrou explicite).](captures/reseau-sdn-appliquer.jpg)

*SDN : appliquer ou annuler les changements en attente (verrou explicite).*

![SDN validé en réel : zone, VNet et sous-réseau en attente](captures/reseau-sdn-en-attente.jpg)

*SDN créé **par l'interface** sur le vrai cluster (validé le 2026-11-13) : une zone, un VNet et un sous-réseau `10.99.0.0/24 via 10.99.0.1`, tous en attente (état `new`, rien appliqué), puis « Annuler les modifications… » qui remet tout à zéro.*

![Supprimer une interface réseau](captures/reseau-interface-supprimer.jpg)

*Supprimer une interface réseau : préparer ne change rien, appliquer recharge le réseau. Pour l'interface d'administration, le verrou « coupure d'accès possible » exige une case et la phrase `COUPURE POSSIBLE`.*

### HA et réplication

Haute disponibilité (ressources, règles) et réplication de stockage. Toute écriture est d'abord prévisualisée et exige la phrase `COUPURE POSSIBLE` quand elle présente un risque.

![État de la HA ](captures/ha-1.jpg)

*État de la HA : quorum, maître, watchdog, gestionnaires (LRM). Avec deux nœuds, la page prévient du risque.*

![Ressources HA, règles HA et jobs de réplication](captures/ha-2.jpg)

*Ressources HA, règles HA et jobs de réplication.*

![Ajouter une machine à la HA ](captures/ha-ressource.jpg)

*Ajouter une machine à la HA : état demandé, redémarrages et déplacements maximum, retour sur le nœud préféré.*

![Nouvelle règle HA ](captures/ha-regle.jpg)

*Nouvelle règle HA : affinité de nœuds (avec priorités) ou affinité de ressources.*

![Migration ignorée par une règle stricte](captures/ha-regle-stricte.jpg)

*Migrer une machine de la HA : si une règle de nœud stricte n'autorise pas le nœud demandé, la fenêtre prévient que la HA va ignorer la demande (rien ne bougera tant que la règle existe) ; le verrou « coupure possible » reste affiché.*

![Nouveau job de réplication ](captures/ha-replication.jpg)

*Nouveau job de réplication : machine, nœud cible, planification, débit maximal (exige du stockage ZFS).*

### Cluster

Informations de corosync, et création, jonction et retrait d'un nœud avec verrous.

![Informations du cluster ](captures/cluster-1.jpg)

*Informations du cluster : nom, quorum, nombre de nœuds, version de configuration, liens.*

![Nœuds (votes, adresses, liens), QDevice et commandes `pvecm` à copier pour créer, joindre ](captures/cluster-2.jpg)

*Nœuds (votes, adresses, liens) et QDevice ; les commandes `pvecm` à copier restent disponibles.*

![Boutons Créer un cluster et Joindre un cluster au-dessus des commandes à copier](captures/cluster-ecriture-1.jpg)

*Créer ou joindre un cluster depuis Kaji (opérations rares et risquées) ; « Retirer… » apparaît sur un nœud hors ligne.*

![Fenêtre Créer un cluster : l'aperçu des verrous refuse, ce nœud est déjà dans un cluster](captures/cluster-ecriture-2.jpg)

*Fenêtre « Créer un cluster » : le serveur relit l'état chez Proxmox et refuse sur un nœud déjà en cluster (aperçu seulement, rien n'est écrit ; « Créer » reste grisé).*

### Connexions : épingler le certificat de Proxmox

![Fenêtre « Certificat » d'une connexion : empreinte SHA-256 présentée par le nœud, sujet, émetteur, validité, commande de comparaison, case de confirmation](captures/connexion-epinglage-1.jpg)

*Fenêtre « Épingler le certificat… » d'une connexion (noms et empreinte masqués) : Kaji montre le certificat que Proxmox présente, tu compares son empreinte à celle de ton nœud, tu coches et tu confirmes. Ensuite seul ce certificat est accepté (`docs/api/connexions-tls.md`).*

### Datacenter

![Options du datacenter ](captures/datacenter-1.jpg)

*Options du datacenter : clavier, langue, visionneuse de console, e-mail d'expédition, préfixe MAC, tâches parallèles, proxy, migration.*

![Haute disponibilité, ordonnancement et débits](captures/datacenter-ha-debits.jpg)

*Section « Haute disponibilité, ordonnancement et débits » : politique d'arrêt des nœuds, mode de fencing, ordonnancement des ressources (CRS), cinq limites de débit en Kio/s et réseau de réplication. Rien n'est envoyé sans passer par un aperçu.*

![Confirmation d'un réglage de la haute disponibilité](captures/datacenter-ha-confirmation.jpg)

*Un réglage de la HA (ici le CRS en mode `static`) lève un verrou décidé par le serveur : l'écran montre le risque et le paramètre exact, et n'écrit qu'après la case de confirmation. Le fencing matériel exige en plus la phrase `COUPURE POSSIBLE`.*

![Section WebAuthn des options du datacenter](captures/datacenter-webauthn.jpg)

*Section **WebAuthn** : identifiant de la partie de confiance (`id`), origine du site, nom affiché et sous-domaines. Aucune valeur n'est réglée sur ce cluster. Toute écriture demande une confirmation ; changer ou retirer une valeur déjà définie exige en plus la phrase `COUPURE POSSIBLE` (cela casse les credentials existants).*

![Notes du datacenter et début des notifications](captures/datacenter-2.jpg)

*Notes du datacenter, puis la section **Notifications** qui commence.*

![Notifications : cibles et règles, avec les boutons d'écriture](captures/datacenter-3.jpg)

*Section **Notifications** : les cibles (ici `mail-to-root`, la cible intégrée de Proxmox, qui écrit à `root@pam`) avec la règle qui les utilise, et les règles (`default-matcher`). Les éléments intégrés ne se suppriment pas. Boutons : ajouter, modifier, tester. Aucun mot de passe ni jeton n'est affiché. Dessous, les serveurs de métriques.*

![Ajouter une cible de notification](captures/notif-cible-creer-1.jpg)

*Ajouter une cible de notification : type (sendmail, SMTP, Gotify ou webhook), destinataires, serveur, port, chiffrement. Le mot de passe est en écriture seule et les adresses locales sont refusées.*

![Bas de la même fenêtre](captures/notif-cible-creer-2.jpg)

*Bas de la même fenêtre : case « Désactivée », **Aperçu** (ce qui serait envoyé à Proxmox, sans secret) puis **Appliquer**.*

![Modifier la cible intégrée `mail-to-root`](captures/notif-cible-modifier.jpg)

*Modifier la cible intégrée `mail-to-root` : commentaire en ASCII seulement (Proxmox altère les accents).*

![Tester une cible](captures/notif-cible-tester.jpg)

*Tester une cible : envoie un VRAI message, une fois par minute au plus, et il faut retaper le nom de la cible. Le bouton reste grisé tant que le nom n'est pas exact.*

![Ajouter une règle](captures/notif-regle-creer.jpg)

*Ajouter une règle : cibles, gravités, champs, calendrier, mode et inversion.*

![Ajouter un serveur de métriques (InfluxDB, Graphite…) ](captures/datacenter-metriques.jpg)

*Ajouter un serveur de métriques (InfluxDB, Graphite…) : les secrets ne sont jamais affichés.*

![Correspondances de ressources du datacenter](captures/datacenter-correspondances.jpg)

*Correspondances de ressources (PCI, USB, répertoires) : une correspondance donne un nom logique à un périphérique ou à un répertoire sur chaque nœud ; la liste est vide tant qu'aucune n'est créée.*

![Ajouter une correspondance PCI](captures/datacenter-correspondances-ajout.jpg)

*Ajouter une correspondance PCI : l'entrée se remplit depuis le matériel détecté sur le nœud (chemin, identifiant, sous-système, groupe IOMMU) ; l'aperçu dit ce qui sera envoyé avant toute écriture.*

![Une correspondance PCI créée](captures/datacenter-correspondances-liste.jpg)

*Une correspondance PCI créée : nom, description et entrée (nœud, chemin, identifiant) ; Modifier et Supprimer à droite.*

![Supprimer une correspondance](captures/datacenter-correspondances-suppression.jpg)

*Supprimer une correspondance : refusé tant qu'une VM la cite, aperçu puis identifiant à retaper.*

![Options du datacenter](captures/datacenter-identifiants-etiquettes.jpg)

*Options du datacenter, suite : **plage des identifiants libres** (début et fin, 100 à 999 999 999) et **style des étiquettes** (forme, ordre, casse, couleurs : une ligne par étiquette, « nom couleur [couleur du texte] »).*

![Après « Appliquer »](captures/datacenter-etiquettes-retirer.jpg)

*Après « Appliquer », la valeur est relue chez Proxmox. Les boutons « Retirer la plage d'identifiants » et « Retirer le style des étiquettes » remettent les valeurs par défaut.*

![Un début de plage supérieur à la fin est refusé par le serveur (« lower doit être inférieur à upper ») sans rien écrire.](captures/datacenter-plage-refusee.jpg)

*Un début de plage supérieur à la fin est refusé par le serveur (« lower doit être inférieur à upper ») sans rien écrire.*

![Options du datacenter](captures/datacenter-etiquettes-droits-consentement.jpg)

*Options du datacenter, fin : **étiquettes réservées** (une par ligne), **droits des utilisateurs sur les étiquettes** (none, list, existing, free ; avec `list`, la liste des étiquettes permises) et **texte de consentement** affiché à tous avant la connexion.*

![Le mode `list` sans aucune étiquette est refusé par le serveur (« exige au moins une étiquette ») sans rien écrire. Le texte de consentement n'est jamais copié dans le journal d'audit.](captures/datacenter-droits-refuses.jpg)

*Le mode `list` sans aucune étiquette est refusé par le serveur (« exige au moins une étiquette ») sans rien écrire. Le texte de consentement n'est jamais copié dans le journal d'audit.*

![Pools de ressources](captures/datacenter-pools.jpg)

*Section **Pools de ressources** de la page Datacenter : créer un pool, gérer ses membres, le supprimer (seulement s'il est vide).*

![Gérer un pool](captures/datacenter-pool-gerer.jpg)

*« Gérer » : commentaire du pool, membres actuels (cocher pour retirer), machines et stockages à ajouter. Fenêtre fermée sans valider.*

### Page d'un nœud

Tout ce qui concerne un serveur Proxmox : supervision, système, services, disques.

![En-tête du nœud (CPU, RAM, disque), notes du nœud et historique (heure, jour, semaine, moi](captures/noeud-1.jpg)

*En-tête du nœud (CPU, RAM, disque), notes du nœud et historique (heure, jour, semaine, mois, année).*

![Graphiques réseau et charge, console du nœud (verrouillée derrière une case à cocher) et b](captures/noeud-2.jpg)

*Graphiques réseau et charge, console du nœud (verrouillée derrière une case à cocher) et boutons redémarrer / éteindre le nœud.*

![Version de Proxmox et du noyau, heure et DNS, configuration (DNS, fuseau horaire, fichier ](captures/noeud-3.jpg)

*Version de Proxmox et du noyau, heure et DNS, configuration (DNS, fuseau horaire, fichier hosts) et mises à jour disponibles.*

![Dépôts de paquets (activer, désactiver, ajouter un dépôt standard) et certificats](captures/noeud-4.jpg)

*Dépôts de paquets (activer, désactiver, ajouter un dépôt standard) et certificats.*

![Installer un certificat, certificats automatiques (ACME) et services du nœud (arrêter, red](captures/noeud-5.jpg)

*Installer un certificat, certificats automatiques (ACME) et services du nœud (arrêter, redémarrer, recharger).*

![Fin des services, journal système et disques (état SMART)](captures/noeud-6.jpg)

*Fin des services, journal système et disques (état SMART).*

![Groupes LVM, pools LVM-thin, répertoires, ZFS, et machines du nœud](captures/noeud-7.jpg)

*Groupes LVM, pools LVM-thin, répertoires, ZFS, et machines du nœud.*

![Stockages et réseau du nœud](captures/noeud-8.jpg)

*Stockages et réseau du nœud.*

![Section Pare-feu de la page d'un nœud](captures/pare-feu-noeud-section.jpg)

*Section « Pare-feu » de la page d'un nœud : options et règles de ce nœud (vides ici), avec les boutons « Options… » et « Règles… ». Un pare-feu non activé ne filtre rien, même avec des règles.*

![Options du pare-feu du nœud : verrou « coupure d'accès possible »](captures/pare-feu-noeud-verrou.jpg)

*« Options… » s'ouvre déjà au niveau du nœud. Demander l'activation du pare-feu du nœud affiche, avant toute écriture, le verrou « Coupure d'accès possible » (case à cocher, puis phrase à retaper) ; ici, aperçu seulement, rien n'est appliqué.*

![Section Réplication de la page d'un nœud](captures/replication-noeud-section.jpg)

*Section « Réplication » de la page d'un nœud : les jobs qui partent de ce nœud ou arrivent dessus (aucun ici : le cluster n'a pas de ZFS), avec « Nouveau job… ».*

![Nouveau job de réplication bloqué faute de ZFS](captures/replication-noeud-bloque.jpg)

*« Nouveau job… » : l'aperçu annonce ce qui bloque (aucun stockage ZFS, disque sur LVM-thin) et « Appliquer » reste grisé ; rien n'est écrit.*

![Éditeur des notes d'un nœud.](captures/noeud-notes-editeur.jpg)

*Éditeur des notes d'un nœud.*

![Redémarrer un nœud : machines arrêtées, perte de quorum, machines protégées et nom à retaper.](captures/noeud-redemarrer.jpg)

*Redémarrer un nœud : machines arrêtées, perte de quorum, machines protégées et nom à retaper.*

![Éteindre un nœud](captures/noeud-eteindre.jpg)

*Éteindre un nœud : machines arrêtées, perte de quorum, nom du nœud à retaper. Un nœud éteint ne se rallume pas depuis Kaji.*

![Page d'un nœud](captures/noeud-groupees-boutons.jpg)

*Page d'un nœud, section Système : à côté de Redémarrer / Éteindre, **Actions groupées…** (démarrer, arrêter ou migrer plusieurs machines) et **Réveiller le nœud…** (Wake-on-LAN, grisé tant que le nœud est en ligne). Le message vert confirme l'action demandée à Proxmox.*

![Actions groupées](captures/noeud-groupees-protegee.jpg)

*Actions groupées, **Arrêter** : une machine protégée est refusée par le serveur (« jamais en groupe ») et le bouton reste grisé, même confirmé.*

![Actions groupées](captures/noeud-groupees-demarrer.jpg)

*Actions groupées, **Démarrer** : on coche les machines (jamais « toutes »), l'**Aperçu** liste ce qui sera envoyé à Proxmox.*

![Actions groupées](captures/noeud-groupees-arreter.jpg)

*Actions groupées, **Arrêter** : arrêt forcé après un délai (en secondes) et nom du nœud à retaper avant de valider.*

![Actions groupées](captures/noeud-groupees-migrer.jpg)

*Actions groupées, **Migrer** : nœud cible, migrations en parallèle, copie des disques locaux, puis nom du nœud à retaper.*

![Activer un dépôt apt](captures/noeud-depot-activer.jpg)

*Activer ou désactiver un dépôt de paquets demande une **confirmation** : Kaji relit les dépôts avant d'écrire et refuse si la configuration a bougé. Pour un dépôt « enterprise » sans abonnement, une case supplémentaire (« apt répondra 401 ») doit être cochée.*

![Dépôts de paquets d'un nœud](captures/noeud-depots-liste.jpg)

*Section **Dépôts de paquets** : activer ou désactiver un dépôt existant, ajouter un dépôt standard de Proxmox, ou préparer un **dépôt personnalisé**.*

![Dépôt apt personnalisé](captures/noeud-depot-perso.jpg)

*« Dépôt personnalisé… » : Proxmox ne sait pas écrire un dépôt libre, Kaji valide les champs et fabrique le fichier `.sources` et les commandes à **copier** dans la console du nœud (rien n'est envoyé à Proxmox). Les avertissements disent ce qui manque (ici : la clé de signature doit déjà exister sur le nœud).*

![Serveurs NTP d'un nœud](captures/noeud-ntp-commandes.jpg)

*« Serveurs NTP… » (bloc **Configuration du nœud**) : Proxmox n'a pas d'API NTP, Kaji valide les champs et fabrique le fichier de sources `chrony` et les commandes à **copier** dans la console du nœud (contrôle de la directive, écriture, rechargement, vérification). Rien n'est envoyé à Proxmox.*

### Accès

Ce que le token de Kaji peut faire, et les droits Proxmox (lecture seule). Les pages « Connexions » et « Compte », qui touchent aux tokens et aux mots de passe, ne sont pas montrées.

![Mode administrateur (session temporaire) et liste des 28 droits dont Kaji a besoin](captures/acces-1.jpg)

*Mode administrateur (session temporaire) et liste des 28 droits dont Kaji a besoin : 27 sont accordés, 1 manque.*

![Suite des droits, avec le droit de notification manquant](captures/acces-2.jpg)

*Suite des droits : snapshots, clonage, migration, sauvegardes, console, HA, réplication, **notifications (lecture et écriture)**, datacenter… Ici, le droit `Mapping.Modify` sur `/mapping/notifications` n'est pas accordé : l'écriture des notifications reste donc refusée tant qu'il manque, et la page affiche la commande pour le donner.*

![Fin des droits, puis utilisateurs et groupes](captures/acces-3.jpg)

*Fin des droits, puis utilisateurs et groupes.*

![Droits attribués (ACL) du token de Kaji, par chemin](captures/acces-4.jpg)

*Droits attribués (ACL) du token de Kaji, par chemin.*

![Rôles Proxmox et leurs privilèges](captures/acces-5.jpg)

*Rôles Proxmox et leurs privilèges.*

![Fin des rôles et realms d'authentification](captures/acces-6.jpg)

*Fin des rôles et realms d'authentification.*

![Ouvrir une session administrateur](captures/acces-session-admin.jpg)

*Ouvrir une session administrateur : un token créé pour l'occasion, valable 30 minutes, gardé en mémoire du serveur seulement. Les champs sont vides ici.*

![Tableau des utilisateurs avec le bouton Supprimer](captures/acces-utilisateurs-supprimer.jpg)

*Avec une session administrateur ouverte, chaque utilisateur du realm `pve` a un bouton **Supprimer…** ; Kaji et `root@pam` n'en ont pas (« – »), ils sont protégés.*

![Fenêtre de suppression d'un utilisateur](captures/acces-utilisateur-suppression.jpg)

*Le bouton ouvre la suppression déjà réglée : l'utilisateur se choisit dans une liste (plus de saisie à la main, de même pour la double authentification, les ACL et les groupes), l'impact s'affiche tout de suite (groupes, entrées d'ACL, jetons supprimés avec lui) et « Appliquer » reste grisé tant que le nom n'est pas retapé. Fenêtre ouverte puis fermée sans valider.*

![Les rôles Proxmox se déplient pour montrer leurs privilèges (ici `PVEAuditor`, lecture seule).](captures/acces-role-deplie.jpg)

*Les rôles Proxmox se déplient pour montrer leurs privilèges (ici `PVEAuditor`, lecture seule).*
