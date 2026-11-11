# Onglet « Pare-feu » d'une machine (VM et LXC, M7, ticket #274)

Nouvel onglet **Pare-feu** de la page Machine (VM et conteneur), comme dans Proxmox. **Aucune route nouvelle** : l'onglet lit `GET /api/connections/{conn_id}/firewall/guests/{node}/{gtype}/{vmid}` (options et règles) et réutilise les fenêtres d'écriture de la page « Réseau », avec la machine préremplie :

| Bouton | Fenêtre | Routes d'écriture (`docs/api/pare-feu-*.md`) |
|---|---|---|
| Options… | options du pare-feu de la machine : politiques entrante et sortante, journalisation, DHCP, ipfilter, filtre MAC, NDP, radv | `PUT …/firewall/guests/{node}/{gtype}/{vmid}/options` |
| Règles… | liste, ajout, activation, déplacement, suppression des règles de la machine | `POST|PUT|DELETE …/firewall/guests/…/rules` |
| Alias et IPSets… | alias, IPSets et leurs entrées de la machine (pas de groupes de sécurité : ils n'existent qu'au datacenter) | `POST|PUT|DELETE …/firewall/guests/…/aliases` et `…/ipsets` |

Toutes les écritures gardent leurs verrous et leur aperçu `dry_run` (activation du pare-feu de la machine : `acknowledge_live` ; machine de `KAJI_PROTECTED_VMIDS` ou politique restrictive : phrase `COUPURE POSSIBLE`).

Le pare-feu d'une machine ne filtre que ses cartes réseau dont la case « firewall » est cochée (onglet Matériel) et seulement si le pare-feu du datacenter est activé : l'onglet le rappelle.

Frontend : `components/FirewallTab.tsx` ; `FwRulesDialog`, `FwOptionsDialog` et `FwObjectsDialog` acceptent une machine (`guest`) ; l'affichage des règles et des options est partagé (`components/FwViews.tsx`, utilisé aussi par la page « Réseau »).
