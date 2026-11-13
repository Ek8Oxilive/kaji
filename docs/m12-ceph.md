# M12 : cadrage de Ceph

**Statut (revu le 2026-11-13) : cadrage de départ ; M12 est codé** (lecture, écriture C2 / C3 / initialisation, destruction C4 : `docs/api/ceph.md`, `ceph-destruction.md`), **jamais validé en réel : le cluster n'a pas Ceph** (voir `docs/statut-fonctions.md`). Texte d'origine : But du projet : ne perdre aucune fonctionnalité de l'interface de Proxmox (`docs/parite-proxmox.md`),
Ceph compris. Ce document dit ce qu'il y a à couvrir, **ce que le cluster de test permet réellement**, comment avancer sans risque, et
les décisions à prendre.

## 1. Faits vérifiés sur le cluster réel (lecture seule, Proxmox 9.1.9)

| Constat | Valeur |
|---|---|
| Ceph installé | **Non** (`binary not installed: /usr/bin/ceph-mon` sur `/cluster/ceph/status`) |
| Nœuds | **2** (`enzo`, `enzo2`) |
| Disques de `enzo` | **un seul** : NVMe 512 Go (le disque système) |
| Disques de `enzo2` | **un seul** : 500 Go (le disque système) |
| Mémoire | `enzo` 15,5 Go (10,2 utilisés, environ 5 libres) ; `enzo2` 7,6 Go (5,2 utilisés, environ 2,4 libres) |

**Conséquences.**
1. **Ceph ne peut pas tourner sur ce cluster tel qu'il est** : pas de disque libre pour un OSD, et **deux nœuds seulement**. Ceph demande
   au minimum **trois moniteurs** pour garder le quorum quand un nœud tombe (avec deux, la perte d'un nœud bloque tout le stockage Ceph).
2. **Un banc d'essai imbriqué n'est pas réaliste ici** : trois Proxmox imbriqués avec leurs moniteurs et OSD demandent environ 4 à 6 Go
   chacun, soit 12 à 18 Go, pour 7,4 Go libres au total.
3. Pour **utiliser** Ceph (ton besoin), il faudra du matériel : un 3e nœud, ou au moins 3 nœuds avec **un disque dédié aux OSD** chacun.

## 2. Ce que couvre l'interface de Proxmox (à reproduire)

| Zone | Fonctions |
|---|---|
| **Installation** | assistant d'installation de Ceph sur un nœud (dépôt, paquets), initialisation (réseau public et réseau de cluster) |
| **État** | santé (`HEALTH_OK` / `WARN` / `ERR`) et ses messages, groupes de placement (PG), usage, débit, OSD actifs et dans le cluster |
| **Moniteurs et gestionnaires** | lister, créer, détruire |
| **OSD** | lister (état, usage, classe de disque), créer (disque, disque de journal DB/WAL, chiffrement), mettre dedans/dehors, démarrer, arrêter, redémarrer, **détruire**, scrub, rééquilibrer |
| **Pools** | lister, créer (`size`, `min_size`, règle CRUSH, autoscaler de PG, application), modifier, **détruire**, créer le stockage RBD associé |
| **CephFS** | créer, détruire, serveurs de métadonnées (MDS) |
| **Configuration** | `ceph.conf`, base de configuration, carte CRUSH, règles CRUSH (lecture) |
| **Journaux, performances** | journal Ceph, débit et latence |

## 3. Ce qui rend Ceph dangereux (et les règles qui en découlent)

Une erreur sur Ceph **détruit des données de toutes les machines** qui s'appuient sur un pool, pas d'une seule. Règles à figer, **chacune
avec un test qui échoue si on la retire** :

1. **Lecture seule d'abord.** Rien d'écrit tant que la lecture n'est pas validée en réel.
2. **Jamais de configuration brute.** Pas d'édition libre de `ceph.conf` ni de la base de configuration : champs en liste blanche.
3. **Garde-fous de redondance.** Refus de `size` inférieur à 2 et de `min_size` à 1 (avec `size` 2 ou plus, `min_size` à 1 laisse
   écrire sur une seule copie) ; valeurs par défaut `size 3`, `min_size 2`.
4. **Barrière de santé.** Toute opération risquée (arrêter, mettre dehors ou détruire un OSD, détruire un moniteur) est refusée si la santé
   n'est pas `HEALTH_OK`, ou si l'opération ferait perdre le quorum ou la redondance.
5. **Destruction : confirmation forte et dépendances.** Détruire un **pool** liste d'abord les stockages et disques de machines qui
   l'utilisent et refuse tant qu'il y en a ; détruire un **OSD** exige qu'il soit déjà dehors et arrêté, que ses données soient
   évacuées, et le **nom exact retapé** ; jamais en masse.
6. **Une seule opération destructive à la fois**, audit de chacune (succès, refus, erreur), sans secret.
7. **Validation en réel uniquement sur un environnement Ceph jetable** : jamais sur le Ceph de production du propriétaire.

## 4. Comment avancer sans environnement Ceph

On développe et on teste **avec le faux Proxmox** (comme pour M5), et on **ne déclare « validé en réel » que ce qui a tourné sur un vrai
Ceph**. Chaque lot a donc une liste « non validé en réel » explicite et la PR le dit.

| Lot | Contenu | Qui | Risque | Validation en réel |
|---|---|---|---|---|
| **C1 : lecture seule** | état et santé, moniteurs, gestionnaires, OSD, pools, CephFS, configuration, journal ; page « Ceph » | PC B (faux Proxmox) | Faible | Possible dès qu'un Ceph existe (même vide) |
| **C2 : pools** | créer, modifier (garde-fous du §3), stockage RBD | PC B puis PC A | Élevé | Ceph jetable |
| **C3 : moniteurs, gestionnaires, OSD, MDS** | créer, démarrer, arrêter, mettre dedans/dehors | PC B puis PC A | Élevé | Ceph jetable |
| **C4 : destruction** | détruire pool, OSD, moniteur, gestionnaire, MDS (barrières du §3) ; **CephFS : pas d'API chez Proxmox** | PC A | **Très élevé** | Ceph jetable (**codé le 2026-11-12, faux Proxmox seulement** : `docs/api/ceph-destruction.md`) |
| **C5 : initialisation** | initialisation (`pveceph init`) et assistant ; **l'installation des paquets n'a pas d'API chez Proxmox** (elle reste dans le shell du nœud) | PC B (décision du propriétaire) puis PC A | Élevé | Nœud jetable |

**C1 peut commencer tout de suite** : il est en lecture seule et se teste entièrement avec le faux Proxmox.

## 5. Les trois façons d'obtenir un Ceph jetable pour valider C2 à C5

| Option | Ce qu'il faut | Remarques |
|---|---|---|
| **A. Un 3e nœud réel** (et un disque dédié par nœud) | du matériel | **Nécessaire de toute façon pour utiliser Ceph en production** ; sert aussi de banc d'essai tant qu'il n'est pas en production |
| **B. Banc d'essai imbriqué sur une autre machine** | une machine avec **au moins 16 Go de RAM libres** et la virtualisation imbriquée | Trois Proxmox en VM avec chacun 2 disques virtuels supplémentaires |
| **C. Banc d'essai sur ce cluster** | libérer de la mémoire (arrêter des machines) | **Non recommandé** : 7,4 Go libres seulement, et risque pour les machines de production |

## 6. Décisions à prendre

1. **Lancer C1 (Ceph en lecture seule) tout de suite avec PC B ?** *(recommandé : oui)*
2. **Quelle option pour un Ceph jetable (A, B ou C) ?** Sans elle, C2 à C5 resteront « écrits mais non validés en réel ».
3. **Prévois-tu un 3e nœud pour utiliser Ceph ?** *(Avec deux nœuds, Ceph n'est pas recommandé : le stockage répliqué par ZFS et la
   réplication de Proxmox, déjà prévue en M8, conviennent mieux à 2 nœuds.)*
