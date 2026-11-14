#!/bin/sh
# Restauration de la base de Kaji depuis une sauvegarde de tools/backup.sh. DANGEREUX : remplace la base en service (l'ancienne est gardée à côté).
#
#   tools/restore.sh FICHIER.db [--yes]
#
# Avant : remets le MÊME `.env` (même KAJI_SECRET_KEY) que celui de la sauvegarde. Le script refuse une sauvegarde que la clé actuelle ne peut pas lire.
# Déroulé : confirmation (taper RESTAURER) → arrêt du backend → `restore` dans un conteneur jetable (contrôles : base saine, schéma pas trop récent, secrets lisibles
# avec la clé ; l'ancienne base devient kaji.db.avant-restauration-AAAAMMJJ-HHMMSS) → redémarrage → `verify`.
# Voir docs/deploiement.md.
set -eu
FILE=${1:-}
YES=${2:-}
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "usage : tools/restore.sh FICHIER.db [--yes]" >&2; exit 2; }
head -c 15 "$FILE" | grep -q 'SQLite format 3' || { echo "$FILE n'est pas une base SQLite : rien n'a été fait." >&2; exit 2; }
FILE=$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")      # chemin absolu : on change de dossier juste après
cd "$(dirname "$0")/.."
. tools/_compose.sh

if [ "$YES" != "--yes" ]; then
  echo "Cela va REMPLACER la base de Kaji par $FILE (comptes, connexions, jetons, planifications, audit)."
  echo "L'ancienne base est conservée dans le volume (kaji.db.avant-restauration-…). Kaji sera arrêté quelques instants."
  printf "Tape RESTAURER pour continuer : "
  read -r answer
  [ "$answer" = "RESTAURER" ] || { echo "Annulé : rien n'a été fait." >&2; exit 1; }
fi

docker compose stop backend
if ! docker compose run --rm -T --no-deps backend python -m app.admin_cli restore - --yes < "$FILE"; then
  echo "Restauration REFUSÉE ou échouée : la base n'a pas été modifiée. Redémarrage de Kaji avec l'ancienne base." >&2
  docker compose up -d backend
  exit 1
fi
docker compose up -d --wait backend
echo
echo "Contrôle de la base restaurée :"
docker compose exec -T backend python -m app.admin_cli verify
echo "Termine par un essai à la main : connexion à Kaji, page « Connexions » → « Tester », liste des actions planifiées et des alertes."
