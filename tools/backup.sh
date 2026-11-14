#!/bin/sh
# Sauvegarde de Kaji : la BASE, cohérente, SANS arrêter Kaji. La CLÉ `KAJI_SECRET_KEY` (fichier `.env`) n'est PAS dans la base : à sauvegarder À PART.
#
#   tools/backup.sh [DOSSIER]        (défaut : ./sauvegardes dans le dossier de Kaji ; un chemin relatif se lit depuis ce dossier ; fichier kaji-AAAAMMJJ-HHMMSS.db)
#
# Lance `python -m app.admin_cli backup --stdout` dans le conteneur `backend` (copie par l'API de sauvegarde de SQLite), écrit le flux dans un fichier en 600,
# puis RELIT cette copie avec la clé actuelle (`verify --file -`) : si un jeton ou un webhook n'est pas lisible, le script échoue et le dit.
# Voir docs/deploiement.md.
set -eu
cd "$(dirname "$0")/.."
. tools/_compose.sh

DEST=${1:-sauvegardes}
umask 077
mkdir -p "$DEST"
chmod 700 "$DEST"
OUT="$DEST/kaji-$(date +%Y%m%d-%H%M%S).db"
[ ! -e "$OUT" ] || { echo "$OUT existe déjà : réessaie dans une seconde." >&2; exit 1; }

if ! docker compose exec -T backend python -m app.admin_cli backup --stdout > "$OUT.partiel"; then
  rm -f "$OUT.partiel"
  echo "Échec de la sauvegarde : rien n'a été écrit." >&2
  exit 1
fi
if ! head -c 15 "$OUT.partiel" | grep -q 'SQLite format 3'; then
  rm -f "$OUT.partiel"
  echo "La sortie n'est pas une base SQLite : rien n'a été écrit." >&2
  exit 1
fi
mv "$OUT.partiel" "$OUT"
if ! docker compose exec -T backend python -m app.admin_cli verify --file - < "$OUT"; then
  echo "La copie $OUT n'est PAS exploitable avec la clé actuelle (voir ci-dessus). Ne t'y fie pas." >&2
  exit 1
fi
echo
echo "Base sauvegardée : $OUT"
echo "À FAIRE : sauvegarder AUSSI le fichier .env (il contient KAJI_SECRET_KEY), séparément de la base et en lieu sûr (gestionnaire de mots de passe)."
echo "Sans cette clé, la base ne sert à rien : les jetons Proxmox et les webhooks y sont chiffrés. Compare l'empreinte de la clé affichée plus haut."
