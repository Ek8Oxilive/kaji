# Cluster en écriture (M10-2) : créer, joindre, retirer un nœud

Option B de `docs/m10-cluster.md` (décision d'Enzo du 2026-11-12 : « fais M10 »). Trois routes, **toutes soumises à des verrous décidés par le serveur** ; validées sur un faux Proxmox strict seulement (voir « Essais réels »).

| Route | Où elle part | Proxmox |
|---|---|---|
| `POST /api/connections/{id}/cluster/create` | le nœud **isolé** que la connexion désigne | `POST /cluster/config` |
| `POST /api/connections/{id}/cluster/join` | le nœud **isolé et sans machine** que la connexion désigne | `POST /cluster/config/join` |
| `DELETE /api/connections/{id}/cluster/nodes/{node}` | un **autre** membre du cluster | `DELETE /cluster/config/nodes/{node}` |

Créer et joindre s'adressent au nœud qui change de cluster, pas au cluster : il faut donc une connexion Kaji vers ce nœud isolé. Après une jonction, la configuration du nœud (`/etc/pve`, donc les utilisateurs et le jeton de Kaji) est remplacée par celle du cluster : **la connexion à ce nœud ne marche plus**, il faut ajouter une connexion au cluster rejoint.

## Paramètres (schéma officiel de Proxmox 9, lu sur `apidoc.js`)
- **créer** : `clustername` (obligatoire, 15 caractères au plus : lettres, chiffres, tiret), `links[]` (`{link: 0 à 7, address: IP, priority: 0 à 255}`, envoyés `linkN=address=IP[,priority=N]`), `nodeid` (1 à 10 000), `votes` (1 à 10).
- **joindre** : `hostname` (nom ou IP d'un membre, adresses locales refusées), `fingerprint` (obligatoire, 32 octets hexadécimaux séparés par « : », « Join Information » de la page Cluster), `password` (mot de passe **root du membre contacté**, obligatoire), `links[]` (la priorité n'est pas envoyée : Proxmox l'ignore à l'ajout), `nodeid`, `votes` (0 à 10). L'option `force` de Proxmox n'est **pas** exposée.
- **retirer** : le nom du nœud dans l'URL, **retapé** dans `name` ; aucun paramètre envoyé à Proxmox.
Les champs inconnus sont ignorés ; les adresses de lien sont des IP (jamais un nom), ni locales, ni de multidiffusion, ni réservées.

## Verrous
Toujours `confirm=true` (sauf `dry_run=true`). Le serveur relit l'état chez Proxmox :

| Verrou | Se lève ? | Cas |
|---|---|---|
| **Refus** (`blockers`, 409) | **jamais** | créer / joindre sur un nœud déjà en cluster ; joindre avec des machines sur le nœud (Proxmox refuse), ou en contactant ce nœud lui-même ; retirer : nœud **en ligne**, nœud auquel Kaji est connecté, état inconnu, cluster **sans quorum** |
| **Machine protégée** (403) | jamais | retirer un nœud qui porte la configuration d'une machine de `KAJI_PROTECTED_VMIDS` (dont Kaji) |
| **Coupure possible** (409) | `acknowledge_cut_access=true` **et** `type_name="COUPURE POSSIBLE"` | **joindre** (toujours : la configuration du nœud est remplacée, la connexion de Kaji est perdue) ; **retirer** quand il restera moins de 3 nœuds |
| **Machines concernées** (409) | `acknowledge_guests=true` | retirer un nœud qui garde la configuration de machines (elles ne démarreront plus tant qu'elles ne sont pas déplacées) ; les ressources HA concernées sont listées |

`dry_run=true` renvoie `locks` (`blockers`, `cut`, `live`), `phrase` et ce qui serait envoyé, **sans rien écrire** (même pour un cas refusé : le refus est dans `blockers`).

## Réponses
- créer : `{"created", "node", "upid", "locks"}` ; joindre : `{"joining", "via", "upid", "locks"}` (`upid` = tâche Proxmox, `null` si la réponse n'en est pas une) ; retirer : `{"removed", "guests", "ha_resources", "locks"}` après relecture de `/cluster/config/nodes` (502 si le nœud y est toujours).
- Rien de Proxmox n'est recopié dans une erreur (messages fixes de `_px`).

## Sécurité
- **Le mot de passe root** n'existe que dans la requête de jonction : `SecretStr`, jamais renvoyé (l'aperçu écrit « défini »), jamais dans l'audit (« mot de passe : défini »), jamais dans une erreur ; l'interface l'efface à la fermeture. Caractères de contrôle refusés, 128 caractères au plus.
- Audit `cluster-create`, `cluster-join`, `cluster-remove-node` : succès, refus, erreur ; sans empreinte ni mot de passe.
- **Droit chez Proxmox : non documenté.** Le schéma officiel ne donne aucune clause `permissions` pour ces trois routes (probablement réservées à `root@pam`). Avec un jeton ordinaire, Proxmox répond 403, que Kaji traduit en « Droits insuffisants pour cette opération » ; **Kaji ne fabrique ni n'utilise de jeton root**, donc ces fonctions ne marcheront que si Enzo donne volontairement ce droit.

## Essais réels (2026-11-12)
Le cluster réel est déjà un cluster de 2 nœuds : **aucune écriture n'y est faite** (créer / joindre y sont impossibles, retirer un nœud en ligne est refusé). Seuls des `dry_run`, sans effet, y sont essayés (voir `docs/REPRISE.md`).
