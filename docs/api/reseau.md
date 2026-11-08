# Réseau d'un nœud et pare-feu (lecture seule)

Préfixe : `/api/connections/{id}`. **Aucune écriture** : voir `docs/m7-reseau-firewall.md`. Tout est en liste blanche, les textes sont bornés et sans caractère de contrôle,
et une valeur hors liste (type, action, niveau de journal…) devient `null` au lieu d'être transmise.

| Route | Rôle |
|---|---|
| `GET /nodes/{node}/network` | `{interfaces, changes, pending}` : bridges, bonds, VLAN, cartes ; `changes` = le **diff texte des modifications en attente** (20 000 caractères au plus), `pending` vrai s'il y en a |
| `GET /firewall/cluster` | pare-feu du datacenter : `{options, rules, aliases, ipsets, groups}` |
| `GET /firewall/cluster/ipsets/{name}` | entrées d'un IPSet `[{cidr, comment, nomatch}]` |
| `GET /firewall/cluster/groups/{name}` | règles d'un groupe de sécurité |
| `GET /firewall/nodes/{node}` | `{options, rules}` du pare-feu d'un nœud |
| `GET /firewall/guests/{node}/{qemu\|lxc}/{vmid}` | `{options, rules}` du pare-feu d'une machine |

- **Interfaces** : `iface`, `type` (`bridge`, `bond`, `eth`, `vlan`… sinon `unknown`), `active`, `autostart`, `method`, adresses v4 et v6, passerelle, `mtu` (68 à 65535), `bridge_ports`, `slaves`, `bond_mode`, `vlan_id`, `vlan_raw_device`, `comments`.
  **`has_gateway`** signale l'interface qui porte la passerelle par défaut : probablement le réseau d'administration, celle à ne jamais modifier à la légère.
- **Règles** : `pos`, `type` (`in`, `out`, `group`, `forward`), `action`, `enable`, `source`, `dest`, `proto`, `sport`, `dport`, `iface`, `macro`, `log`, `icmp_type`, `ipversion`, `comment`. Triées par position.
- **Options** : une liste blanche par niveau (datacenter, nœud, machine) ; le `digest` (40 caractères hexadécimaux) est repris pour les futures écritures, sinon `null`.
- Chaque partie du pare-feu porte **sa propre erreur** (`{"error": "…"}`) : un droit manquant sur les règles n'empêche pas de lire les options. Une erreur du réseau est traduite (502/504), sans message brut de Proxmox.
- Les modifications réseau en attente peuvent avoir été faites hors de Kaji : la page les affiche en évidence, avec le diff.
