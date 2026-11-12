# Statut des fonctions de Kaji (pour la V1)

Trois niveaux, sans ambiguïté. **« Validé en réel »** = essayé sur le vrai cluster (2 nœuds, Proxmox 9.1.9) par l'interface de Kaji déployée, dans le bac à sable, tout remis à l'identique. **« Expérimental »** = codé et testé sur un faux Proxmox strict (avec mutations), **jamais exécuté sur un vrai Proxmox**, souvent parce que le cluster n'a pas le matériel (ZFS, Ceph, PBS) ou qu'on ne risque pas la configuration réelle. Le détail ligne par ligne est dans `docs/parite-proxmox.md` ; l'historique des essais dans `docs/REPRISE.md`.

## 1. Validé en réel (utilisable)
- **Machines (VM et conteneurs)** : démarrer, arrêter, redémarrer, arrêt forcé, suspendre, reprendre, hiberner, réinitialiser ; créer (assistant complet, depuis une ISO ou un modèle) ; supprimer (nom retapé) ; CPU, RAM, disques (ajouter, détacher, déplacer, agrandir) ; carte réseau ; options ; cloud-init ; snapshots ; clone (complet et lié) ; convertir en modèle ; **migration hors ligne et à chaud** ; notes et étiquettes ; consoles noVNC et xterm.js ; terminal série.
- **Matériel avancé** (VM arrêtée) : carte d'affichage, ports série, audio, RNG, watchdog, BIOS, disque EFI, TPM ; passthrough PCI / USB / répertoire par correspondance.
- **Stockage** : liste, contenu, ajouter / modifier / retirer un stockage `dir`, téléverser et télécharger des ISO, modèles LXC, supprimer un volume.
- **Cluster et datacenter** : tableau de bord temps réel, tâches (liste, journal, arrêter), pools de ressources, **HA** (ressources, règles, migrer, relocaliser), options du datacenter (clavier, notes, plage d'identifiants, style des étiquettes, étiquettes réservées, texte de consentement), correspondances de ressources, serveurs de métriques InfluxDB et Graphite (désactivés), notifications (cibles sendmail et gotify désactivées, règles).
- **Nœud** : résumé et graphiques, notes, journal système, disques (liste, SMART), **DNS, hosts, fuseau horaire, redémarrage d'un service normal (`chrony`), dépôts apt (désactiver / activer)**, actions groupées (démarrer, arrêter, migrer une sélection).
- **Pare-feu et réseau, en lecture** et objets pare-feu inertes (alias, IPSets, groupes, règles et options sur la VM de test) ; réseau d'un nœud : lecture et mise en attente puis annulation.
- **Interface** : recherche globale, thèmes (Sombre, Glass, Clair, Auto), français / anglais, petits écrans (vu à ~390 px), journal d'audit de Kaji.
- **Console SPICE** : le fichier `.vv`, le tunnel du proxy, le TLS et l'authentification sont validés avec un client minimal ; **l'affichage dans un vrai virt-viewer n'a pas été vu**.

## 2. Expérimental (codé, jamais exécuté en réel : à utiliser avec prudence)
Le serveur le dit déjà dans l'interface (« non validé en réel ») et verrouille ce qui peut couper l'accès.
- **Ceph** : tout (installation guidée, moniteurs, gestionnaires, MDS, OSD, pools, **destruction**) : le cluster n'a pas Ceph.
- **Réplication ZFS** (jobs) et stockages autres que `dir` (LVM, LVM-thin, ZFS, NFS, CIFS…) : écriture non essayée, pas de ZFS.
- **Proxmox Backup Server**, protection et élagage des sauvegardes : aucun PBS, aucune sauvegarde sur le cluster.
- **SDN** (zones, VNets, contrôleurs, IPAM, DNS, fabrics) : le jeton de Kaji n'a pas le droit `SDN.Allocate`.
- **Droits Proxmox** (utilisateurs, groupes, ACL, jetons API) : écriture jamais essayée (il faut un jeton d'administration).
- **Réseau** : appliquer une configuration réseau ; **pare-feu activé** (datacenter, nœud) et ses verrous actifs.
- **Cluster : créer, joindre, retirer un nœud** (verrous et aperçu essayés en réel, aucune écriture) ; redémarrer / éteindre un nœud ; Wake-on-LAN.
- **Certificats** (personnalisé, ACME), services sensibles, disques (GPT, effacer, LVM, répertoire), ajout d'un dépôt apt standard ou personnalisé.
- **Notifications** : SMTP, webhook, envoi de test ; serveur de métriques actif ou OpenTelemetry.
- Options avancées de VM peu courantes (`vga: none`, `pcie`, `x-vga`, `mdev`, réplication de machine), VM en marche pour le passthrough, shell du nœud.

## 3. Limites connues (non couvert, ou refusé par Proxmox)
- **Moniteur QEMU** : Proxmox 9 le refuse au jeton de Kaji (réservé à `root@pam`) : fonction inutilisable en l'état.
- **LXC `keyctl`, `fuse`, `mount`** : réservés à `root@pam` chez Proxmox.
- **Détruire un CephFS** : pas d'API chez Proxmox (ligne de commande). Migration **vers un autre cluster** : non faite.
- **Double authentification** pour se connecter à Kaji : non fournie. **HTTPS** : non fourni (à mettre devant). Voir `docs/securite.md`.
- Vu seulement sur Chrome / Brave : pas de Safari ni de vrai téléphone ; qualité de l'anglais relue par échantillon.
- Les messages du serveur construits avec des valeurs (certains refus) restent en français.
