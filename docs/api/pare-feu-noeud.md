# Section « Pare-feu » de la page d'un nœud

Frontend seul, **aucune route nouvelle** : la section lit `GET /api/connections/{id}/firewall/nodes/{node}` (options et règles du nœud) et ses deux boutons ouvrent les fenêtres existantes de la page « Réseau », déjà réglées sur le nœud :

| Bouton | Fenêtre | Écriture |
|---|---|---|
| Options… | `FwOptionsDialog` (niveau « Nœud ») | `PUT /firewall/nodes/{node}/options` (voir `pare-feu-options.md`) |
| Règles… | `FwRulesDialog` (portée « Nœud ») | règles du nœud (voir `pare-feu-regles.md`) |

Les verrous sont ceux du serveur : activer le pare-feu d'un nœud exige le déverrouillage « coupure possible » (case + phrase `COUPURE POSSIBLE`), chaque action passe par un aperçu `dry_run`. Les alias, IPSets et groupes ne se règlent qu'au datacenter ou sur une machine (pas de niveau « nœud » dans Proxmox).
