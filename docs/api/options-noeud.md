# Options d'un nœud (M11, lot #403)

Préfixe `/api/connections/{conn_id}/nodes/{node}/options`. Équivalent de Nœud → Système → Options (réveil à distance, délai de démarrage, ballooning). Bouton **« Options du nœud… »** du bloc « Configuration du nœud » de la page Nœud.
Schéma lu sur `apidoc.js` de Proxmox 9 : `GET` (droit `Sys.Audit`) et `PUT /nodes/{node}/config` (droit `Sys.Modify` sur `/`), `allowtoken: 1`. Validation : `backend/app/nodeoptspec.py`.

| Route | Droit | Effet |
|---|---|---|
| `GET /` | Kaji | `wakeonlan` (`mac`, `bind_interface`, `broadcast_address`), `wakeonlan_readable`, `startall_onboot_delay`, `ballooning_target`, `digest`, `empty` |
| `PUT /` | Kaji (`Sys.Modify`) | Modifie ou retire ces options |

## Écriture
- Champs : `wakeonlan_mac` (`aa:bb:cc:dd:ee:ff`), `wakeonlan_bind_interface`, `wakeonlan_broadcast_address` (IPv4 strict), `startall_onboot_delay` (0 à 300), `ballooning_target` (0 à 100), `clear` (`wakeonlan`, `startall-onboot-delay`, `ballooning-target`).
- **Seules les options demandées partent chez Proxmox.** Une demande de `wakeonlan` partielle est **fusionnée** avec la valeur actuelle (la MAC est obligatoire au final). Une option à la fois modifiée et retirée, ou retirée deux fois : 422. Champs inconnus ignorés, jamais transmis.
- `digest` lu juste avant : exigé (400 s'il manque, 409 s'il est périmé). Seule une configuration **vide** (Proxmox ne renvoie alors pas de digest) s'écrit sans.
- `confirm=true` exigé ; `dry_run` renvoie les paramètres sans rien écrire. Relecture après l'écriture, chaque changement vérifié (502 sinon). Audit `node-options` : noms des options seulement, jamais les valeurs.
- **Jamais touchés** : les notes (`description`, voir `docs/api/notes.md`) et l'ACME (`docs/api/acme.md`) de la même configuration. Un `wakeonlan` illisible par Kaji (clé inconnue…) fait **refuser** sa réécriture, les autres options restent modifiables.

## Validation
Faux Proxmox strict (`backend/tests/test_node_options.py` : clés, formats `wakeonlan`, bornes, digest, relecture de chaque option), 44 tests, 20 mutations tuées.
**Essai réel** : voir `docs/REPRISE.md` (ligne « Options du nœud »).
