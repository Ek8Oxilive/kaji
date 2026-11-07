# Notes des machines et des nœuds (M13)

Les notes sont le champ `description` de la configuration d'une machine ou d'un nœud. Le texte est affiché **tel quel** par l'interface (jamais interprété comme du HTML ; le balisage Markdown de Proxmox n'est pas rendu).

| Route | Droit | Rôle |
|---|---|---|
| `GET /api/connections/{id}/guests/{node}/{qemu|lxc}/{vmid}/notes` | `VM.Audit` | `{notes, digest, empty}` |
| `PUT` la même | `VM.Config.Options` | remplace les notes |
| `GET /api/connections/{id}/nodes/{node}/notes` | `Sys.Audit` | `{notes, digest, empty}` |
| `PUT` la même | `Sys.Modify` | remplace les notes |

Corps de `PUT` : `{ "notes": "…", "digest": "<lu juste avant>" }`. Garde-fous, audités (`guest-notes`, `node-notes`) **sans jamais écrire le texte dans l'audit** (seulement sa longueur) :
- 8192 caractères au plus, pas d'octet nul, retours chariot normalisés ;
- **`digest` obligatoire** (40 hexadécimaux) : s'il a changé entre-temps, `409` et rien n'est écrit ; configuration illisible : `502` ;
- **cas des nœuds sans réglage** : leur configuration est **vide** (`{}`) et Proxmox ne renvoie alors aucun `digest` (constaté sur `enzo` et `enzo2`). `empty: true` autorise l'écriture sans digest, et seulement dans ce cas ; un texte vide sur une configuration vide n'écrit rien ;
- notes vides sinon : l'option `description` est supprimée ; **rien d'autre** n'est jamais envoyé à Proxmox (schéma vérifié par le faux Proxmox : `description` / `delete`, plus `digest`).
