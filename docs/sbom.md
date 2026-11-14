# Liste des composants (SBOM) et suivi des vulnérabilités

Jalon J4 (`docs/cadrage-prod-entreprise.md`, ticket #459). Un **SBOM** (« software bill of materials ») dit **de quoi Kaji est fait** : chaque dépendance, sa version, d'où elle vient. Il sert à répondre vite à « sommes-nous touchés par la faille X ? ».

## Ce que contient chaque version
Au moment de l'étiquette `vX.Y.Z`, le workflow **« SBOM et audit »** (`.github/workflows/sbom.yml`) produit trois sortes de fichiers au format **CycloneDX** (JSON) :

| Fichier | Contenu | Comment |
|---|---|---|
| `sbom-python.cdx.json` | dépendances Python du backend, **transitives comprises** | `cyclonedx-py environment` sur un environnement où `backend/requirements.txt` a été **installé** (partir du fichier seul ne listerait que les 9 dépendances directes) |
| `sbom-node.cdx.json` | dépendances JavaScript **de production** du frontend | `npm sbom --omit dev` après `npm ci` |
| `sbom-image-<nom>_<étiquette>.cdx.json` | paquets système de chaque **image de base épinglée** (`python`, `node`, `nginx`, `caddy`) | `syft` sur l'image désignée **par son empreinte** (`docs/images-et-versions.md`) |

Ils sont **joints à la release** de l'étiquette si elle existe (la créer est le geste du propriétaire), sinon gardés comme **artefacts du workflow**.

## Ils sont contrôlés, pas seulement produits
`tools/check_sbom.py` refuse un SBOM invalide ou **périmé** : JSON CycloneDX valide, composants non vides, nom et version présents, et surtout **chaque dépendance épinglée (`==`) de `requirements.txt`, chaque paquet de production de `package-lock.json` y figure avec la même version** ; pour une image, l'**empreinte épinglée figure dans le SBOM** (c'est bien cette image qui a été analysée). Le même workflow tourne sur les PR qui touchent une dépendance ou une image : un SBOM impossible à produire ne se découvre pas le jour de la version.

## Suivi des vulnérabilités
Le workflow tourne aussi **chaque lundi** et à la demande :
- `pip-audit -r backend/requirements.txt` : **aucune vulnérabilité connue** n'est tolérée, sauf **exception déclarée** dans `tools/audit-exceptions.txt` (identifiant + justification + date de réexamen).
- `npm audit --omit=dev` : dépendances de production ; **npm n'a pas de mécanisme d'exception** : une alerte à écarter se traite en mettant à jour, ou en la documentant ici avant de neutraliser l'étape.
- État au 2026-11-14 : les deux audits ne signalent **rien**, aucune exception.
- Dependabot ouvre les PR de mise à jour (`.github/dependabot.yml`) ; une image épinglée ne reçoit de correctif que si son empreinte change (`tools/image_digests.sh`).

## Lire un SBOM
```bash
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); [print(c['name'], c['version']) for c in d['components']]" sbom-python.cdx.json
```
Les outils standards (`grype`, `osv-scanner`, `dependency-track`) lisent le CycloneDX directement.

## Validé en réel, et ce qui ne l'a pas été
- **Essayé en local** : génération Python (environnement propre : 32 composants) et JavaScript (8 composants de production), contrôle par `check_sbom.py` (conformes ; le contrôleur a fait remarquer qu'un SBOM issu de `requirements.txt` seul serait incomplet, et que les paquets `devOptional` du verrou n'appartiennent pas à la production), `pip-audit` et `npm audit` (rien).
- **Jamais essayé en local** : les SBOM d'images (`syft` n'est pas disponible sur le poste de rédaction), le workflow lui-même, la jonction à une release. Ils ne sont prouvés que par une exécution réussie du workflow sur GitHub (déclenchée à la main : onglet Actions → « SBOM et audit » → Run workflow).
- Un SBOM **n'est pas signé** à ce jour : la signature des versions est le ticket #458.
