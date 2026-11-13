# Journal du cluster (M13, lot #401)

`GET /api/connections/{conn_id}/cluster/log?max=100` : équivalent de Datacenter → Journal du cluster (bas de l'interface de Proxmox). **Lecture seule**, droit de Kaji (session Kaji).
Schéma lu sur `apidoc.js` de Proxmox 9 : `GET /cluster/log`, `allowtoken: 1`, seul paramètre `max` (entier ≥ 1). Proxmox exige `Sys.Syslog` sur `/` pour tout voir (sinon il filtre).

- `max` : 1 à 500 (100 par défaut), 422 sinon.
- Réponse : `{ entries: [{ time, pri, tag, node, user, pid, msg }] }`, plus récentes d'abord. `pri` = gravité syslog de 0 (urgence) à 7 (debug), 6 si illisible.
- Tout ce qui vient de Proxmox est traité comme non fiable (`app/clusterlogspec.py`) : entrées non conformes ignorées, types vérifiés, caractères de contrôle remplacés par des espaces, longueurs bornées (message 500, service 40, nœud 64, utilisateur 80), 500 entrées au plus.
- Interface : section « Journal du cluster » en bas de la page « Tâches » (filtres gravité, nœud, texte ; 100 / 200 / 500 entrées ; rafraîchie toutes les 30 s).

## Validation
Faux Proxmox strict (`backend/tests/test_cluster_log.py` : seul `max` accepté, tri, caractères de contrôle, entrées hostiles, erreur sans fuite, 401 sans connexion), 6 mutations tuées.
**Format réel** : lu d'après la documentation de Proxmox (`uid`, `time`, `pri`, `tag`, `pid`, `node`, `user`, `msg`) ; vérifié en réel après déploiement (voir `docs/REPRISE.md`).
