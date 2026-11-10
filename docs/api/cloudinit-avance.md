# Cloud-init avancé : snippets `cicustom` (VM, M14, ticket #238)

Onglet **Cloud-init** de la page Machine (VM avec lecteur cloud-init) : section « Snippets personnalisés (avancé) ».

`cicustom` dit à Proxmox de prendre un fichier cloud-init **existant** à la place de celui qu'il génère, pour quatre parties : `user`, `network`, `meta`, `vendor`. Format Proxmox : `user=local:snippets/ci-user.yaml,network=…`.

**Les snippets ne se téléversent pas par l'API Proxmox** (l'upload n'accepte que `iso`, `vztmpl`, `import`) : on les dépose à la main dans un stockage qui accepte le contenu `snippets` ; Kaji ne crée ni ne modifie aucun fichier.

| Route | Rôle |
|---|---|
| `GET /api/connections/{conn_id}/guests/{node}/qemu/{vmid}/cloudinit` | comme avant, plus `custom` : `{user, network, meta, vendor}`, chacun `stockage:snippets/fichier` ou `null` |
| `GET …/cloudinit/snippets` | snippets du nœud : `{snippets[{volid, storage, name, size}], errors[]}` (lecture seule) |
| `PATCH …/cloudinit` | champ `custom` : `{partie: "stockage:snippets/fichier" \| null}` ; `null` ou chaîne vide retire la partie |

## Règles
- **Valeur validée** : `^stockage:snippets/fichier$` (nom de fichier sans `/`, sans `..`, sans virgule ni espace, 200 caractères au plus). Une autre partie que les quatre connues est refusée (422). Les erreurs de validation ne renvoient pas la valeur.
- **Le snippet doit exister** : avant l'écriture, Kaji relit la liste des snippets du nœud (stockages qui acceptent `snippets`, actifs) ; un volume absent est refusé en **422 sans appel d'écriture** (« les snippets se déposent à la main »).
- **Réécriture complète** : Kaji relit `cicustom` actuel, applique les changements, et réécrit la valeur entière dans l'ordre `user, network, meta, vendor` ; plus aucune partie = `delete=cicustom`. Les parties inconnues ou mal formées d'une valeur relue sont ignorées.
- **`digest`** : le `digest` de la configuration lue est renvoyé à Proxmox, qui refuse (502) si la configuration a changé entre-temps.
- Rien à changer = 200 `{changed: [], cleared: []}` sans écriture. Combinable avec les autres réglages cloud-init dans le même `PATCH` (une seule écriture).
- **Audit** : action `cloudinit-update`, détail « snippets user=défini, network=retiré » (les noms de fichiers ne sont pas recopiés) ; refus audités.
- Un stockage illisible (hors ligne) est signalé dans `errors`, il ne bloque pas les autres.

## Tests
Faux Proxmox strict (`backend/tests/test_cloudinit_custom.py`) : digest vérifié, format et volumes vérifiés, 400 sinon ; 10 mutations tuées. Essais réels : voir `docs/REPRISE.md`.
