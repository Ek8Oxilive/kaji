# Dépôt apt personnalisé (commandes à copier)

**Kaji n'écrit rien chez Proxmox pour cette fonction.** L'API de Proxmox VE 9 n'a pas de route pour un dépôt libre (`apidoc.js`) :
`/nodes/{n}/apt/repositories` sait lire (`GET`), activer / désactiver un dépôt existant (`POST`) et ajouter un dépôt **standard** par son
nom (`PUT` avec `handle`). L'interface de Proxmox n'ajoute pas non plus de dépôt libre. Kaji fait donc comme pour « installer les mises à
jour » : il valide les champs et fabrique le fichier et les commandes à coller dans la console du nœud (bouton « Dépôt personnalisé… » de la
section « Dépôts de paquets » de la page Nœud).

| Route | Corps | Résultat |
|---|---|---|
| `POST …/nodes/{n}/apt/repositories/custom` | `{name, types, uris, suites, components, signed_by?, architectures?}` | `{file, content, commands, warnings, exists}` (aucune écriture ; droit `Sys.Audit` pour relire les fichiers du nœud) |

## Champs (liste blanche, aucun texte libre)
- `name` : `^[a-z0-9][a-z0-9-]{0,59}$` → fichier `/etc/apt/sources.list.d/<name>.sources`.
- `types` : `deb` et / ou `deb-src`, sans doublon.
- `uris` : 1 à 3 adresses `http://` ou `https://`, **sans identifiant** (`user:pass@`), sans `?`, `#`, espace, `..` ni `//` dans le chemin, port de 1 à 65535.
- `suites` : 1 à 5 (`trixie`, `stable/updates`) ; `components` : 1 à 8, minuscules.
- `signed_by` : chemin d'une clé **déjà posée** sous `/usr/share/keyrings/` ou `/etc/apt/keyrings/`, `.gpg` ou `.asc`. Kaji n'accepte **jamais** le contenu d'une clé et ne télécharge rien.
- `architectures` : parmi `amd64`, `arm64`, `armhf`, `i386`, `all`.

## Résultat
- `content` : le fichier deb822, champs dans un ordre fixe, recalculé à partir des champs validés.
- `commands` : `cat > <fichier> <<'KAJI_EOF' … KAJI_EOF` (délimiteur entre guillemets : le shell n'interprète rien) puis `apt update`.
- `warnings` : adresse `http` (non chiffrée), absence de `Signed-By`, clé à poser soi-même, dépôt de Proxmox (préférer le dépôt standard), composant de test, et **fichier du même nom déjà présent** (la commande le remplacerait). `exists` vaut `null` si les dépôts du nœud sont illisibles : la génération n'est pas bloquée (rien n'est écrit).

Pas d'entrée d'audit : aucune écriture, aucun secret. Tests : `backend/tests/test_apt_custom.py` (58 cas, 19 mutations tuées).
