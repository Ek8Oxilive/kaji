# Passthrough PCI, USB et répertoires d'une VM, par correspondance (M14, ticket #260)

Section « Périphériques PCI, USB et répertoires » de l'onglet **Matériel** d'une VM : ajouter, modifier, retirer un `hostpciN`, un `usbN` ou un `virtiofsN` **par une correspondance du datacenter** (voir `docs/api/correspondances.md`, `mapping=ID` / `dirid=ID`).

**Pourquoi seulement par correspondance** : Proxmox ne laisse un jeton non-root utiliser que des correspondances ; un périphérique « brut » (`host=0000:01:00.0`, `host=0bda:b00a`) est réservé à `root@pam`. Kaji **affiche** les périphériques bruts d'une VM (lecture seule, `raw: true`) mais ne les crée, modifie ni retire jamais (409).

Droits Proxmox : `VM.Config.HWType` sur la VM et `Mapping.Use` sur `/mapping/pci|usb|dir` (page « Accès » : `passthrough-write`).

| Route | Rôle |
|---|---|
| `GET /api/connections/{conn_id}/guests/{node}/qemu/{vmid}/passthrough` | `pci[]`, `usb[]`, `dir[]` (clé, correspondance, options lues, `raw`, `host`, `other`), `pending[]` (clés avec changement en attente), `machine`, `running` |
| `POST …/passthrough/{type}` | ajoute dans le **premier emplacement libre** (`pci` : hostpci0–15, `usb` : usb0–13, `dir` : virtiofs0–9) ; `201` |
| `PUT …/passthrough/{type}/{key}` | **remplace** le périphérique (ce qui n'est pas donné est retiré) |
| `DELETE …/passthrough/{type}/{key}?confirm=true` | retire de la configuration ; `dry_run=true` pour l'aperçu |

Corps (POST et PUT) : `mapping` (obligatoire) puis, selon le type, `pcie`, `rombar`, `x_vga`, `mdev` (pci) ; `usb3` (usb) ; `cache` (`always`, `auto`, `metadata`, `never`), `direct_io`, `expose_acl`, `expose_xattr` (dir) ; `dry_run`. Une option d'un autre type est refusée (422).

## Règles
- **Validation** : identifiant de correspondance et `mdev` par expression régulière (aucune virgule, aucun `host=` ne peut s'y glisser) ; valeur construite par Kaji : `mapping=ID` puis les options dans l'ordre canonique.
- **Contrôles côté serveur** : la correspondance existe (422 sinon) ; **déjà utilisée par un autre emplacement de cette VM : 409** ; `mdev` demande une correspondance marquée médiée (422) ; plus d'emplacement libre : 409 ; VM de `KAJI_PROTECTED_VMIDS` : 403 (lecture permise).
- **Avertissements** (aperçu et réponse, sans bloquer) : la correspondance n'a aucune entrée pour le nœud de la VM (elle ne pourra pas y démarrer) ; `pcie=1` sans machine `q35`.
- **Rien à chaud** : si la VM tourne, le changement reste « en attente » (`pending: true`, badge dans l'interface) jusqu'à son arrêt complet. La lecture se fait sur la configuration fusionnée avec ces changements.
- **Écriture** : `digest` de la configuration lue renvoyé à Proxmox (refus si elle a changé), relecture et comparaison après écriture (502 sinon).
- **Audit** : `passthrough-add|update|remove`, détail « hostpci0 : mapping=smbus » (identifiant de correspondance, pas de secret) ; refus audités.

## Tests
Faux Proxmox strict (`backend/tests/test_passthrough.py`) : format des propriétés, hôte brut refusé aux non-root (403), digest, configuration fusionnée ; 16 mutations tuées. Essais réels : voir `docs/REPRISE.md`.
