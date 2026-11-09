# Pare-feu : règles en écriture (M7-3b)

Créer, modifier, déplacer et supprimer des règles au datacenter, sur un nœud, sur une machine et dans un groupe de sécurité. Préfixe : `/api/connections/{conn_id}/firewall`.

| Niveau | Créer (`POST`) | Modifier (`PUT`) | Déplacer (`PUT`) | Supprimer (`DELETE`) |
|---|---|---|---|---|
| Datacenter | `/cluster/rules` | `/cluster/rules/{pos}` | `/cluster/rules/{pos}/move` | `/cluster/rules/{pos}` |
| Nœud | `/nodes/{node}/rules` | `…/rules/{pos}` | `…/rules/{pos}/move` | `…/rules/{pos}` |
| Machine | `/guests/{node}/{qemu\|lxc}/{vmid}/rules` | idem | idem | idem |
| Groupe | `/groups/{group}/rules` | idem | idem | idem |

La lecture reste `GET /firewall/cluster`, `/firewall/nodes/{node}`, `/firewall/guests/…`, `/firewall/cluster/groups/{name}`.

## Corps
- **Créer** : `type` (`in`, `out`, `forward`, `group`) et `action` (`ACCEPT`, `DROP`, `REJECT`, ou le nom d'un groupe existant si `type=group`) obligatoires ; `enable` (booléen strict, **faux par défaut**), `source`, `dest` (adresses, plages, alias, `+ipset`), `proto`, `sport`, `dport`, `iface`, `macro` (vérifiée contre `/cluster/firewall/macros`), `log`, `icmp_type`, `comment`, `pos` (insertion).
- **Modifier** : seuls les champs fournis changent ; `clear: [...]` retire des champs (`source`, `dest`, `proto`, `sport`, `dport`, `iface`, `macro`, `log`, `icmp_type`, `comment`).
- **Déplacer** : `moveto`.
- Verrous communs : `confirm`, `acknowledge_live`, `acknowledge_cut_access`, `type_name`, `dry_run` (pour `DELETE`, en paramètres de requête).
- Niveau groupe : `in`/`out` seulement. Niveau machine : pas de `forward`. Champs inconnus ignorés, jamais transmis.

## Verrous (décidés par le serveur sur l'état relu chez Proxmox)
1. **Inerte** : le pare-feu du datacenter OU celui du niveau est désactivé, ou la règle est désactivée avant et après : `confirm` suffit.
2. **Actif** : la règle (avant ou après) agit sur un pare-feu actif ⇒ `acknowledge_live=true`.
3. **Coupure possible** ⇒ `acknowledge_cut_access=true` et `type_name="COUPURE POSSIBLE"` :
   - une règle `DROP`/`REJECT` entrante ou transférée qui touche TCP 22, 3128, 8006, 5900-5999, les macros `SSH`, `VNC`, `SPICEproxy`, ou tout le trafic (datacenter, nœud, groupe) ;
   - retirer, désactiver, modifier ou déplacer une règle `ACCEPT` qui autorise ces ports quand la politique entrante est restrictive (absente = `DROP`, comme Proxmox) ;
   - toute règle active d'une machine de `KAJI_PROTECTED_VMIDS` (dont le CT 116, Kaji lui-même).
4. Un déplacement est analysé dans les deux sens (ce qu'il peut autoriser et ce qu'il peut bloquer).

`dry_run=true` renvoie `{params, locks, phrase}` sans rien écrire. Le `digest` de la règle est relu et transmis (refus si les règles ont changé entre-temps). Après l'écriture, les règles sont relues : si Proxmox n'a pas appliqué, **502**.

## Audit
`fw-rule-create|update|move|delete`, cible `<niveau>#<pos>`, succès, refus et erreurs. Aucun secret.

## Non testé en réel
Voir le ticket : seules des règles **inertes** sont essayées en réel (pare-feu du datacenter désactivé, ou pare-feu de la VM 115).
