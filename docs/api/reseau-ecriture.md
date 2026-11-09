# Réseau d'un nœud en écriture (M7-4)

Bridges, bonds, VLAN et cartes Linux. Open vSwitch, fabrics, VNet et alias ne sont pas gérés (422). Préfixe : `/api/connections/{conn_id}/nodes/{node}/network`.

Chez Proxmox, créer, modifier ou supprimer une interface n'écrit que la configuration **en attente** (`/etc/network/interfaces.new`). Rien ne change tant qu'on n'**applique** pas, ce qui recharge le réseau du nœud, **sans retour arrière automatique**.

| Route | Rôle |
|---|---|
| `POST /interfaces` | Préparer une interface : `type` (`bridge`, `bond`, `vlan`), `iface` (`vmbr0-9999`, `bond0-9999`, `carte.ID` ou `vlanID`) |
| `PUT /interfaces/{iface}` | Modifier (`clear: [...]` retire des champs) |
| `DELETE /interfaces/{iface}` | Supprimer (refusé si l'interface sert de port, d'esclave ou de carte de VLAN à une autre) |
| `POST /apply` | Appliquer toutes les modifications en attente (renvoie la tâche Proxmox) |
| `POST /revert` | Annuler toutes les modifications en attente |

Champs : `cidr`, `gateway`, `cidr6`, `gateway6`, `mtu` (1280-65520), `comments`, `autostart`, `bridge_ports`, `bridge_vlan_aware`, `bridge_vids`, `slaves`, `bond_mode`, `bond_xmit_hash_policy`, `bond_primary`, `vlan_id`, `vlan_raw_device`. Booléens stricts, adresses et passerelles vérifiées (la passerelle doit être dans le réseau), ports et esclaves existants et libres, champs propres au type. Champs inconnus ignorés.

## Verrous (état relu chez Proxmox)
- **Préparer** : `confirm` suffit (inerte), SAUF si l'interface est celle d'**administration** (porte la passerelle par défaut, ou en dépend : ports, esclaves, carte de VLAN) ou si on pose une passerelle sur une autre interface alors qu'il y en a déjà une ⇒ `acknowledge_cut_access` + `type_name="COUPURE POSSIBLE"`.
- **Appliquer** : refusé s'il n'y a rien en attente (409) ; `acknowledge_live` toujours ; phrase `COUPURE POSSIBLE` en plus si le diff en attente nomme une interface d'administration ou retire une passerelle, un port, un esclave, un bridge ou un bond.
- **Annuler** : `confirm` (inerte).
- `dry_run` (corps, ou paramètre de requête pour `DELETE`) : verrous, paramètres et diff sans rien écrire. Après une préparation, Proxmox est relu (502 s'il n'a pas enregistré).

Audit : `net-create`, `net-update`, `net-delete`, `net-apply`, `net-revert` (succès, refus, erreurs).

## Non testé en réel
L'**application** (jamais exécutée sur le cluster réel : aucun banc d'essai), bonds, VLAN, suppression, détection des interfaces d'administration sur un vrai nœud multi-passerelles. Seuls des bridges sans port ni adresse, préparés puis annulés, sont essayés.
