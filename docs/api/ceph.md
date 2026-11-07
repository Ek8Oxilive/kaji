# Ceph (lecture seule)

Lot C1 de `docs/m12-ceph.md`. Toutes les routes exigent une session ouverte. **Elles sont toutes en `GET` : aucune écriture
n'existe** (`POST`, `PUT`, `PATCH` et `DELETE` répondent 405), et Kaji n'envoie que des lectures à Proxmox. Aucune réponse ne
contient de secret.

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
