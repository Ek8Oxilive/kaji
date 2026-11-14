# Cadrage : de « lab » à « production en entreprise » (jalons J0 à J4)

**Objectif (demande d'Enzo, 2026-11-14)** : que Kaji puisse être déployé en production dans une entreprise pour gérer un cluster Proxmox VE. **Aujourd'hui (J0) il est « V1 candidate », prévu pour un lab interne non exposé** (`docs/statut-fonctions.md`, `docs/securite.md`). Ce document dit ce qui sépare les deux, dans quel ordre, avec des critères de sortie vérifiables (« go / no-go ») à chaque jalon.

**Principe** : on ne franchit un jalon que si **tous** ses critères sont remplis. Ce qui n'est pas vérifié en réel est écrit comme tel. Les estimations de taille sont relatives (S < M < L), pas des durées.

## Où l'on en est (J0, vérifié le 2026-11-13)
| Domaine | État |
|---|---|
| Déploiement | Docker (backend FastAPI, nginx, Caddy en option), HTTPS interne, jeton de première configuration, secret obligatoire |
| Accès à Kaji | un mot de passe par compte, 3 rôles (administrateur, opérateur, lecture seule), sessions, limiteur de connexions **en mémoire** |
| Accès à Proxmox | **un seul jeton partagé** par tous les utilisateurs de Kaji ; session administrateur ponctuelle (jeton ou mot de passe) pour les droits, utilisateurs, realms, double authentification |
| Traçabilité | audit propre à Kaji (sans secret) ; **côté Proxmox, toutes les actions apparaissent sous le même jeton** |
| Validation | un seul cluster (2 nœuds), sans ZFS, Ceph ni PBS ; fonctions classées « validé en réel / expérimental » |
| Tests | ~5 600 tests sur faux Proxmox strict, mutations ; CI à 3 contrôles |
| Revue | **aucune relecture ni test d'intrusion par un tiers** |
| Livraison | pas de versions étiquetées ni de journal des changements ; images de base désignées par étiquette |

## Décision d'identité côté Proxmox (**retenue par Enzo le 2026-11-14 : option A, avec garde-fous**)
C'est ce qui engage l'architecture et ce qu'une entreprise remarque d'abord : *qui a fait quoi ?*

| Option | Principe | Pour | Contre |
|---|---|---|---|
| **A. Un jeton Proxmox par utilisateur de Kaji** | Chaque personne crée un jeton dans Proxmox (droits propres) et l'associe à son compte Kaji ; Kaji le garde chiffré | Proxmox applique **ses** droits, journal Proxmox nominatif, on peut retirer un droit sans toucher à Kaji | Beaucoup de secrets à stocker (compromettre Kaji = compromettre tous les jetons) ; jetons à créer et renouveler ; certaines routes refusent les jetons (TFA, `allowtoken: 0`) |
| **B. Ticket par session (mot de passe)** | La personne se connecte à Kaji avec son compte Proxmox ; Kaji obtient un ticket Proxmox temporaire | **Aucun secret stocké**, identité réelle, double authentification gérée | Le ticket expire (~2 h), mot de passe à retaper, pas de tâche planifiée ni d'alerte sans personne connectée |
| **C. Statu quo (jeton partagé) + audit Kaji** | Un jeton limité, rôles de Kaji, journal de Kaji exporté | Simple, déjà fait | Les droits réels sont ceux du jeton, pas ceux de la personne ; journal Proxmox anonyme |

**Décision (Enzo, 2026-11-14)** : **option A** pour tout ce que la personne fait à la main, complétée par :
1. **Chaque jeton avec date d'expiration et séparation de privilèges** (le jeton n'a que les droits qu'on lui donne, pas ceux du compte).
2. **Un jeton de service limité** pour le planificateur et les alertes (personne n'est connecté) : jamais `Administrator`, uniquement les droits que ces fonctions exigent (`docs/api/acces.md`).
3. **La session par mot de passe** (ticket, mot de passe jamais gardé : `docs/api/admin-session.md`) seulement pour les rares opérations que Proxmox interdit aux jetons (`allowtoken: 0` : écriture de la double authentification).
4. **Chiffrement renforcé des jetons** : clé **séparée** des données, rotation documentée, et **test explicite que la base seule ne suffit pas à les lire**.

**Risque accepté et à surveiller** : Kaji garde alors **tous** les jetons des utilisateurs (chiffrés) : qui obtient la base ET la clé les obtient tous. D'où les points 1 et 4, et le fait que les jetons soient à privilèges séparés et expirables. Kaji pourra aider l'administrateur à créer ces jetons (session administrateur, secret affiché une seule fois, comme l'écran des jetons de la page « Accès »).

## Jalons

### J1. Lab partageable (une autre personne peut l'installer et l'essayer) : taille S à M
Public : un collègue, un lab d'entreprise.
- **Guide « Installer Kaji en lab »** : prérequis, jeton Proxmox au moindre privilège (liste des droits par fonction : `docs/api/acces.md`), variables à régler, `KAJI_ADMIN_USE_KAJI_TOKEN=false`, HTTPS, sauvegarde de la base ET de la clé.
- **`SECURITY.md`** (signalement de vulnérabilité, versions suivies) et **`CHANGELOG.md`**.
- **Versions étiquetées** (`v1.0.0-rc1`…), images de base **épinglées par empreinte**.
- **Installation propre testée par quelqu'un d'autre** que l'auteur, sur une machine neuve ; chaque accroc devient un ticket.
- **Sauvegarde et restauration de Kaji** testées de bout en bout (base + clé, jetons et webhooks relus après restauration).
- **Critères de sortie** : installation réussie par un tiers en suivant le guide seul ; restauration validée ; aucun secret dans les journaux (test existant) ; CI verte.

### J2. Pilote en entreprise (équipe réduite, réseau interne) : taille L
- **Identité par utilisateur (option A retenue ; jeton par utilisateur codé le 2026-11-14, #440, essai réel à faire)** : jeton Proxmox par utilisateur de Kaji (chiffré, clé séparée, expiration, privilèges séparés), **jeton de service limité** pour le planificateur et les alertes, **session par mot de passe** pour les opérations interdites aux jetons ; création assistée des jetons par l'administrateur.
- **Connexion à Kaji d'entreprise** : OIDC (SSO) et/ou LDAP / AD ; **double authentification (TOTP) pour se connecter à Kaji** (aujourd'hui seulement pour les comptes Proxmox).
- **Audit exportable** : syslog / fichier JSON horodaté, conservation configurable, jamais de secret.
- **Limiteur de connexions persistant** (il est en mémoire : remis à zéro au redémarrage).
- **Rôles par périmètre** (par pool ou par groupe de machines), en plus des 3 rôles actuels.
- **Critères de sortie** : une personne se connecte par le SSO de l'entreprise ; une action est attribuée à son nom **côté Kaji ET côté Proxmox** (journal de Proxmox relu en réel) ; **la base de Kaji seule ne permet pas de lire un jeton** (test automatisé) ; le planificateur tourne avec un jeton de service qui n'a que ses droits (refus constaté pour le reste) ; l'audit arrive dans le SIEM de test ; un compte à rôle restreint ne peut pas sortir de son périmètre (test automatisé + essai réel).

### J3. Pré-production (validation indépendante) : taille L, dépend de tiers
- **Relecture de sécurité par une personne tierce** (authentification, rôles, sessions, consoles, chiffrement des secrets) et **test d'intrusion**.
- **Corrections** de tout constat de gravité moyenne ou plus ; les autres notés dans `docs/securite.md`.
- **Validation en réel sur d'autres clusters** : 3 nœuds ou plus, **ZFS** (réplication), **Ceph**, **PBS**, **HA** réelle. Chaque fonction concernée passe de « expérimental » à « validé en réel » *ou* reste étiquetée telle.
- **Mise à jour d'une version à l'autre** (migrations de base) testée sur une base issue de la version précédente.
- **Robustesse** : comportement quand Proxmox est lent ou injoignable, nombre d'utilisateurs simultanés raisonnable (ordre de grandeur mesuré, pas promis).
- **Critères de sortie** : rapport de revue et de test d'intrusion archivé ; aucun constat ouvert de gravité moyenne ou plus ; fonctions annoncées = fonctions validées en réel (ou clairement limitées).

### J4. Production : V1 stable : taille M
- **Version signée** (images et sources), liste des composants (SBOM), `CHANGELOG` à jour.
- **Politique de support** : versions maintenues, délai de correctif de sécurité visé, procédure de mise à jour et de retour arrière.
- **Runbook d'exploitation** : supervision de Kaji lui-même, rotation des secrets (`KAJI_SECRET_KEY`, jetons Proxmox), restauration, incident.
- **Critères de sortie** : J1 à J3 remplis ; installation et mise à jour réalisées par un exploitant qui ne connaît pas le projet ; texte d'annonce relu.

## Ce que l'agent fait seul, ce qui dépend d'autres
| Jalon | Agent (PC A ou B) | Enzo | Tiers |
|---|---|---|---|
| J1 | guide, `SECURITY.md`, changelog, épinglage des images, test de restauration | choisir le nom des versions, publier | **installer depuis zéro** |
| J2 | tout le code (identité par utilisateur, jeton de service, SSO, TOTP, audit, rôles) | ~~choisir l'option d'identité~~ **fait : option A** ; fournir un IdP de test (Keycloak, Entra, etc.) ; créer les comptes et jetons de test dans Proxmox | |
| J3 | corrections, tests de non-régression | fournir des clusters (ZFS, Ceph, PBS) | **relecture + test d'intrusion** |
| J4 | SBOM, signature, runbook | décision de passer en « stable » | exploitant non initié |

## Risques à garder en tête
- **Le jeton de Kaji reste une cible de choix** (option C et tâches de fond) : le limiter au strict nécessaire (`docs/api/acces.md`), ne jamais lui donner `Administrator` en entreprise.
- **Des défauts cachés dans le non-essayé** : le HTTPS fourni n'avait jamais tourné avant le 2026-11-13 et a montré trois défauts. Les fonctions « expérimentales » peuvent en cacher d'autres.
- **Fonctions réservées à `root@pam` par Proxmox** (moniteur QEMU, `affinity`, `hugepages`, `keyctl`/`fuse`/`mount`, création et jonction de cluster) : elles resteront dans l'interface Proxmox, quelle que soit la maturité de Kaji. À dire dans la page d'installation.
- **Charge de relecture** : une seule personne code et relit ; J3 existe pour corriger cela.

## Première étape proposée
1. ~~Enzo tranche l'option d'identité~~ **fait le 2026-11-14 : option A avec garde-fous.**
2. ~~Tickets et jalons GitHub (« J1 lab partageable » à « J4 production »).~~ **Fait le 2026-11-14** : J1 #425 à #429, J2 #440 à #448, J3 #449 à #457, J4 #458 à #463.
3. On commence par le guide d'installation en lab, parce qu'il révèle tout de suite ce qui manque à une installation neuve.
