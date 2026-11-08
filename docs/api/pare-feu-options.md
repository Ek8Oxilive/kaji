# Pare-feu : options (datacenter, nœud, machine), écriture avec verrous

Routes : `PUT /api/connections/{id}/firewall/cluster/options`, `PUT …/firewall/nodes/{node}/options`, `PUT …/firewall/guests/{node}/{qemu|lxc}/{vmid}/options`.
Écriture avec le token de Kaji (`Sys.Modify` sur `/` ou sur le nœud, `VM.Config.Network` sur la machine). Décision d'Enzo : **tout est possible, rien n'est fait par accident** :
des verrous à déverrouillage explicite, décidés par le **serveur** sur l'état relu chez Proxmox.

## Champs (liste blanche par niveau)
- **Datacenter** : `enable`, `ebtables`, `policy_forward` (ACCEPT, DROP), `policy_in`, `policy_out` (ACCEPT, REJECT, DROP).
- **Nœud** : `enable`, niveaux de journal (`log_level_in|out|forward`, `smurf_log_level`, `tcp_flags_log_level`), `log_nf_conntrack`, `ndp`, `nf_conntrack_allow_invalid`, `nf_conntrack_helpers` (liste parmi amanda, ftp, irc, netbios-ns, pptp, sane, sip, snmp, tftp),
  `nf_conntrack_max` (≥ 32768), `nf_conntrack_tcp_timeout_established` (≥ 7875), `…syn_recv` (30 à 60), `nftables`, `nosmurfs`, `protection_synflood` (+ `_burst`, `_rate`), `tcpflags`.
- **Machine** : `enable`, `dhcp`, `ipfilter`, `macfilter`, `ndp`, `radv`, `log_level_in|out`, `policy_in`, `policy_out`.
- `clear: [...]` retire des réglages (retour à la valeur par défaut) ; `clear: ["enable"]` équivaut à **désactiver**. Un réglage à la fois modifié et retiré, un champ inconnu seul ou un corps vide : 422.
- Booléens et entiers **stricts** (un `"true"` ou un `1` à la place d'un booléen est refusé), bornes vérifiées avant tout appel à Proxmox. Non géré ici : `log_ratelimit`.

## Verrous
| Verrou | Quand | Pour passer |
|---|---|---|
| *(aucun)* | niveau **désactivé** et rien qui l'active : les réglages s'appliqueront à l'activation (la réponse le dit : `inactive_level`) | `confirm: true` |
| **actif** | le niveau filtre déjà (`enable` vrai) et on modifie, retire ou désactive quelque chose ; activer le pare-feu d'une machine | `confirm` + `acknowledge_live: true` |
| **coupure possible** | **activer** le pare-feu du datacenter ou d'un nœud ; passer `policy_in`/`policy_out`/`policy_forward` à `DROP` ou `REJECT` sur un niveau actif ou qu'on active ; toucher au pare-feu de la machine de Kaji (`KAJI_PROTECTED_VMIDS`) | `confirm` + `acknowledge_cut_access: true` **et** `type_name: "COUPURE POSSIBLE"` |

Refus : **409** avec les raisons en clair. Les deux verrous ne s'additionnent pas : « coupure possible » couvre « actif ».
**`dry_run: true`** (sans `confirm`) renvoie `{params, remove, locks: {cut, live, inert}, phrase}` **sans rien écrire** : c'est l'aperçu de l'interface.

## Garanties
- Le `digest` lu juste avant est transmis : Proxmox refuse si la configuration a changé entre-temps.
- Proxmox est relu après l'écriture ; si l'état ne correspond pas : **502**, jamais un faux succès.
- Audit `fw-options` (succès, refus, erreur), niveau et réglages écrits ; aucun secret.

## Ce que ce lot ne fait pas
Les **règles** (M7-3b) et le **réseau** (M7-4). Aucune analyse automatique de « mon adresse est-elle autorisée à joindre le port 8006 ? » : le verrou est volontairement large (toute activation, toute politique restrictive).
