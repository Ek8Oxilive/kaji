# Étiquettes (tags) des machines (M13)

## Lecture
Chaque machine de `GET /api/connections/{id}/guests` (et du flux temps réel) porte `tags: string[]` : minuscules, triées, sans doublon, **seules les étiquettes valides** sont reprises (Proxmox les sépare par `;`, parfois `,` ou espace). Illisible ou absent : liste vide.

## Écriture
`PUT /api/connections/{id}/guests/{node}/{qemu|lxc}/{vmid}/tags` — `{ "tags": ["web", "prod"] }` → `{ "tags": [...] }`. Droit `VM.Config.Options`.
- Remplace **l'ensemble** des étiquettes ; une liste vide les retire toutes (`delete=tags`). **Rien d'autre** n'est envoyé à Proxmox (les champs inconnus du corps sont ignorés), testé.
- Étiquette valide : `[a-z0-9_][a-z0-9_\-+.]{0,31}` (mise en minuscules, dédoublonnée) ; 20 au plus ; sinon `422`. Le datacenter peut en plus restreindre la liste (`allowed-tags`) : Proxmox refuse alors, le message est relayé.
- Audité (`guest-tags`), sans confirmation (réversible, sans effet sur la machine).
