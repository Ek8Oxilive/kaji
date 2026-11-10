# Tableau de bord : regroupement par stockage (M13, lot #252)

Liste déroulante « Regrouper par » du tableau de bord : nouvelle valeur **Regrouper par stockage** (mémorisée comme les autres). Lecture seule.

## `GET /api/connections/{conn_id}/guest-storages`
Aucune route de Proxmox ne donne « machine → stockages » : Kaji lit `/cluster/resources?type=storage`, puis les volumes (`GET /nodes/{node}/storage/{storage}/content`) de chaque stockage **actif** qui peut contenir des disques (`images` ou `rootdir`), et retient le `vmid` des volumes de ces deux types (une sauvegarde, une ISO ou un modèle ne comptent pas).

Réponse : `{by_vmid: {"102": ["local-lvm"], "103": ["fast", "local-lvm"]}, storages: [...], errors: n}`.

- Un stockage **partagé** n'est lu qu'une fois ; un stockage non partagé est lu sur chaque nœud où il est actif.
- **Au plus 40 stockages** lus par requête (le reste est compté dans `errors`).
- Un stockage illisible est compté dans `errors` sans faire échouer le reste ; l'interface prévient « n stockage(s) illisible(s) ».
- Lignes ou volumes de forme inattendue : ignorés. Aucun secret ne sort, aucune écriture.

Une machine dont les disques sont sur plusieurs stockages apparaît dans chacun de ses groupes (comme pour les étiquettes) ; sans disque identifié : « Sans disque identifié » en dernier.
