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
