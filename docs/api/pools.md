# Pools de ressources (lot #298)

> **Non validé en réel au moment du code** (faux Proxmox strict, schéma officiel de Proxmox 9). Fichiers : `routers/pools.py`, `poolspec.py`, `tests/test_pools.py`,
> `components/PoolsSection.tsx` (section « Pools de ressources » de la page Datacenter), `lib/types/pools.ts`. La liste simple `GET /pools` existe depuis M4 (`routers/create.py`).

Préfixe `/api/connections/{id}/pools`. Équivalent de Datacenter → Permissions → Pools. Droits Proxmox : `Pool.Allocate` sur `/pool/{poolid}` ; Proxmox exige **aussi le droit
de modifier les permissions** sur ce qu'on ajoute ou retire d'un pool (à vérifier en réel avec le token de Kaji).

| Route | Rôle | Appel Proxmox |
|---|---|---|
| `GET /overview` | tous les pools avec leurs membres | `GET /pools` |
| `GET /{poolid}` | un pool (404 s'il n'existe pas) | `GET /pools` |
| `POST /` `{poolid, comment?}` | crée un pool (201 ; 409 s'il existe) | `POST /pools` |
| `PUT /{poolid}` | commentaire, ajouter / retirer des machines et des stockages ; `{comment?, add_vms[], remove_vms[], add_storage[], remove_storage[], allow_move, confirm, dry_run}` | `PUT /pools` (ajouts d'abord, retraits ensuite : `delete=1`) |
| `DELETE /{poolid}?confirm=true&name={poolid}` | supprime un pool **vide et sans droit** | `DELETE /pools?poolid=…` |

Audit : `pool-create`, `pool-update`, `pool-delete` (succès, refus, erreurs ; jamais de secret).

## Validation (liste blanche, `fullmatch`, champs inconnus ignorés)
- `poolid` : `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$` (pas de pool imbriqué), aussi dans le chemin. `comment` : 200 caractères au plus, sans caractère de contrôle.
- Machines : entiers **stricts** de 100 à 999 999 999, sans doublon, 50 au plus. Stockages : identifiants Proxmox valides, sans doublon, 20 au plus.
- Un même élément ne peut pas être ajouté **et** retiré dans la même demande (422) ; demande sans aucune modification : 400.

## Garde-fous (tout est relu chez Proxmox AVANT d'écrire ; un refus n'écrit rien)
- Pool inconnu : 404. Élément à retirer absent du pool, ou à ajouter déjà présent : 409. Machine ou stockage à ajouter introuvable : 404.
- **Une machine de `KAJI_PROTECTED_VMIDS` n'est jamais ajoutée, retirée ni déplacée** (409, même confirmé).
- Une machine qui est **déjà dans un autre pool** n'est déplacée qu'avec `allow_move=true` (409 sinon), et seulement avec `confirm=true` (elle sort de son pool : ses droits changent).
- **Retirer** un membre exige `confirm=true` (400 sinon) : retirer une machine d'un pool peut retirer les droits d'accès accordés par ce pool (c'est le cas de `kaji-test` pour Kaji).
- `dry_run=true` : renvoie les appels prévus (`calls`) et les raisons de confirmation, **sans rien écrire**.
- **Suppression** : `confirm=true` ET l'identifiant retapé (`name`, casse et espaces compris) ; refusée tant que le pool contient un membre (409) et tant qu'une entrée d'**ACL** existe sur
  `/pool/{poolid}` (409 : sa suppression ferait disparaître des accès) ; ACL illisibles : 502, rien n'est supprimé.
- Si le retrait échoue après les ajouts (deux appels Proxmox), la réponse est une erreur 502 ; relire le pool montre ce qui a été fait.
- Erreurs Proxmox traduites en 502 sans fuite.

## Interface
Section « Pools de ressources » de la page Datacenter : tableau (pool, commentaire, nombre de machines et de stockages), « Créer un pool », « Gérer » (commentaire, cocher les membres à
retirer, ajouter des machines et des stockages, case « déplacer » quand une machine est déjà dans un autre pool, confirmation affichée avant un retrait), « Supprimer » (identifiant à retaper).

## Constaté en réel (2026-11-12, Proxmox 9.1.9)
- **`GET /pools` sans `poolid` ne renvoie pas les membres** (seulement `poolid` et `comment`) ; il faut `GET /pools?poolid=…` pour chaque pool. Kaji lit donc le détail de chaque pool (100 au plus),
  pour ses pré-contrôles (déjà membre, retrait d'un non-membre, pool vide à la suppression). Premier jet du lot : membres toujours vides, corrigé le jour même (PR de suivi).
- Créer un pool et ajouter une VM / un stockage : acceptés par Proxmox avec le token de Kaji (`PUT /pools` 200 ; la VM apparaît dans le pool dans la liste des machines).

## Non validé en réel
- l'acceptation de chaque appel (`POST`, `PUT` avec `vms` / `storage` / `delete` / `allow-move`, `DELETE ?poolid=`) par le token de Kaji, et le droit « modifier les permissions » exigé pour ajouter ou retirer ;
- la forme réelle des membres dans `GET /pools` (le schéma officiel est suivi) ;
- l'interface n'a pas été ouverte dans un navigateur au moment du code.
