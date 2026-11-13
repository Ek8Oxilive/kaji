# Migration distante vers un autre cluster (M14, lot #390)

`POST /api/connections/{conn_id}/guests/{node}/{qemu|lxc}/{vmid}/remote-migrate`. Bouton **« Autre cluster… »** de la ligne « Nœud » de l'onglet Matériel d'une machine, à côté de « Migrer » (migration entre nœuds du MÊME cluster).
Schéma lu sur `apidoc.js` de Proxmox 9 (`POST /nodes/{node}/{qemu|lxc}/{vmid}/remote_migrate`, droit `VM.Migrate` sur `/vms/{vmid}`). **Fonction « EXPERIMENTAL » chez Proxmox. Jamais essayée en réel : il n'y a qu'un cluster.**
Validation et secrets : `backend/app/remotemigrate.py`.

## Corps
| Champ | Règle |
|---|---|
| `target_host` | nom ou IP d'un nœud du cluster distant ; boucle locale, adresse non spécifiée, liaison locale, multicast, `localhost` refusés |
| `target_port` | entier 1 à 65535 (facultatif ; 8006 par défaut chez Proxmox) |
| `target_token_id` | jeton d'API du cluster distant : `utilisateur@realm!nom` |
| `target_secret` | **secret du jeton**, un UUID ; `SecretStr`, écriture seule |
| `target_fingerprint` | **empreinte SHA-256 du certificat distant, OBLIGATOIRE** (32 octets hexadécimaux séparés par `:`), mise en majuscules. Proxmox la laisse facultative : Kaji ne se connecte **jamais** sans la vérifier |
| `target_storage`, `target_bridge` | obligatoires ; `1` (chaque source vers elle-même), un identifiant (tout vers lui) ou `source:cible,source:cible` (20 paires au plus) ; chaque identifiant validé |
| `target_vmid` | 100 à 999 999 999 (facultatif) |
| `online` | VM en marche : obligatoire ; conteneur : migration à chaud (expérimentale) |
| `restart`, `timeout` | conteneurs seulement (422 pour une VM) ; un conteneur en marche exige `restart` ou `online` |
| `bwlimit` | Kio/s, entier ≥ 0 |
| `delete` | **supprime l'ORIGINAL après réussite** (par défaut, il est gardé arrêté) |
| `confirm`, `type_name`, `acknowledge_cut_access`, `phrase`, `dry_run` | verrous ci-dessous |

Envoyé à Proxmox : `target-endpoint=apitoken=PVEAPIToken=user@realm!nom=SECRET,host=HÔTE,fingerprint=EMPREINTE[,port=PORT]` (format du schéma), `target-storage`, `target-bridge`, et seulement les options données.

## Verrous (décidés par le serveur)
- **Machines protégées** (`KAJI_PROTECTED_VMIDS`, dont le CT de Kaji) : refusées (409), aperçu compris.
- `confirm=true` obligatoire (400 sinon), sauf pour `dry_run`.
- **`delete=true`** : en plus le **nom exact de la machine retapé** (`type_name`, 400 sinon ; l'identifiant si la machine n'a pas de nom) et `acknowledge_cut_access=true` + `phrase="COUPURE POSSIBLE"` (409 sinon) : si la migration échoue ou si la copie est incomplète, les données sont perdues.
- Une VM en marche exige `online=true` ; un conteneur en marche `restart=true` ou `online=true` (422).
- **`dry_run=true`** : renvoie la cible (hôte, port, nom du jeton, empreinte), les paramètres avec `target-endpoint` **masqué**, l'état de la machine et les verrous ; **n'appelle jamais `remote_migrate`**.

## Secrets
Le secret du jeton distant n'est jamais renvoyé, journalisé ni mis dans une erreur. **Les erreurs de Proxmox sont nettoyées** : Proxmox écrit son message dans la ligne d'état HTTP et peut y recopier le paramètre fautif (donc le jeton) ; Kaji retire le secret et, si la chaîne de connexion apparaît, remplace tout le message par un texte fixe. L'audit (`remote-migrate`) ne garde que l'hôte, le port, le début de l'empreinte, les correspondances, l'identifiant cible et les options.

## Validation
Faux Proxmox strict (`backend/tests/test_remote_migrate.py` : clés autorisées par type, `target-endpoint` au format du schéma, correspondances validées, erreur qui recopie le jeton). **Jamais écrit en réel.**
**Hypothèses non vérifiées** : le format exact de `target-endpoint` accepté par Proxmox 9.1 (lu dans le schéma, jamais envoyé), que Proxmox accepte `delete` ou `bwlimit` pour un conteneur, ce que Proxmox renvoie quand l'empreinte ne correspond pas.
