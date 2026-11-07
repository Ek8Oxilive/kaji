# Ceph (lecture, écriture des pools, des moniteurs, des gestionnaires, des MDS et des OSD)

Lots C1, C2 et C3 de `docs/m12-ceph.md`. Toutes les routes exigent une session ouverte. **La lecture** (toutes les routes `GET`)
n'envoie que des lectures à Proxmox. **L'écriture** : créer et modifier un pool (« Écriture des pools »), puis créer, démarrer, arrêter
des moniteurs, gestionnaires, MDS et OSD, et mettre un OSD dedans ou dehors (« Écriture des services »). Il n'existe **aucune
suppression** (lot C4) ; l'**initialisation** est décrite plus bas (lot C5), l'installation des paquets n'a pas d'API chez Proxmox. Aucune
réponse ne contient de secret.

> **Rien de ce document n'a été validé en réel, sauf un point** (voir plus bas). Le cluster de test n'a pas de Ceph : un disque
> par nœud et deux nœuds seulement. Tout a été écrit et testé avec un **faux Proxmox**, d'après la connaissance de l'API de
> Proxmox, pas d'après un essai. Les formes décrites ci-dessous sont donc des **hypothèses**, et la mise en forme est tolérante
> pour cette raison.

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/ceph/status` | Santé et état du cluster Ceph (`ceph -s`) |
| `GET …/ceph/monitors` | Moniteurs |
| `GET …/ceph/managers` | Gestionnaires |
| `GET …/ceph/osds` | OSD à plat, drapeaux du cluster, résumé |
| `GET …/ceph/pools` | Pools et réglages de redondance |
| `GET …/ceph/filesystems` | CephFS et serveurs de métadonnées (MDS) |
| `GET …/ceph/config` | `ceph.conf` et base de configuration, secrets masqués |
| `GET …/ceph/log?limit=&start=` | Journal de Ceph |
| `GET …/ceph/rules` | Règles de placement CRUSH (lecture) |
| `POST …/ceph/pools` | **Écriture, non validée en réel** : créer un pool |
| `PUT …/ceph/pools/{name}` | **Écriture, non validée en réel** : modifier un pool |
| `POST …/ceph/nodes/{node}/monitors` | **Écriture, non validée en réel** : créer le moniteur du nœud |
| `POST …/ceph/nodes/{node}/managers` | **Écriture, non validée en réel** : créer le gestionnaire du nœud |
| `POST …/ceph/nodes/{node}/mds` | **Écriture, non validée en réel** : créer le MDS du nœud |
| `POST …/ceph/nodes/{node}/osds` | **Écriture, non validée en réel** : créer un OSD (**efface le disque**) |
| `POST …/ceph/nodes/{node}/osds/{id}/out` · `/in` | **Écriture, non validée en réel** : mettre un OSD dehors, dedans |
| `POST …/ceph/nodes/{node}/services/{osd\|mon\|mgr\|mds}/{name}/start` · `/stop` | **Écriture, non validée en réel** : démarrer, arrêter un service |
| `POST …/ceph/nodes/{node}/init` | **Écriture, non validée en réel** : initialiser Ceph (`pveceph init`) |

## Ceph non installé

Sur un cluster sans Ceph, Proxmox répond **500 « binary not installed: /usr/bin/ceph-mon »**. Kaji le traduit, sur **toutes** les
routes, en une réponse **200** claire :

```json
{"installed": false, "message": "Ceph n'est pas installé sur ce cluster."}
```

- Le texte brut de Proxmox (le chemin du binaire) n'est **jamais** renvoyé.
- Le message est cherché dans la **phrase de statut HTTP et dans le corps** de la réponse : on ne sait pas lequel des deux Proxmox
  utilise. Il n'est reconnu **que sur un code 500**. Toute autre erreur (401, 403, 404, 500 sans ce message, 502) reste une erreur
  502, qui ne dit jamais « non installé ».
- Quand Ceph est présent, chaque réponse contient `"installed": true`.

## Choix du nœud

Hormis `status` (cluster entier), les routes interrogent un **nœud**. `?node=` (même regex que les autres routes) en choisit un ;
sinon Kaji essaie les **nœuds en ligne**, par ordre alphabétique, et garde le premier qui a Ceph (Ceph peut ne pas être installé
sur tous). Un nœud choisi explicitement qui n'a pas Ceph donne « non installé », **sans** repli. Aucun nœud en ligne : 503. La
réponse indique le nœud interrogé dans `node`.

## Formes des réponses

Toute valeur absente ou d'un type inattendu devient `null` (ou une liste vide) : elle n'est jamais devinée ni ne fait échouer la
page.

**`status`**

| Champ | Sens |
|---|---|
| `health.status` | `HEALTH_OK`, `HEALTH_WARN`, `HEALTH_ERR`, ou **`UNKNOWN`** pour toute autre valeur (jamais devinée) |
| `health.checks[]` | `code`, `severity`, `message`, `count`, `muted`, `details[]` |
| `osds` | `total`, `up`, `in` |
| `mons` | `total`, `quorum[]` (noms) |
| `mgr` | `active`, `standbys` (nombre), `available` |
| `pgs` | `total`, `states[]` (`state`, `count`), `all_clean` (vrai seulement s'il y a des groupes **et** tous sont `active+clean`) |
| `usage` | `total`, `used`, `avail` (octets), `percent` (`null` si le total est inconnu ou nul) |
| `io` | `read_bytes_sec`, `write_bytes_sec`, `read_ops`, `write_ops` |

**`monitors`** : `name`, `host`, `addr`, `rank`, `in_quorum` (vrai, faux, ou `null` si Proxmox ne le dit pas), `state`, `version` ;
triés par rang. **`managers`** : `name`, `host`, `addr`, `state`, `version`.

**`osds`** : l'arbre CRUSH de Proxmox (racine, hôtes, OSD) est **aplati** en `osds[]` avec `id`, `name`, `host`, `up`, `in`,
`device_class`, `crush_weight`, `reweight`, `percent_used`, `used`, `total`, `pgs`, `version`, triés par identifiant. `up` vaut
`null` (inconnu) quand Proxmox ne donne pas d'état. Plus `flags[]` (drapeaux du cluster comme `noout`) et `summary`
(`total`, `up`, `in`). L'arbre est borné (profondeur 12, 5 000 nœuds).

**`pools`** : `name`, `id`, `type`, `size`, `min_size`, `pg_num`, `crush_rule`, `autoscale`, `used`, `percent_used`,
`applications[]`, `warnings[]`. Les **avertissements ne font que signaler** (rien n'est modifié) :
- `size` inférieur à 2 : une seule copie, la panne d'un disque fait perdre des données ;
- `min_size` à 1 avec `size` de 2 ou plus : Ceph accepte d'écrire sur une seule copie ;
- `min_size` supérieur à `size` : les écritures seront bloquées.
Un réglage absent ne déclenche **aucun** avertissement.

**`filesystems`** : `filesystems[]` (`name`, `metadata_pool`, `data_pools[]`) et `mds[]` (`name`, `host`, `addr`, `rank`, `state`).

**`config`** : `conf` (`text`, `truncated`), `entries[]` (`section`, `name`, `level`, `value`, `runtime`) et `unavailable[]`. Si la
base de configuration est illisible alors que `ceph.conf` l'est, `entries` est vide et `unavailable` vaut `["db"]` : l'absence est
**signalée**, pas cachée. Si `ceph.conf` est illisible, c'est une erreur 502.

**`log`** : `lines[]` (`n`, `text`). `limit` de 1 à 500 (100 par défaut), `start` de 0 à 1 000 000 000 ; hors de ces bornes : 422, et
rien n'est envoyé à Proxmox.

## Secrets

Le `ceph.conf`, la base de configuration et le journal passent par un masquage : toute valeur dont le **nom** contient `key`,
`secret`, `passw…`, `token` ou `credential` devient `[masqué]` (le journal masque aussi les paires `clé=valeur` dans le texte
libre). C'est volontairement large : `keyring = …` est masqué aussi. Le texte est borné (200 000 octets pour `ceph.conf`, 500
caractères par ligne). **Ceph ne met normalement pas de secret dans ces textes** (les trousseaux sont des fichiers à part) : ce
masquage est une précaution, pas une réponse à un cas observé.

## Écriture des pools (lot C2) : NON VALIDÉE EN RÉEL

> **Aucune de ces écritures n'a jamais tourné sur un vrai Ceph** (le cluster de test n'en a pas). Elles sont testées avec un faux
> Proxmox. Les **noms et bornes des paramètres** viennent de la documentation officielle de `pveceph pool create` et `pveceph pool
> set` ; **le comportement réel** (réponse, durée, effet sur le cluster) n'a jamais été vu. L'interface l'affiche dans un bandeau.
> **Ne pas utiliser sur un Ceph en production avant validation sur un Ceph jetable** (`docs/m12-ceph.md` §5).

Une erreur sur un pool détruit les données de **toutes** les machines qui s'y appuient. D'où des garde-fous **vérifiés côté serveur**,
chacun avec un test qui échoue si on le retire.

**`POST /ceph/pools`** : crée un pool **répliqué** (pas de pool à effacement, pas de suppression).

| Champ | Validation | Défaut |
|---|---|---|
| `name` | lettres, chiffres, `_`, `-`, `.` ; 63 caractères au plus ; **jamais de point initial** (les pools internes de Ceph, comme `.mgr`, commencent par un point) | obligatoire |
| `size` | entier de **2** à 7 (**une seule copie est refusée**) | 3 |
| `min_size` | entier de **2** à 7 (**`min_size` à 1 est refusé**), jamais supérieur à `size` | 2 |
| `pg_num` | **puissance de 2**, de 1 à 32768 | 128 |
| `autoscale` | `on`, `off` ou `warn` | `warn` |
| `application` | `rbd`, `cephfs` ou `rgw` | `rbd` |
| `crush_rule` | une règle que **Proxmox connaît** (lue chez lui) ; illisible : 502, jamais ignorée | règle par défaut |
| `add_storage` | booléen ; crée aussi le stockage RBD du pool (**définition de stockage pour tout le cluster**) ; seulement avec `rbd` ; **exige `confirm`** | `false` |
| `confirm` | booléen, **jamais transmis à Proxmox** ; voir « Confirmation à la création » | `false` |

Tout autre champ (`erasure-coding`, `target_size`, `force`, un `node` dans le corps…) est **ignoré et jamais transmis**. Refus avant tout
appel d'écriture : santé **`HEALTH_ERR` ou inconnue** (409), pool **déjà existant** (409), règle CRUSH **inconnue** (422), Ceph **non
installé** (409, jamais un 200 : ce n'est pas une lecture). La création est acceptée en `HEALTH_OK` et `HEALTH_WARN`.

**Confirmation à la création** (décidée par le **serveur**, après tous les refus ci-dessus et avant l'écriture) : sans `confirm: true`, 400
« Confirmation requise (…) : raison ; raison » et rien n'est écrit, dans deux cas :
- **`size` à 2** : seulement deux copies, la perte de deux disques (ou d'un nœud et d'un disque) fait perdre des données ;
- **`add_storage`** : la définition de stockage créée vaut pour **tout le cluster**.

Un pool à 3 copies sans `add_storage` n'en demande pas.

**`PUT /ceph/pools/{name}`** : mise à jour partielle. Seuls les champs fournis **et différents de l'existant** sont envoyés ; si rien
ne diffère, 400 « Aucun changement ».
- **Non risqués** (`autoscale`, `application`) : passent sans condition de santé ni confirmation.
- **Risqués** (`size`, `min_size`, `pg_num`, `crush_rule`), car ils **déplacent ou dupliquent des données** : refusés tant que la santé
  n'est pas **`HEALTH_OK`** (même avec confirmation), puis exigent **`confirm: true`**. Sans lui, 400 « Confirmation requise (…) : raison ;
  raison », avec ce que Ceph va faire (par exemple « RÉDUIT le nombre de copies (de 3 à 2) »). `confirm` n'est **jamais** transmis à
  Proxmox. L'interface affiche ces raisons puis renvoie avec `confirm: true`.
- Les valeurs **effectives** sont vérifiées : `min_size` ne peut pas dépasser `size`, même si seul l'un des deux est modifié.
  **Choix assumé** : si le `size` actuel du pool est **illisible** (absent de la réponse de Proxmox), cette vérification est sautée et
  c'est Proxmox qui refuse une valeur incohérente ; Kaji ne devine pas.
- **Pool à effacement** : `size` et `crush_rule` sont refusés (409), comme le dit la documentation de Proxmox ; `min_size` est permis.
- Pool inconnu : 404.

**Une seule écriture Ceph à la fois par connexion** : une seconde, pendant que la première s'exécute, est refusée (409). La tâche que
Proxmox lance peut durer plus longtemps que la requête ; c'est la **barrière de santé** qui empêche d'enchaîner une seconde modification
risquée pendant que Ceph redistribue les données (la santé n'est plus `HEALTH_OK`).

**Audit** : `ceph-pool-create` et `ceph-pool-update` pour chaque succès (avec l'UPID), refus et erreur, sans secret.

**Réponses** : `202 {"upid", "node", "pool"}` à la création ; `200 {"upid", "node", "pool", "changes"}` à la modification. `upid` vaut
`null` si Proxmox ne renvoie pas de tâche (cas non vérifié).

**Non validé en réel, et à vérifier sur un Ceph jetable** : que `POST` et `PUT /nodes/{node}/ceph/pool` acceptent exactement ces
paramètres et renvoient une tâche ; que `GET /nodes/{node}/ceph/rules` existe et renvoie des noms de règles (`name` ou `rule_name`) ;
que la santé lue dans `/cluster/ceph/status` reflète bien la redistribution en cours ; que `add_storages` crée le stockage attendu ; le
**comportement de Ceph** quand on abaisse `size` ou qu'on change `pg_num` ou la règle (durée, charge, risque réel).

## Écriture des services (lot C3) : NON VALIDÉE EN RÉEL

> **Aucune de ces écritures n'a jamais tourné sur un vrai Ceph.** Elles sont testées avec un faux Proxmox. Les noms de routes et de
> paramètres de Proxmox viennent de sa documentation (`pveceph mon|mgr|mds|osd create`, `ceph start|stop`), jamais d'un essai. À ne pas
> utiliser sur un Ceph de production avant validation sur un Ceph jetable. **Hypothèse assumée** : le domaine de panne est l'**hôte**
> (règle CRUSH par défaut) ; une règle qui sépare autrement n'est pas comprise.

Toutes ces routes sont sous `…/ceph/nodes/{node}/` : le **nœud est l'endroit où l'on agit** et doit exister et être **en ligne**
(sinon 404, rien n'est écrit). Ceph non installé : **409**, jamais un 200. Réponse : `202 {"upid", "node"}`. **Aucune route de
suppression** (lot C4) : `DELETE`, `PUT`, `PATCH` répondent 404 ou 405.

| Opération | Refus avant tout appel d'écriture | Confirmation décidée par le serveur |
|---|---|---|
| **Créer un moniteur** | santé `HEALTH_ERR` ou inconnue (409) ; le nœud en a déjà un (409) | si le total devient **pair** (n'améliore pas la tolérance) |
| **Créer un gestionnaire** | santé ERR ou inconnue ; le nœud en a déjà un | non |
| **Créer un MDS** (`hotstandby` optionnel) | santé ERR ou inconnue ; le nœud en a déjà un | non |
| **Créer un OSD** (`dev`, `encrypted`, `device_class` parmi `hdd`, `ssd`, `nvme`) | santé ERR ou inconnue ; disque **absent de la liste des disques inutilisés** du nœud (lue chez Proxmox, `type=unused`) ou déjà utilisé (409) | **toujours** : « EFFACE ENTIÈREMENT le disque… », puis `confirm_dev` = **nom exact du disque retapé** (400 sinon) |
| **OSD dehors** | santé **différente de `HEALTH_OK`** (même avec confirmation) ; déjà dehors ; **moins d'hôtes utiles que le `min_size` du pool le plus exigeant** : des données deviendraient indisponibles | **toujours** ; ajoute « redondance DÉGRADÉE » s'il reste moins d'hôtes que `size` |
| **OSD dedans** | santé ERR ou inconnue ; déjà dedans | non |
| **Démarrer** un service | n'existe pas ou n'est pas sur ce nœud ; OSD déjà démarré. **Pas de barrière de santé** : démarrer répare, c'est autorisé même en `HEALTH_ERR` | non |
| **Arrêter** un service | santé ≠ `HEALTH_OK` (même avec confirmation) ; absent ou sur un autre nœud ; OSD déjà arrêté ; **moniteur** : quorum perdu (majorité) ou état du quorum illisible ; **OSD** : même règle que « dehors » | **toujours** ; dit si c'est le **dernier gestionnaire** ou le **seul MDS actif** (CephFS indisponible) |

`confirm` doit être le booléen JSON `true` (**ni `"true"`, ni `1`**). Il n'est **jamais transmis** à Proxmox. Les confirmations ne
contournent aucun refus. Champs inconnus (`db_dev`, `wal_dev`, `force`, un `node` dans le corps…) : **ignorés, jamais transmis**.
`dev` : `/dev/` puis lettres, chiffres, `_`, `-` et `/` (jamais `//` ni `..`), 69 caractères au plus.
**Pas encore géré** : disque de journal DB/WAL, redémarrage, scrub, rééquilibrage, nom de moniteur ou de MDS libre (le nom par défaut
est celui du nœud).

**Une seule écriture Ceph à la fois par connexion** (le même verrou que les pools). **Audit** : `ceph-mon-create`, `ceph-mgr-create`,
`ceph-mds-create`, `ceph-osd-create`, `ceph-osd-out`, `ceph-osd-in`, `ceph-service-start`, `ceph-service-stop`, pour chaque succès (avec
l'UPID), refus et erreur.

**Non validé en réel, et à vérifier sur un Ceph jetable** : que `POST /nodes/{node}/ceph/mon|mgr|mds|osd`,
`…/osd/{id}/in|out` et `…/ceph/start|stop` acceptent exactement ces paramètres et renvoient une tâche ; que `GET /nodes/{node}/disks/list?type=unused`
renvoie `devpath`, `size`, `model` et un `used` vide pour un disque libre (un disque dont `used` est renseigné est refusé) ; que
`quorum` et `host` des moniteurs sont bien présents (sinon l'arrêt est **refusé**, par prudence) ; les valeurs de `state` des
gestionnaires (`active`, `standby`) et des MDS (`up:…`) ; que la santé reflète une redistribution en cours ; le **comportement réel** de
Ceph (durée, charge) à l'arrêt ou à la mise dehors d'un OSD. Si l'hôte d'un OSD est illisible, toute action dessus est refusée.

## Initialisation (lot C5) : NON VALIDÉE EN RÉEL

> **Jamais essayée sur un vrai Ceph.** `POST /nodes/{node}/ceph/init` et ses paramètres (`network`, `cluster-network`, `size`, `min_size`)
> viennent de l'API de Proxmox (documentation générée), pas d'un essai. **L'installation des paquets n'a pas d'API chez Proxmox** : elle
> se fait avec `pveceph install` dans le shell du nœud ; Kaji ne l'automatise pas, l'assistant affiche seulement la commande.

`POST …/ceph/nodes/{node}/init` — corps : `network` (CIDR, obligatoire), `cluster_network` (CIDR, facultatif), `size` (2 à 7, défaut 3),
`min_size` (2 à 7, défaut 2, jamais supérieur à `size`), `confirm`. Réponse `202 {"upid", "node", "initialized": true}` (`upid` vaut
`null` : Proxmox ne renvoie sans doute pas de tâche, non vérifié).

- **Réseaux** : format CIDR strict (pas de nom d'hôte, pas de masque `255.255.255.0`, pas d'espace). Le réseau est **normalisé** à son
  adresse de réseau (`10.10.10.77/24` devient `10.10.10.0/24`). Refusés : adresse nulle, boucle locale, multicast, lien local, préfixe
  hors de /8 à /30 (IPv4) ou /32 à /120 (IPv6), réseau de cluster identique au réseau public.
- **Refus avant l'écriture** : nœud inconnu ou hors ligne (404) ; Ceph **non installé** (409, avec le rappel `pveceph install`) ; Ceph
  **déjà initialisé** (409) quand `ceph.conf` est lisible et non vide. Une configuration illisible est considérée comme « pas encore
  initialisé » : **c'est une hypothèse**, Kaji ne sait pas distinguer cet état de « non installé » autrement.
- **Confirmation décidée par le serveur** : toujours (« initialise Ceph pour TOUT le cluster… »), avec en plus un avertissement si un
  réseau n'est **pas privé** ou si `size` vaut 2. `confirm` doit être le booléen JSON `true`, il n'est jamais transmis à Proxmox.
- **`disable_cephx` et `pg_bits` n'existent pas ici** : la sécurité de Ceph reste active, ces champs sont ignorés et jamais transmis.
- Une seule écriture Ceph à la fois par connexion. **Audit** : `ceph-init` (succès, refus, erreur), sans secret ni contenu de `ceph.conf`.

**Après l'initialisation** : créer le premier moniteur et le premier gestionnaire (lot C3), puis des OSD et un pool. **Non validé** : que
Kaji puisse lire l'état de Ceph, et donc créer un moniteur, **avant** que le premier moniteur existe. Si Proxmox refuse de répondre à
ces lectures, la création du premier moniteur est refusée par Kaji (502) ; il faut alors utiliser `pveceph mon create` dans le shell.

## Ce qui a été validé en réel, et ce qui ne l'a pas été

**Validé en réel** (par PC A, sur le cluster de test, en lecture seule) : **un seul fait**. Sans Ceph, `/cluster/ceph/status`
répond 500 `binary not installed: /usr/bin/ceph-mon`.

**Non validé en réel, faute de Ceph :**
- **toutes les formes de réponse** ci-dessus (`status`, moniteurs, gestionnaires, arbre des OSD, pools, CephFS, MDS,
  configuration, journal) et les noms des champs de Proxmox (par exemple `ceph_version_short`, `pg_autoscale_mode`,
  `application_metadata`) ;
- **où Proxmox met le message « non installé »** (phrase de statut ou corps) : les deux sont reconnus, aucun n'est constaté ;
- **la réponse de `/nodes/{node}/ceph/…`** quand Ceph n'est pas installé : seul `/cluster/ceph/status` a été observé ; on suppose
  que les routes de nœud répondent de la même façon ;
- **Ceph installé mais non initialisé** (pas encore de `ceph.conf`) : Proxmox répond sans doute autre chose ; Kaji le traitera
  comme une erreur 502, pas comme « non installé » ;
- **le repli d'un nœud à l'autre** : testé seulement avec le faux Proxmox ;
- **`status` n'est pas interrogé nœud par nœud** : `/cluster/ceph/status` est servi par le nœud auquel Kaji est connecté. Si Ceph
  n'est installé que sur d'autres nœuds, cette route répondrait « non installé » alors que les autres routes (qui essaient tous les
  nœuds) trouveraient Ceph. Non vérifié ;
- **la taille réelle** d'un `ceph.conf`, d'un arbre d'OSD ou d'un journal sur un grand cluster.

Validation en réel possible dès qu'un Ceph existe, même vide (`docs/m12-ceph.md`, §4 et §5).
