# Pare-feu : alias, IPSets et groupes de sécurité (écriture)

Deux niveaux, mêmes routes : datacenter `/api/connections/{id}/firewall/cluster/…` et machine `/api/connections/{id}/firewall/guests/{node}/{qemu|lxc}/{vmid}/…` (les groupes n'existent qu'au datacenter).
Écritures faites avec le token de Kaji (`Sys.Modify` sur `/`, ou `VM.Config.Network` sur la machine), pas avec la session administrateur : ce ne sont pas des droits d'accès.

| Route | Rôle |
|---|---|
| `POST …/aliases` `{name, cidr, comment?, confirm}` | crée un alias (IP ou réseau, IPv4 ou IPv6) |
| `PUT …/aliases/{name}` `{cidr, comment?, confirm, type_name, acknowledge_live?}` | modifie un alias ; le `digest` lu juste avant est transmis (refus si la configuration a changé) |
| `DELETE …/aliases/{name}?confirm=true&typed={name}` | supprime un alias |
| `POST …/ipsets` `{name, comment?, confirm}` | crée un IPSet vide |
| `DELETE …/ipsets/{name}?confirm=true&typed={name}&delete_members=` | supprime un IPSet (avec ses entrées si `delete_members=true`) |
| `POST …/ipsets/{name}/entries` `{cidr, comment?, nomatch?, confirm, acknowledge_live?}` | ajoute une entrée : IP, réseau ou alias |
| `DELETE …/ipsets/{name}/entries?cidr=&confirm=true&typed={cidr}&acknowledge_live=` | retire une entrée |
| `POST …/groups` `{name, comment?, confirm}` · `DELETE …/groups/{name}?confirm=true&typed={name}` | groupe de sécurité (18 caractères au plus ; supprimé seulement s'il est **vide et inutilisé**) |

## Verrous (décidés par le serveur sur l'état relu chez Proxmox)
- **Objet inerte** (non référencé, ou pare-feu de son niveau désactivé) : `confirm=true` suffit (création) ou `confirm` + nom retapé (modification, suppression).
- **Objet utilisé par une règle d'un pare-feu ACTIF** : refus **409** qui liste les règles concernées, tant que `acknowledge_live=true` n'est pas envoyé en plus. Les références cherchées : `name`, `dc/name`, `guest/name` (alias), `+name`, `+dc/name` (IPSet), règles de type `group`. Au datacenter, les règles du datacenter, des groupes et de **tous les nœuds** sont lues ; les règles des machines ne le sont pas toutes (Proxmox tranche).
- **`management` et `blacklist`** (ensembles intégrés que Proxmox utilise sans règle qui les nomme) : verrou **toujours** actif, même pare-feu éteint.
- **Supprimer** un alias, un IPSet ou un groupe **nommé par une règle** est refusé même avec `acknowledge_live` : on ne casse pas une règle (retire-le d'abord de la règle).
- **Un alias nommé par une entrée d'IPSet** (`alias`, `dc/alias`, `guest/alias`) est protégé de la même façon : suppression refusée (409), modification verrouillée si le pare-feu est actif. **Constaté en réel** : Proxmox laisse supprimer un tel alias et laisse une référence cassée dans l'IPSet ; Kaji le refuse. Limite : seuls les IPSets du même niveau sont lus (un IPSet de machine qui nomme `dc/alias` n'est pas détecté).
- IPSet non vide : suppression seulement avec `delete_members=true`.

## Validation
Noms : lettre puis lettres, chiffres, `-` `_` (groupes : 18 caractères au plus). Adresses : `ipaddress` fait foi (une plage `a-b`, un `/33`, un texte libre sont refusés ; une entrée d'IPSet peut être un alias). Commentaire d'une ligne de 100 caractères sans antislash.
Tout est refusé en 422 **avant** tout appel à Proxmox. Proxmox est relu après chaque écriture (502 s'il n'a pas appliqué). Audit `fw-alias-*`, `fw-ipset-*`, `fw-ipset-entry-*`, `fw-group-*` (succès, refus, erreur).
