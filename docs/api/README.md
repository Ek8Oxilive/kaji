# Documentation d'API par fonction

Un fichier par fonction (`stockage.md`, `sauvegardes.md`…), avec le tableau de ses routes. Les routes historiques sont
encore dans le README à la racine ; **les nouvelles fonctions documentent ici**, pour que deux PR ne modifient jamais
le même fichier.

Format conseillé :

| Route | Rôle |
|---|---|
| `GET /api/connections/{id}/…` | Description courte, garde-fous (confirmation, droits Proxmox nécessaires) |
