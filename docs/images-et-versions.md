# Images de base épinglées et versions étiquetées

Deux sujets liés au jalon J1 (`docs/cadrage-prod-entreprise.md`, ticket #427) : **reconstruire Kaji deux fois donne les mêmes images**, et **une version a un nom, une rubrique dans le journal et une étiquette Git**.

## 1. Images de base épinglées par empreinte

Kaji n'est pas publié sur un registre d'images : chaque installation le **construit** (`docker compose up -d --build`). Les images de départ sont donc désignées par `nom:étiquette@sha256:<empreinte>` :

| Image | Où | Rôle |
|---|---|---|
| `python:3.12-slim` | `backend/Dockerfile` | backend FastAPI |
| `node:22-alpine` | `frontend/Dockerfile` (étage `build`) | construction du frontend |
| `nginx:1.27-alpine` | `frontend/Dockerfile` | service des fichiers et relais de `/api` |
| `caddy:2.8-alpine` | `docker-compose.tls.yml` | HTTPS facultatif |

- **L'empreinte fait foi**, l'étiquette ne sert qu'à la lecture et à la mise à jour : quand les deux sont présentes, Docker ne regarde que l'empreinte.
- Ce sont des **index multi-architectures** (amd64 et arm64 au moins) : l'épinglage ne bloque aucune machine.
- Relevées sur Docker Hub le 2026-11-14 (`tools/image_digests.sh` compare à l'état du jour).
- **Contrepartie** : une image épinglée **ne reçoit plus de correctif de sécurité tant qu'on ne change pas l'empreinte** (même étiquette, nouvelle empreinte à chaque reconstruction de l'éditeur). Il faut donc la mettre à jour régulièrement : au moins à chaque version, et dès qu'une faille de l'image est annoncée.

### Mettre à jour les empreintes
**Automatique** : Dependabot (`.github/dependabot.yml`, écosystèmes `docker` et `docker-compose`) ouvre une PR hebdomadaire quand une étiquette ou une empreinte change. La CI construit alors la pile complète et la teste (job `docker`), et tire l'image Caddy (job `docker`, étape « L'image Caddy épinglée existe »).

**À la main** (machine avec `curl` et `jq`, sans Docker nécessaire) :
```bash
tools/image_digests.sh             # compare : « à jour » ou « NOUVEAU », code de sortie 1 s'il y a du nouveau
tools/image_digests.sh --update    # réécrit les empreintes dans les Dockerfile et docker-compose.tls.yml
git diff                           # relire : seules des empreintes doivent changer
docker compose build --no-cache    # puis tester (docker compose up -d, page de connexion, une action réversible)
```
Pour **changer d'étiquette** (par exemple `python:3.13-slim`), modifie l'étiquette dans le fichier, puis lance `tools/image_digests.sh --update` (l'empreinte est relevée pour la nouvelle étiquette ; si elle est fausse, le script la corrige). Le script ne gère que les images officielles de Docker Hub (`library/…`).

Un test (`backend/tests/test_images_pinned.py`) échoue si une image est ajoutée sans empreinte, si elle utilise `latest`, ou si le script ne contrôle pas un fichier qui en contient une.

**Non vérifié** : que Dependabot comprenne `docker-compose.tls.yml` (son écosystème `docker-compose` ne cite que `docker-compose.yml` dans sa documentation) ; si aucune PR n'arrive pour Caddy, lancer le script à la main.

## 2. Versions étiquetées

### Nommage
`vMAJEUR.MINEUR.CORRECTIF`, avec un suffixe `-rcN` tant que la version n'est pas jugée stable : **`v1.0.0-rc1`** (existante), `v1.0.0-rc2`, … jusqu'au jalon J4, où `v1.0.0` sera décidée par le propriétaire (`docs/cadrage-prod-entreprise.md`). Après la 1.0.0 : correctif de sécurité ou de bogue = `CORRECTIF`+1 ; fonction nouvelle sans casse = `MINEUR`+1 ; casse (migration manuelle, variable renommée) = `MAJEUR`+1.

Une version = **une étiquette Git** qui désigne un commit de `main` dont la CI est verte. Il n'y a pas d'image à publier (voir plus haut) : installer une version, c'est `git checkout <étiquette>` puis construire (`docs/installation-lab.md`, étape 8).

### Publier une version (décision et geste du propriétaire)
1. `git checkout main && git pull` ; CI de `main` verte.
2. `tools/image_digests.sh` : les empreintes sont-elles à jour ? Sinon, section 1.
3. `CHANGELOG.md` : le contenu de « Non publié » devient la rubrique `[X.Y.Z-rcN] - AAAA-MM-JJ`, une nouvelle rubrique « Non publié » vide reste en tête, et les liens de bas de page sont mis à jour. **Le test `test_release_docs.py` échoue si une étiquette Git n'a pas sa rubrique.**
4. **Base d'exemple de la version** (test de mise à jour, ticket #456) : `backend/.venv/bin/python tools/snapshot_db.py HEAD backend/tests/fixtures/db/kaji-vX.Y.Z-rcN.db`, à commiter **dans la PR de release** (le code de `HEAD` est celui qui sera étiqueté). La CI migre chaque base de ce dossier vers le code courant et **échoue si une étiquette n'a pas la sienne**.
5. PR `chore(release): vX.Y.Z-rcN`, CI verte, fusion.
6. Étiqueter le commit de fusion (le push de l'étiquette déclenche le workflow « SBOM et audit » : `docs/sbom.md`, SBOM joints à la release si elle existe), avec une étiquette **annotée** (la signature viendra au jalon J4) :
   ```bash
   git fetch && git checkout main && git pull
   git tag -a vX.Y.Z-rcN -m "Kaji X.Y.Z-rcN"
   git push origin vX.Y.Z-rcN
   gh release create vX.Y.Z-rcN --prerelease --title "Kaji X.Y.Z-rcN" --notes "Journal des changements : CHANGELOG.md, rubrique [X.Y.Z-rcN]."
   ```
7. Redéployer l'installation d'exploitation sur cette étiquette.

Les agents **ne créent ni ne poussent d'étiquette** sans demande explicite du propriétaire : publier est son geste.

**Limite connue** : `v1.0.0-rc1` est une étiquette **légère** (sans message ni signature) posée sur le commit de la PR #424 ; elle n'est pas modifiée, les suivantes seront annotées.
