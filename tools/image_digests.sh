#!/bin/sh
# Empreintes des images de base de Kaji : vérifie (ou met à jour) les `image:étiquette@sha256:…` des Dockerfile et de docker-compose.tls.yml.
#
#   tools/image_digests.sh            compare chaque empreinte épinglée à celle que Docker Hub sert AUJOURD'HUI pour la même étiquette
#   tools/image_digests.sh --update   réécrit les fichiers avec les nouvelles empreintes (puis : relire `git diff`, reconstruire, tester)
#
# Besoin : curl et jq. Lecture seule sur Docker Hub (images officielles `library/…` seulement : une autre source est refusée).
# Code de sortie : 0 = tout est à jour, 1 = au moins une empreinte a changé, 2 = erreur.
# Sans `--update`, rien n'est écrit. Voir docs/images-et-versions.md.
set -eu

cd "$(dirname "$0")/.."
FILES="backend/Dockerfile frontend/Dockerfile docker-compose.tls.yml"
UPDATE=0
case "${1:-}" in
  "") ;;
  --update) UPDATE=1 ;;
  *) echo "usage : $0 [--update]" >&2; exit 2 ;;
esac
command -v curl >/dev/null && command -v jq >/dev/null || { echo "curl et jq sont nécessaires" >&2; exit 2; }

ACCEPT="application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"

# Une ligne par image épinglée : « fichier<TAB>nom:étiquette<TAB>empreinte »
refs=$(grep -HoE '[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}' $FILES | sed -E 's/^([^:]+):(.+)@(sha256:[0-9a-f]{64})$/\1\t\2\t\3/')
[ -n "$refs" ] || { echo "aucune image épinglée trouvée dans : $FILES" >&2; exit 2; }

printf '%s\n' "$refs" | while IFS="$(printf '\t')" read -r file ref pinned; do
  name=${ref%%:*}; tag=${ref#*:}
  case "$name" in */*) echo "$file : $ref n'est pas une image officielle de Docker Hub, à vérifier à la main" >&2; exit 2 ;; esac
  repo="library/$name"
  token=$(curl -fsS "https://auth.docker.io/token?service=registry.docker.io&scope=repository:$repo:pull" | jq -r .token)
  current=$(curl -fsSI -H "Authorization: Bearer $token" -H "Accept: $ACCEPT" "https://registry-1.docker.io/v2/$repo/manifests/$tag" \
            | tr -d '\r' | awk -F': ' 'tolower($1)=="docker-content-digest"{print $2}')
  case "$current" in sha256:[0-9a-f]*) ;; *) echo "$file : empreinte de $ref illisible" >&2; exit 2 ;; esac
  if [ "$current" = "$pinned" ]; then
    echo "à jour    $file  $ref"
  else
    echo "NOUVEAU   $file  $ref"
    echo "            épinglée : $pinned"
    echo "            actuelle : $current"
    echo "x" >> "${TMPDIR:-/tmp}/kaji-digests-changed.$$"
    [ "$UPDATE" = 1 ] && sed -i "s#$ref@$pinned#$ref@$current#" "$file"
  fi
done || exit 2

if [ -e "${TMPDIR:-/tmp}/kaji-digests-changed.$$" ]; then
  rm -f "${TMPDIR:-/tmp}/kaji-digests-changed.$$"
  [ "$UPDATE" = 1 ] && echo "Fichiers mis à jour : relis \`git diff\`, reconstruis (docker compose build) et teste avant de commiter." >&2
  exit 1
fi
exit 0
