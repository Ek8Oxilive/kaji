#!/bin/sh
# Essai de bout en bout AVEC LE VRAI DOCKER (jalon J1 #429 et J3 #456). À lancer sur une machine jetable (CI GitHub) : il crée un projet
# Compose « kajiessai » et le DÉTRUIT à la fin. Jamais sur une installation réelle.
#
#   tools/essai_docker.sh sauvegarde    sauvegarde puis restauration (tools/backup.sh, tools/restore.sh) : un compte créé APRÈS la sauvegarde disparaît
#   tools/essai_docker.sh mise-a-jour   installe la version ÉTIQUETÉE donnée (KAJI_ANCIENNE, défaut v1.0.0-rc1), crée des données, passe au code courant
#
# Ce que ça prouve : le conteneur, le volume, l'utilisateur non root et `--wait` marchent avec nos scripts ; ce que ça ne prouve pas : l'interface dans un navigateur.
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
MODE=${1:-}
export COMPOSE_PROJECT_NAME=kajiessai
export KAJI_PORT=18080 KAJI_BIND=127.0.0.1
B=http://127.0.0.1:18080
PASS='un-mot-de-passe-de-essai-12'
WORK=$(mktemp -d)
JAR="$WORK/jar"

compose() { docker compose "$@"; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
json() { curl -s -H 'content-type: application/json' "$@"; }
ok() { echo "OK  $*"; }
fail() { echo "ÉCHEC $*" >&2; exit 1; }
cleanup() {
  status=$?
  [ "$status" -eq 0 ] || { (cd "$ROOT" && compose logs --no-color --tail 80 2>/dev/null) || true; }
  (cd "$ROOT" && compose down -v >/dev/null 2>&1) || true
  [ -z "${OLD_TREE:-}" ] || { (cd "$OLD_TREE" && compose down -v >/dev/null 2>&1) || true; git -C "$ROOT" worktree remove --force "$OLD_TREE" 2>/dev/null || true; }
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

setup_admin() {   # première configuration + connexion
  [ "$(code -c "$JAR" -X POST $B/api/auth/setup -H 'content-type: application/json' -d "{\"username\":\"admin\",\"password\":\"$PASS\"}")" = 201 ] || fail "création du compte admin"
}
login() {
  rm -f "$JAR"
  [ "$(code -c "$JAR" -X POST $B/api/auth/login -H 'content-type: application/json' -d "{\"username\":\"admin\",\"password\":\"$PASS\"}")" = 200 ] || fail "connexion admin"
}
create_user() {   # $1 = nom
  [ "$(code -b "$JAR" -X POST $B/api/kaji-users -H 'content-type: application/json' -d "{\"username\":\"$1\",\"password\":\"$PASS-x\",\"role\":\"viewer\"}")" = 201 ] || fail "création du compte $1"
}
has_user() { curl -s -b "$JAR" $B/api/kaji-users | grep -q "\"username\": *\"$1\""; }
write_env() { printf 'KAJI_SECRET_KEY=%s\nKAJI_COOKIE_SECURE=false\n' "$(openssl rand -base64 36 | tr -d '\n')" > "$1/.env"; }

case "$MODE" in
sauvegarde)
  write_env "$ROOT"
  compose up -d --build --wait --wait-timeout 240
  setup_admin; login
  create_user avant-sauvegarde
  has_user avant-sauvegarde || fail "le compte avant-sauvegarde n'est pas listé"
  ok "installation neuve, compte créé"

  sh tools/backup.sh "$WORK/sauv"
  FILE=$(ls "$WORK"/sauv/kaji-*.db)
  [ -s "$FILE" ] && [ "$(stat -c %a "$FILE")" = 600 ] || fail "fichier de sauvegarde absent ou pas en 600"
  ok "sauvegarde faite, relue avec la clé, fichier en 600"

  create_user apres-sauvegarde
  has_user apres-sauvegarde || fail "apres-sauvegarde absent avant restauration"

  # Un fichier qui n'est pas une base est refusé SANS toucher à l'installation
  echo "pas une base" > "$WORK/faux.db"
  if sh tools/restore.sh "$WORK/faux.db" --yes; then fail "restore.sh a accepté un faux fichier"; fi
  login; has_user apres-sauvegarde || fail "l'installation a été touchée par un refus"
  ok "faux fichier refusé, installation intacte"

  sh tools/restore.sh "$FILE" --yes
  login
  has_user avant-sauvegarde || fail "avant-sauvegarde perdu après restauration"
  if has_user apres-sauvegarde; then fail "apres-sauvegarde devrait avoir disparu"; fi
  compose exec -T backend python -m app.migrations status | grep -q "'pending': \[\]" || fail "migrations en attente après restauration"
  compose run --rm -T --no-deps backend sh -c 'ls /data | grep -q "kaji.db.avant-restauration-"' || fail "l'ancienne base n'a pas été gardée"
  [ "$(compose exec -T backend id -u | tr -d '\r')" != 0 ] || fail "le backend tourne en root"
  ok "restauration : état d'avant la sauvegarde retrouvé, ancienne base gardée, migrations à jour"

  # Une autre clé ne peut pas relire la base : la commande `verify` ne doit pas dire « tout va bien » sur une base qui contient des secrets chiffrés
  # (ici la base n'en contient pas : on vérifie seulement que verify répond sans erreur avec la bonne clé).
  compose exec -T backend python -m app.admin_cli verify >/dev/null || fail "verify échoue avec la bonne clé"
  ok "verify répond avec la bonne clé"
  ;;

mise-a-jour)
  OLD=${KAJI_ANCIENNE:-v1.0.0-rc1}
  OLD_TREE="$WORK/ancienne"
  git worktree add --detach "$OLD_TREE" "$OLD" >/dev/null
  write_env "$OLD_TREE"
  cp "$OLD_TREE/.env" "$ROOT/.env"
  (cd "$OLD_TREE" && compose up -d --build --wait --wait-timeout 300)
  setup_admin; login
  create_user avant-mise-a-jour
  ok "version $OLD installée, données créées"
  (cd "$OLD_TREE" && compose stop)

  # Même projet Compose, même volume, code courant : on reconstruit et on redémarre sur la base de l'ancienne version
  compose up -d --build --wait --wait-timeout 300
  login
  has_user avant-mise-a-jour || fail "compte perdu à la mise à jour"
  compose exec -T backend python -m app.migrations status | grep -q "'pending': \[\]" || fail "migrations en attente après la mise à jour"
  compose exec -T backend python -m app.admin_cli verify >/dev/null || fail "verify échoue après la mise à jour"
  ok "mise à jour $OLD → code courant : données conservées, migrations appliquées, verify OK"

  # Retour arrière : sauvegarde du code courant, nouvelles données, restauration
  sh tools/backup.sh "$WORK/sauv"
  create_user apres-mise-a-jour
  sh tools/restore.sh "$(ls "$WORK"/sauv/kaji-*.db)" --yes
  login
  has_user avant-mise-a-jour || fail "perdu après le retour arrière"
  if has_user apres-mise-a-jour; then fail "apres-mise-a-jour devrait avoir disparu"; fi
  ok "retour arrière par restauration"
  ;;

*)
  echo "usage : tools/essai_docker.sh sauvegarde | mise-a-jour" >&2
  exit 2
  ;;
esac
echo "ESSAI RÉUSSI : $MODE"
