# Vues du tableau de bord (M13)

Pas de route nouvelle : `GET /api/connections/{id}/guests` (et le flux temps réel) porte maintenant, pour chaque machine, son **`pool`** de ressources (`null` si elle n'en a pas ; Proxmox n'envoie la clé que si la machine est dans un pool). Une valeur de forme inattendue (hors `[A-Za-z0-9_][A-Za-z0-9._-]{0,63}`) est écartée.

Côté interface, le tableau de bord filtre par **nœud, pool, étiquette, état, type** (les filtres pool et étiquette n'apparaissent que s'il en existe) et **regroupe** par nœud, pool, étiquette ou type. Le choix de regroupement est mémorisé dans le navigateur. Une machine à plusieurs étiquettes apparaît dans chacun de ses groupes ; les machines sans valeur sont rangées en dernier (« Sans pool », « Sans étiquette »).

**Vue par stockage** : non faite (Proxmox ne dit pas, dans la liste des machines, sur quels stockages reposent leurs disques ; il faudrait lire la configuration de chaque machine ou le contenu de chaque stockage).
