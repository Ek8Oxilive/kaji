# Statut des fonctions de Kaji (pour la V1)

*Revu le 2026-11-13 (lots de la journée compris : rôles, session par mot de passe, journal du cluster, options du nœud, images OCI, planificateur, alertes).*

Trois niveaux, sans ambiguïté. **« Validé en réel »** = essayé sur le vrai cluster (2 nœuds, Proxmox 9.1.9) par l'interface de Kaji déployée, dans le bac à sable, tout remis à l'identique. **« Expérimental »** = codé et testé sur un faux Proxmox strict (avec mutations), **jamais exécuté sur un vrai Proxmox**, souvent parce que le cluster n'a pas le matériel (ZFS, Ceph, PBS) ou qu'on ne risque pas la configuration réelle. Le détail ligne par ligne est dans `docs/parite-proxmox.md` ; l'historique des essais dans `docs/REPRISE.md`.

## 1. Validé en réel (utilisable)
- **Machines (VM et conteneurs)** : démarrer, arrêter, redémarrer, arrêt forcé, suspendre, reprendre, hiberner, réinitialiser ; créer (assistant complet, depuis une ISO ou un modèle) ; supprimer (nom retapé) ; CPU, RAM, disques (ajouter, détacher, déplacer, agrandir) ; carte réseau ; options ; cloud-init ; snapshots ; clone (complet et lié) ; convertir en modèle ; **migration hors ligne et à chaud** ; notes et étiquettes ; consoles noVNC et xterm.js ; terminal série.
- **Matériel avancé** (VM arrêtée) : carte d'affichage, ports série, audio, RNG, watchdog, BIOS, disque EFI, TPM ; passthrough PCI / USB / répertoire par correspondance.
- **Stockage** : liste, contenu, ajouter / modifier / retirer un stockage `dir`, téléverser et télécharger des ISO, modèles LXC, supprimer un volume.
- **Cluster et datacenter** : tableau de bord temps réel, tâches (liste, journal, arrêter), pools de ressources, **HA** (ressources, règles, migrer, relocaliser), options du datacenter (clavier, notes, plage d'identifiants, style des étiquettes, étiquettes réservées, texte de consentement), correspondances de ressources, serveurs de métriques InfluxDB et Graphite (désactivés), notifications (cibles sendmail et gotify désactivées, règles).
- **Nœud** : résumé et graphiques, notes, journal système, disques (liste, SMART), **DNS, hosts, fuseau horaire, redémarrage d'un service normal (`chrony`), dépôts apt (désactiver / activer)**, actions groupées (démarrer, arrêter, migrer une sélection).
- **Réglages du datacenter** (HA, fencing, CRS, débits, réplication, étiquettes, plage d'identifiants) : écrits par l'interface, relus, état d'origine rétabli.
- **Options fines du matériel** d'une VM : disque (cache, discard, iothread, limites de débit…), carte réseau (débit, MTU, trunks, câble débranché), CPU (`cpuunits`, `cpulimit`). `affinity` et `hugepages` sont refusés par Proxmox au jeton (voir limites).
- **Utilisateurs Proxmox** : suppression d'un utilisateur du realm `pve` (impact affiché, nom retapé) ; **session administrateur** ouverte avec le jeton de Kaji (option `KAJI_ADMIN_USE_KAJI_TOKEN`, droits donnés par le propriétaire) ; listes déroulantes d'utilisateurs et de groupes.
- **SDN** : zone, VNet, sous-réseau et fabrics créés EN ATTENTE puis annulés (jamais appliqués) ; **certificat de Proxmox épinglé** (empreinte vérifiée identique à celle du cluster).
- **Journal du cluster** (lecture, 100 entrées lues avec le format attendu) ; **alertes** : règle CPU créée, nœuds passés « en alerte » puis « résolue » d'eux-mêmes après relèvement du seuil, règle supprimée (sans webhook : un webhook n'a pas été essayé) ; **actions planifiées** : une planification de démarrage s'exécute à l'heure, est auditée et se supprime (la tâche Proxmox a échoué ce jour-là à cause de la configuration de la VM d'essai, pas du planificateur).
- **Pare-feu et réseau, en lecture** et objets pare-feu inertes (alias, IPSets, groupes, règles et options sur la VM de test) ; réseau d'un nœud : lecture et mise en attente puis annulation.
- **Interface** : recherche globale, thèmes (Sombre, Glass, Clair, Auto), français / anglais, petits écrans (vu à ~390 px), journal d'audit de Kaji.
- **Console SPICE** : le fichier `.vv`, le tunnel du proxy, le TLS et l'authentification sont validés avec un client minimal ; **l'affichage dans un vrai virt-viewer n'a pas été vu**.

## 2. Expérimental (codé, jamais exécuté en réel : à utiliser avec prudence)
Le serveur le dit déjà dans l'interface (« non validé en réel ») et verrouille ce qui peut couper l'accès.
- **Ceph** : tout (installation guidée, moniteurs, gestionnaires, MDS, OSD, pools, **destruction**) : le cluster n'a pas Ceph.
- **Réplication ZFS** (jobs) et stockages autres que `dir` (LVM, LVM-thin, ZFS, NFS, CIFS…) : écriture non essayée, pas de ZFS.
- **Proxmox Backup Server**, protection et élagage des sauvegardes : aucun PBS, aucune sauvegarde sur le cluster.
- **SDN, la suite** : **appliquer** la configuration (interdit sur le cluster réel), IPAM et DNS (écriture immédiate, secrets), nœuds de fabric, contrôleurs `bgp` / `isis`.
- **Droits Proxmox** : ACL, groupes, appartenances, jetons API, **realms LDAP / AD / OpenID**, **double authentification** (ajout, activation, suppression, déblocage), **WebAuthn** du datacenter : écriture jamais essayée en réel (risque de verrouiller des comptes ; pas d'annuaire sur le cluster). **L'écriture de la TFA exige une session ouverte par mot de passe** (Proxmox l'interdit aux jetons), jamais essayée.
- **Réseau** : appliquer une configuration réseau ; **pare-feu activé** (datacenter, nœud) et ses verrous actifs.
- **Cluster : créer, joindre, retirer un nœud** (verrous et aperçu essayés en réel, aucune écriture) ; **migration vers un autre cluster** (un seul cluster pour essayer) ; redémarrer / éteindre un nœud ; Wake-on-LAN.
- **Options du nœud** en écriture (réveil à distance, délai de démarrage, ballooning) et **images OCI** (téléchargement depuis un registre) : codées et testées sur faux Proxmox, jamais essayées en réel.
- **Rôles de Kaji** (administrateur, opérateur, lecture seule) : politique testée avec de vrais comptes sur faux Proxmox, jamais essayée dans l'interface déployée ; **webhook des alertes** et **alertes de tâches en échec** ; actions planifiées autres que démarrer (éteindre, redémarrer, arrêt forcé, snapshot).
- **Certificats** (personnalisé, ACME), services sensibles, disques (GPT, effacer, LVM, répertoire), ajout d'un dépôt apt standard ou personnalisé.
- **Notifications** : SMTP avec identifiants, envoi de test réel (en attente d'un relais de messagerie) ; serveur de métriques actif ou OpenTelemetry. (Cibles SMTP et webhook **désactivées** : validées en réel.)
- **Jeton de première configuration** (`KAJI_SETUP_TOKEN`) et **HTTPS Caddy** : testés avec de vrais handshakes TLS / sur faux Proxmox, pas activés sur le déploiement ; voir `docs/securite.md` et `docs/v1-actions-enzo.md`.
- Options avancées de VM peu courantes (`vga: none`, `pcie`, `x-vga`, `mdev`, réplication de machine), VM en marche pour le passthrough, shell du nœud.

## 3. Limites connues (non couvert, ou refusé par Proxmox)
- **Moniteur QEMU** : Proxmox 9 le refuse au jeton de Kaji (réservé à `root@pam`) : fonction inutilisable en l'état.
- **LXC `keyctl`, `fuse`, `mount`** : réservés à `root@pam` chez Proxmox.
- **Détruire un CephFS** : pas d'API chez Proxmox (ligne de commande). **Appareils `devN` d'un conteneur LXC** : non faits (droit probablement réservé à `root@pam`, à sonder).
- **VM : `affinity` et `hugepages`** : réservés à `root@pam` chez Proxmox.
- **Écrire la double authentification** : impossible avec un jeton d'API (`allowtoken: 0` chez Proxmox) ; il faut ouvrir la session administrateur **par mot de passe**.
- **Rôles** : ils protègent l'accès à **Kaji** ; le jeton de Kaji reste le même pour tous auprès de Proxmox (un administrateur de Kaji agit avec ses droits). **Double authentification** pour se connecter à Kaji : non fournie. **HTTPS** : option fournie (`docker-compose.tls.yml`, Caddy) mais **non testée en réel** et pas activée sur le déploiement actuel. Voir `docs/securite.md`.
- Vu seulement sur Chrome / Brave : pas de Safari ni de vrai téléphone ; qualité de l'anglais relue par échantillon.
- Les messages du serveur construits avec des valeurs (certains refus) restent en français.
- **Alertes** : pas d'e-mail (Kaji n'a pas de SMTP : webhook seulement), pas d'acquittement, nœuds, stockages et tâches seulement (pas d'alerte par machine). **Planificateur** : un créneau manqué (Kaji arrêté) n'est jamais rattrapé ; snapshots sans suppression automatique ; **une seule instance de Kaji** doit tourner (sinon les actions et alertes seraient doublées).
