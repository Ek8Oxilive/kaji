# Versions signées

Jalon J4 (`docs/cadrage-prod-entreprise.md`, ticket #458). Objectif : qu'une personne qui télécharge Kaji puisse **prouver** que ce qu'elle installe est bien ce que ce dépôt a publié, sans avoir à nous croire sur parole.

## Ce qui est signé
Chaque étiquette `vX.Y.Z` déclenche le workflow **« Signature des versions »** (`.github/workflows/release-sign.yml`) qui produit, dans le même dossier :

| Fichier | Rôle |
|---|---|
| `kaji-vX.Y.Z.tar.gz` | l'**archive des sources** exactement telle qu'elle est dans Git à l'étiquette (`git archive`) |
| `kaji-vX.Y.Z.tar.gz.sha256` | sa somme SHA-256 |
| `kaji-vX.Y.Z.tar.gz.sigstore.json` | la **signature** (paquet Sigstore : signature + certificat + preuve d'inscription au journal public de transparence) |

La signature est **sans clé** (Sigstore) : il n'y a aucune clé privée à garder, à renouveler ou à voler. Le certificat, de quelques minutes, dit **qui a signé** : *ce workflow, de ce dépôt* (identité OIDC de GitHub Actions). Le workflow se **vérifie lui-même** juste après avoir signé ; ces fichiers sont ensuite joints à la release de l'étiquette **si elle existe** (la créer est le geste du propriétaire), sinon ils restent dans les artefacts du workflow.

## Vérifier une version (n'importe qui)
```bash
# fichiers téléchargés dans le même dossier ; cosign installé (https://docs.sigstore.dev/cosign/)
tools/verify_release.sh kaji-v1.0.0.tar.gz            # ou : … Ek8Oxilive/kaji, le dépôt attendu
```
Le script contrôle (1) la somme SHA-256, (2) la signature **et** que l'identité signataire est `https://github.com/<dépôt>/.github/workflows/release-sign.yml@…` émise par `https://token.actions.githubusercontent.com` : une signature valide d'un autre dépôt, ou d'une autre personne, est **refusée**. Sortie 0 = authentique, 1 = refusée.

À la main, sans le script :
```bash
cosign verify-blob --bundle kaji-v1.0.0.tar.gz.sigstore.json \
  --certificate-identity-regexp '^https://github.com/Ek8Oxilive/kaji/\.github/workflows/release-sign\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com kaji-v1.0.0.tar.gz
```

## Et les images ?
**Kaji n'est pas publié sous forme d'images** : chaque installation les **construit** depuis les sources (`docker compose up -d --build`). Il n'y a donc pas d'image de Kaji à signer. La chaîne de confiance est : **sources signées** → **images de base épinglées par empreinte** (`docs/images-et-versions.md`) → **liste des composants** (`docs/sbom.md`). Publier des images signées sur un registre (par exemple `ghcr.io`) serait un **nouveau canal de distribution** : décision du propriétaire, non faite.

## Ce qui n'est PAS fait
- **L'étiquette Git n'est pas signée** (`git tag -s`) : cela exige **la clé personnelle du propriétaire** (GPG ou SSH) ; `v1.0.0-rc1` est une étiquette légère. La signature de l'archive par le workflow n'en dépend pas, mais ne prouve pas qui a décidé de publier.
- Les **SBOM** (`docs/sbom.md`) sont joints à la release mais **ne sont pas signés** par ce workflow.
- **Jamais exécuté sur une vraie étiquette** (aucune étiquette n'est créée par un agent). Voir « Essai » ci-dessous.
- Dépend du service public Sigstore (Fulcio, Rekor) : s'il est indisponible, le workflow échoue et la version n'est pas signée (on relance).

## Essai sans publier
Onglet Actions → « Signature des versions » → **Run workflow** : même chaîne (archive, signature, vérification) sur la branche choisie, **sans** étiquette ni release ; les fichiers sont dans les artefacts. C'est ainsi qu'il a été essayé avant la première étiquette signée.

## Validé en réel, et ce qui ne l'a pas été
- **Essayé en local** : `tools/verify_release.sh` avec un faux `cosign` (somme, arguments, refus), les contrôles statiques du workflow.
- **Pas essayé en local** : `cosign` lui-même, la signature, le journal Sigstore : seul un déclenchement manuel du workflow sur GitHub le prouve (résultat noté dans `docs/REPRISE.md` et le ticket #458).
