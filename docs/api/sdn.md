# SDN : zones, VNets, sous-réseaux (M7-5)

Préfixe `/api/connections/{conn_id}/sdn`. Chez Proxmox, toute écriture SDN est **en attente** : rien n'agit sur les nœuds tant qu'on n'**applique** pas, et on peut tout annuler.

| Route | Rôle |
|---|---|
| `GET /zones`, `GET /vnets`, `GET /vnets/{vnet}/subnets` | Lecture avec les modifications en attente (`state` : `new`, `changed`, `deleted`) |
| `POST /zones`, `PUT /zones/{zone}`, `DELETE /zones/{zone}` | Zones `simple`, `vlan`, `qinq`, `vxlan`, `evpn` |
| `POST /vnets`, `PUT /vnets/{vnet}`, `DELETE /vnets/{vnet}` | VNets (`zone`, `alias`, `tag`, `vlanaware`, `isolate_ports`) |
| `POST /vnets/{vnet}/subnets`, `PUT|DELETE …/subnets/{subnet}` | Sous-réseaux : `subnet` = CIDR à la création (`10.99.0.0/24`), identifiant `zone-adresse-préfixe` ensuite ; `gateway`, `snat`, `dhcp_range` (`[{start,end}]`), `dhcp_dns_server`, `dnszoneprefix` |
| `POST /apply` | Applique la configuration en attente sur tous les nœuds (tâche Proxmox) |
| `POST /rollback` | Annule la configuration en attente |

Champs par type de zone : `vlan` (`bridge`), `qinq` (`bridge`, `tag`, `vlan_protocol`), `vxlan` (`peers`, `vxlan_port`), `evpn` (`controller`, `vrf_vxlan`, `exitnodes`, `exitnodes_primary`, `exitnodes_local_routing`, `advertise_subnets`, `disable_arp_nd_suppression`, `rt_import`) ; communs : `nodes`, `mtu`, `ipam`, `dns`, `reversedns`, `dnszone`, `dhcp`. Un champ d'un autre type ou un champ exigé manquant : 422. `clear: [...]` retire des champs ; `digest` relu et transmis.

## Garde-fous
- Identifiants : 8 caractères, minuscules et chiffres. Zone ou VNet qui existe déjà : 409. Supprimer une zone qui a des VNets, ou un VNet qui a des sous-réseaux : 409. Sous-réseau qui en chevauche un autre : 409.
- VNet d'une zone `vlan`/`qinq` : `tag` 1-4094 obligatoire ; zone `simple` : pas de tag. Passerelle dans le sous-réseau, plage DHCP dans le sous-réseau et avec passerelle.
- **Préparer** : `confirm` suffit (inerte). `dry_run` montre les paramètres.
- **Appliquer** : `acknowledge_live` toujours ; **`COUPURE POSSIBLE`** en plus si une zone autre que `simple` est créée ou modifiée (VLAN, VXLAN, EVPN touchent le réseau des nœuds) ou si une zone ou un VNet est supprimé (les machines branchées perdent leur réseau). Rien en attente : 409.
- Relecture après écriture (502 si Proxmox n'a pas enregistré), audit `sdn-zone-*`, `sdn-vnet-*`, `sdn-subnet-*`, `sdn-apply`, `sdn-rollback`.

## Droit requis
L'écriture exige **`SDN.Allocate` sur `/sdn`**. Le token permanent de Kaji ne l'a pas (constaté en réel le 2026-11-09 : « Permission check failed (/sdn/zones, SDN.Allocate) »). À accorder dans Proxmox (rôle `PVESDNAdmin` sur `/sdn` au token de Kaji) pour utiliser ces routes ; la lecture marche déjà.

## Non testé en réel
Toute écriture (droit manquant), donc aussi la forme exacte de la réponse `pending=1` (les formes `state` / `pending` sont gérées de façon tolérante) et le format de l'identifiant de sous-réseau à la création.


## Suite : contrôleurs, IPAM, DNS, fabrics (M7-5b)
Mêmes routes sous le même préfixe, mêmes verrous (`confirm`, `dry_run`, `clear`, `digest`, relecture, audit `sdn-controller-*`, `sdn-ipam-*`, `sdn-dns-*`, `sdn-fabric-*`, `sdn-fabric-node-*`).

| Objet | Routes | Remarques |
|---|---|---|
| Contrôleurs | `GET/POST /controllers`, `PUT/DELETE /controllers/{id}` | Types `evpn` (asn, peers), `bgp` (asn, node, peers, ebgp, ebgp_multihop, loopback…), `isis` (node, isis_domain, isis_net, isis_ifaces…). **En attente.** Suppression refusée si une zone l'utilise |
| IPAM | `GET/POST /ipams`, `PUT/DELETE /ipams/{id}` | `pve` (intégré, jamais supprimé), `netbox` (url, token), `phpipam` (url, token, section) ; `fingerprint` SHA-256. **Pas d'état « en attente » chez Proxmox : écriture immédiate** ; `acknowledge_live` si une zone s'en sert ; suppression refusée si une zone l'utilise |
| DNS | `GET/POST /dns`, `PUT/DELETE /dns/{id}` | `powerdns` (url, key, ttl, reversemaskv6, fingerprint), même logique que l'IPAM |
| Fabrics | `GET/POST /fabrics`, `PUT/DELETE /fabrics/{id}` ; nœuds : `GET /fabrics/{id}/nodes`, `POST/PUT/DELETE /fabrics/{id}/nodes/{node}` | Protocoles `ospf` (area) et `openfabric` (hello_interval, csnp_interval) ; préfixe IPv4 et/ou IPv6. Nœud : `ip` ou `ip6`, `interfaces: [{name}]` (autres options d'interface non gérées). **En attente.** Suppression refusée s'il reste des nœuds ou si un contrôleur l'utilise |

- **Secrets** (`token` IPAM, `key` DNS) : `SecretStr`, jamais relus (la lecture dit seulement `token_set` / `key_set`), jamais renvoyés (`dry_run` affiche `***`), jamais dans l'audit (« secret défini »).
- **Appliquer** : un contrôleur ou un fabric en attente (BGP, EVPN, IS-IS, OSPF, OpenFabric) exige la phrase `COUPURE POSSIBLE` ; `pending` du résumé liste aussi `controllers` et `fabrics` (nœuds : `fabric/nœud`).
- **Droit** : mêmes exigences (`SDN.Allocate` sur `/sdn` ; nœuds de fabric : aussi `Sys.Modify` sur le nœud).
- **Non testé en réel** : tout (droit manquant), en particulier la forme de `pending=1` pour contrôleurs et fabrics, le format des interfaces de nœud de fabric (`name=nic1`) et la réponse de `fabrics/node` (`node_id`).


## Validé en réel le 2026-11-13 (droit accordé par Enzo : `PVESDNAdmin` sur `/sdn` à l'utilisateur ET au jeton)
- Le jeton de Kaji a la séparation de privilèges : ses droits sont l'**intersection** de ceux de l'utilisateur `kaji@pve` et des siens. Donner le rôle au seul jeton ne suffit pas (« Droits insuffisants ») : il faut `pveum acl modify /sdn --users 'kaji@pve' --roles PVESDNAdmin` **et** `--tokens 'kaji@pve!kaji'`.
- Zone `simple` et VNet créés **en attente** (`state: new`, `applied: false`), puis annulés par `POST /rollback` : listes revenues vides, rien appliqué sur les nœuds.
- **Défaut trouvé en réel et corrigé** : créer un sous-réseau échouait (« create sdn subnet object failed: 400 Parameter verification failed »). Le schéma de Proxmox 9 exige `vnet` aussi dans le **corps** de la création (en plus du chemin) ; Kaji ne l'envoyait pas, et le faux Proxmox ne le contrôlait pas. Le faux Proxmox est maintenant strict sur ce point (4 tests échouaient avant la correction).
- Lire les sous-réseaux d'un VNet inconnu : Proxmox répond 500 « does not exist » ; Kaji renvoie maintenant **404 « VNet inconnu »** (les autres pannes restent des erreurs).
- **Aussi validés en réel le 2026-11-13 (tout en attente puis `rollback`, rien appliqué)** : zones `vlan`, `qinq`, `vxlan` et `evpn` (avec un contrôleur `evpn`), VNet d'une zone VLAN avec `tag` (sans `tag` : refusé 422), modification d'une zone en attente (`mtu`), contrôleur `evpn` en attente ; fabrics `openfabric` et `ospf` créées en attente.
- **Second défaut trouvé en réel et corrigé (fabrics)** : Proxmox accepte la création mais Kaji répondait « n'a pas enregistré la modification », car il ne retrouvait pas l'objet. Sortie réelle de `pvesh get /cluster/sdn/fabrics/fabric --pending 1` : `{"digest":…,"pending":{"id":"kfab","ip_prefix":…,"protocol":"openfabric"},"state":"new"}` : un objet NEUF n'a ni `id` ni `protocol` au premier niveau, tout est dans `pending`. Kaji lit maintenant l'identifiant et le protocole dans la valeur effective (pending par-dessus le courant), pour les fabrics et leurs nœuds.
- **Jamais essayés en réel** : appliquer (`apply`, interdit sur le cluster réel), IPAM et DNS (écriture immédiate chez Proxmox, secrets exigés : non saisis), nœuds de fabric, contrôleurs `bgp` et `isis`, la forme des nœuds de fabric en attente.
- **Troisième correction, la bonne (sous-réseau)** : ajouter `vnet` dans le corps (PR #371) ne suffisait pas, la création échouait encore. Le réseau doit être envoyé en **CIDR** (`10.99.0.0/24`) dans `subnet` ; Proxmox fabrique lui-même l'identifiant `zone-adresse-préfixe` (ici `kajitest-10.99.0.0-24`). L'identifiant envoyé à la création était refusé. **Validé en réel par l'API ET par l'interface** (page Réseau, section SDN : « Ajouter une zone… », « Ajouter un VNet… », « + sous-réseau », chacun avec « Aperçu des verrous » puis « Confirmer », puis « Annuler les modifications… » : « Modifications SDN annulées », tout vide).
- Aussi vus en réel : doublon (409), chevauchement (409) et modification de la passerelle d'un sous-réseau en attente ; fabrics `openfabric` et `ospf` créées en attente et listées après correction de la lecture.
