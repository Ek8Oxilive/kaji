# M7 : réseau et pare-feu, cadrage de l'écriture

**Statut : lecture livrée (M7-1), écriture non commencée.** Ce document dit comment écrire sans pouvoir couper l'accès, et ce qu'il faut décider avant.

## 1. Pourquoi c'est le jalon le plus risqué
Une règle de pare-feu ou une modification de bridge fausse peut **couper l'accès à Proxmox, à Kaji et aux machines**, sans retour possible depuis Kaji (s'il ne joint plus le nœud,
il ne peut rien annuler). Proxmox n'offre pas de retour arrière automatique après `ifreload`. Le projet l'a déjà acté : « réseau et pare-feu ne se testent **pas** sur le cluster réel »
(`docs/parite-proxmox.md`, prérequis du banc d'essai).

## 2. Faits vérifiés (cluster réel, lecture seule, 2026-11-08)
- Réseau du nœud `enzo` : un bridge `vmbr0` (192.168.1.200/24, passerelle 192.168.1.1) sur `nic0`, VLAN aware. Pas de bond. Aucune modification en attente.
- **Pare-feu non configuré nulle part** : options, règles, alias, IPSets, groupes vides au datacenter, sur le nœud et sur la VM 115.
- Kaji (CT 116) joint Proxmox sur ce même réseau : toucher à `vmbr0` ou filtrer 8006 couperait Kaji lui-même.

## 3. Garde-fous proposés pour toute écriture (à figer avant le code)
1. **Interdits absolus côté serveur** : l'interface qui porte la passerelle par défaut (`has_gateway`) et ses ports, les ports 8006, 22 et 3128 en `DROP`/`REJECT` entrant sans règle `ACCEPT` plus précise, activer le pare-feu du datacenter sans règle d'accès à l'administration.
2. **Aperçu avant application** : le diff de Proxmox (`changes`) est montré tel quel ; `confirm=true` et le nom du nœud ou du niveau retapé.
3. **Écriture en deux temps** pour le réseau : on écrit dans la configuration **en attente**, on montre le diff, on peut **annuler** (`DELETE /nodes/{node}/network`) ; l'application (`PUT`) est un geste séparé.
4. **Activation progressive du pare-feu** : règles écrites d'abord pare-feu **désactivé**, puis activation d'un **niveau à la fois** (machine, puis nœud, puis datacenter), jamais d'un coup.
5. **Une écriture à la fois** ; audit de chaque écriture, refus et erreur ; `digest` pour ne pas écraser un changement concurrent.
6. **Aucun essai réel sur le cluster** de production, hors lecture : validation **uniquement** sur le banc d'essai imbriqué.

## 4. Banc d'essai imbriqué : où on en est
Il faut 2 à 3 VM Proxmox sur un réseau isolé (environ 8 à 12 Go de RAM et 100 Go de disque). **Le cluster n'a pas cette marge** : `enzo` utilise 10 Go sur 15,5 Go et `enzo2` 6 Go sur 7,6 Go. Options : (a) un seul nœud imbriqué de 4 Go (réseau et pare-feu suffisent), en éteignant une machine peu utile le temps des essais, (b) une machine hors cluster. **Décision d'Enzo attendue.**

## 5. Découpage
| Lot | Contenu | Qui | Risque |
|---|---|---|---|
| **M7-1** | Lecture du réseau, des modifications en attente et du pare-feu (livré) | PC A | Nul |
| M7-2 | Pare-feu : alias, IPSets, groupes (sans effet tant que le pare-feu est désactivé) | PC B (faux Proxmox), essais réels sur le banc | Faible |
| M7-3 | Pare-feu : options et règles, avec les interdits du §3 | PC B, essais sur le banc | Élevé |
| M7-4 | Réseau : bridges, bonds, VLAN en attente, aperçu, annulation, application | PC A, banc obligatoire | Très élevé |
| M7-5 | SDN (zones, VNets, sous-réseaux) | PC A/B, banc | Élevé |

## 6. Décisions à prendre
1. **Banc d'essai** : option (a) ou (b) du §4, ou on s'en tient à la lecture ?
2. Les garde-fous du §3 te conviennent-ils (en particulier l'interdiction de toucher à l'interface d'administration) ?
3. Ordre : M7-2 avant M7-3 avant M7-4 ?
