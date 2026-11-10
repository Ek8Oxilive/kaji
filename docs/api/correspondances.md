# Correspondances de ressources du datacenter : PCI, USB, répertoires (M14, ticket #248)

Section « Correspondances de ressources » de la page Datacenter (Datacenter → Resource Mappings de Proxmox). Une correspondance donne un **nom logique** à un périphérique PCI, un périphérique USB ou un répertoire, avec une **entrée par nœud** : une VM peut ensuite l'utiliser quel que soit le nœud où elle tourne. **Utiliser** une correspondance dans une VM (`hostpciN`, `usbN`, `virtiofsN`) n'est **pas** encore proposé (ligne « Matériel avancé » de `docs/parite-proxmox.md`).

Droits Proxmox : `Mapping.Audit` / `Mapping.Modify` sur `/mapping/pci`, `/mapping/usb`, `/mapping/dir` ; le matériel d'un nœud demande `Sys.Audit` (page « Accès » : `mappings-read`, `mappings-write`).

| Route | Rôle |
|---|---|
| `GET /api/connections/{conn_id}/mappings/{type}` | liste (`type` = `pci`, `usb`, `dir`) : `id`, `description`, `map[]` (entrées lues), `checks[]`, `error`, `mdev`, `live_migration_capable` ; `?check_node=NŒUD` ajoute les vérifications de ce nœud |
| `GET …/mappings/{type}/{id}` | détail avec `digest` (empreinte de Kaji) |
| `POST …/mappings/{type}` | crée : `id`, `description?`, `map[]`, `mdev?`, `live_migration_capable?` (pci seulement), `dry_run?` |
| `PUT …/mappings/{type}/{id}` | modifie : `description`, `map` (remplace toutes les entrées), `mdev`, `live_migration_capable`, `clear[]` (`description`, `mdev`, `live-migration-capable`), `digest`, `dry_run` |
| `DELETE …/mappings/{type}/{id}` | supprime : `confirm=true` ET `type_name` = identifiant ; `dry_run=true` renvoie `used_by[]` |
| `GET /api/connections/{conn_id}/nodes/{node}/hardware/{pci\|usb}` | matériel détecté, avec les valeurs prêtes pour une entrée (`map_id` = vendeur:périphérique, `subsystem_id`, `map_path` = bus-port USB) |

## Entrées (`map[]`), formats lus sur le vrai Proxmox 9 (`apidoc.js`, 2026-11-10)
| Type | Propriétés | Obligatoires |
|---|---|---|
| `pci` | `node`, `path` (adresses `0000:00:04.0`, plusieurs séparées par `;`), `id` (`8086:1903`), `iommugroup`, `subsystem-id`, `description` | `node`, `path`, `id` |
| `usb` | `node`, `id` (`0bda:b00a`), `path` (bus-port, `1-13`), `description` | `node`, `id` |
| `dir` | `node`, `path` (absolu, sans `..`) | `node`, `path` |

Une propriété d'un autre type est refusée (422). Les identifiants hexadécimaux sont mis en minuscules. Une description d'entrée n'a ni virgule, ni égal, ni guillemet (elle voyage dans une chaîne `clé=valeur,…`). Deux entrées identiques : 422. 32 entrées au plus.

## Règles
- **Validation avant Proxmox** : rien n'est transmis tel quel ; `map` part comme paramètre répété, une chaîne par entrée.
- **Relecture** : après chaque création ou modification, Kaji relit la correspondance et compare les entrées ; sinon 502 (« Proxmox n'a pas appliqué… »).
- **Modification** : `digest` de Kaji (409 si périmé) ; le `digest` de Proxmox, s'il existe, lui est renvoyé ; sans `map` dans la requête, les entrées actuelles sont renvoyées telles quelles (Proxmox exige `map` au `PUT` d'une correspondance USB).
- **Suppression** : refusée (409) tant qu'une VM la cite (`hostpciN` / `usbN` : `mapping=ID` ; `virtiofsN` : `dirid=ID`) ; refusée aussi si une configuration de VM est illisible ou s'il y a plus de 64 VM (on ne devine pas). Les conteneurs LXC ne peuvent pas citer de correspondance.
- **Audit** : `mapping-create`, `mapping-update`, `mapping-delete` ; le détail donne les noms des propriétés (« map=2 entrée(s) »), jamais les descriptions ni les chemins ; refus audités.
- Le **chemin USB** (`bus-port`) est construit depuis `busnum` et `port` du matériel détecté (absent pour un contrôleur racine) : **pas encore vérifié sur une entrée réellement utilisée par une VM**.

## Tests
Faux Proxmox strict (`backend/tests/test_mappings.py`) : formats, paramètres autorisés par type, `digest`, `map` obligatoire au `PUT` USB ; 17 mutations tuées. Essais réels : voir `docs/REPRISE.md`.
