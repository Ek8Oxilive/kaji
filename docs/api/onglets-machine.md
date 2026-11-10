# Onglets « Réplication » et « Permissions » de la page Machine (M8 / M6, lot #226)

**Aucune route nouvelle** : ces deux onglets réutilisent l'API existante. Rien de plus n'est écrit chez Proxmox que ce que les pages « HA » et « Accès » savent déjà faire, avec les mêmes verrous.

## Réplication (VM et conteneur)
- Lit `GET …/replication` et ne garde que les jobs dont `guest` = l'identifiant de la machine ; état (dernière et prochaine synchro, échecs) lu sur le nœud **source** de chaque job (`GET …/nodes/{node}/replication`).
- Boutons : **Nouveau job…**, **Modifier**, **Lancer maintenant**, **Supprimer** : ce sont les fenêtres de la page « HA » (`ReplDialog`), avec la machine préremplie. Aperçu `dry_run` obligatoire avant d'appliquer, bloqueurs annoncés (par exemple « aucun stockage ZFS »), nom du job à retaper pour supprimer sans conserver les copies. Voir `docs/api/replication-ecriture.md`.
- Droit : `VM.Replicate` (page « Accès » : `replication-write`).

## Permissions (VM et conteneur)
- Lit `GET …/access/acl` et affiche les entrées qui s'appliquent à la machine : sur `/vms/<id>`, et celles **héritées** (propagation) de `/vms` et de `/`. Une entrée sur un pool contenant la machine n'est pas affichée (Kaji ne connaît pas l'appartenance aux pools ici).
- Proxmox ne montre au token de Kaji que les entrées qui le concernent : la liste peut être incomplète (voir `docs/api/acces.md`).
- **Modifier une ACL…** ouvre la fenêtre de la page « Accès » avec le chemin `/vms/<id>` prérempli : même session administrateur, mêmes interdits (jamais de rôle qui modifie les droits), identifiant retapé. Voir `docs/api/acl-ecriture.md`.

## Pas testé en réel
Réplication : jamais écrite (pas de ZFS sur le cluster) ; seuls l'affichage et l'aperçu `dry_run` se vérifient. Permissions : écriture jamais essayée (aucun token d'administration).
