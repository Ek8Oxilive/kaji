# Accès : droits de Kaji, utilisateurs, rôles, ACL (lecture seule)

Routes sous `/api/connections/{id}/access`. **Aucune écriture** : Kaji ne crée ni ne modifie aucun utilisateur, rôle ou droit.
Toutes exigent d'être connecté. Tout ce que Proxmox ne renvoie pas (ou renvoie illisible) est ignoré ou donne `null` ; une
ligne illisible n'empêche pas de lister les autres.

| Route | Réponse |
|---|---|
| `GET …/access/features` | « Droits de Kaji » : une entrée par fonction (voir plus bas) |
| `GET …/access/users` | `[{userid, realm, realm_type, enabled, expire}]`, triés par `userid`. `expire` : secondes depuis 1970, `null` si le compte n'expire pas |
| `GET …/access/groups` | `[{groupid, comment, users: [...]}]` |
| `GET …/access/roles` | `[{roleid, special, privs: [...]}]` (privilèges triés) |
| `GET …/access/acl` | `[{path, type, ugid, roleid, propagate}]` |
| `GET …/access/realms` | `[{realm, type, comment}]` |

**Ce que le token voit.** Proxmox ne montre que ce que le token a le droit de voir : `acl` ne liste que les entrées qui le
concernent, `users` seulement les comptes visibles, et la liste des tokens d'un utilisateur (`/access/users/{id}/token`) est
refusée au token de Kaji (403, normal) : elle n'est donc pas exposée ici.

## Droits de Kaji (`features`)

Pour chaque fonction de Kaji, la réponse dit si le token possède les privilèges nécessaires :

```json
{"id": "backup-jobs", "label": "Gérer les sauvegardes planifiées", "status": "missing",
 "missing": [{"path": "/", "privilege": "Sys.Modify"}]}
```

| `status` | Sens |
|---|---|
| `ok` | Tous les privilèges nécessaires sont accordés (Proxmox a répondu pour chaque chemin) |
| `missing` | Au moins un privilège manque ; `missing` le nomme avec son chemin |
| `unknown` | Un chemin n'a pas pu être lu et rien ne prouve un manque. **Jamais `ok` sans preuve** |

- Les droits sont ceux que **Proxmox calcule** pour le token (`GET /access/permissions?path=…`), héritage compris. Kaji ne
  refait aucun calcul d'héritage. Rappel : une entrée posée sur un chemin précis **remplace** celle héritée du parent pour le
  même utilisateur, elle ne s'y ajoute pas.
- Seule la valeur `1` compte comme accordé ; `true`, `"1"`, `0`, `null`… ne comptent pas.
- Les chemins interrogés sont des **constantes** (`/`, `/vms`, `/storage`, `/pool`, `/sdn/zones`) : aucune saisie n'entre
  dans l'appel à Proxmox.
- Si Proxmox ne répond à **aucune** question, l'erreur (502 ou 504) est renvoyée telle quelle, pas un faux « inconnu ».
- **Indicatif.** La liste des privilèges par fonction (`accessspec.py`, `FEATURES`) vient de la documentation de Proxmox ; pour
  les jobs de sauvegarde (`Sys.Modify` sur `/`), elle a été constatée en réel. Un cas particulier peut demander d'autres
  privilèges. `ok` veut dire « les privilèges attendus sont là », pas « l'opération réussira toujours ».

Fonctions couvertes : voir le cluster, voir les stockages, voir les pools, démarrer/éteindre, créer/supprimer une machine,
modifier le matériel, snapshots, cloner, migrer, lancer une sauvegarde, restaurer une sauvegarde, gérer les sauvegardes
planifiées, ajouter une carte réseau.

## Validé en réel, et ce qui ne l'a pas été

Validé sur un vrai cluster (lecture seule) : les cinq listes (utilisateurs, groupes, rôles, ACL, realms) répondent et
sont mises en forme ; `features` répond « ok » partout avec les droits accordés ; `GET /access/permissions` filtré par
`path` ne renvoie que ce chemin, et **un privilège non accordé est absent de la réponse** (ce qui justifie la règle stricte).

**Non validé en réel**
- Le statut **`missing`** n'a été vu que sur le faux Proxmox : tous les droits étant accordés au token de test, aucune
  fonction n'est manquante en réel. (Le comportement sous-jacent, un privilège absent de la réponse, l'a été.)
- La liste des privilèges par fonction est celle de la documentation : elle n'a pas été éprouvée en retirant chaque droit.
- Le cas d'un **token avec séparation de privilèges** (`privsep=1`), dont les droits sont plus petits que ceux de
  l'utilisateur : le token de test n'en a pas.
