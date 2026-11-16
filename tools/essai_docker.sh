#!/bin/sh
# Essai de bout en bout AVEC LE VRAI DOCKER (jalon J1 #429 et J3 #456). À lancer sur une machine jetable (CI GitHub) : il crée un projet
# Compose « kajiessai » et le DÉTRUIT à la fin. Jamais sur une installation réelle.
#
#   tools/essai_docker.sh sauvegarde    sauvegarde puis restauration (tools/backup.sh, tools/restore.sh) : un compte créé APRÈS la sauvegarde disparaît
#   tools/essai_docker.sh chiffre-https connexion Proxmox (jeton chiffré) vers un faux Proxmox en conteneur, HTTPS Caddy, sauvegarde / restauration / mauvaise clé
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
[ ! -e .env ] || { echo "Un fichier .env existe déjà ici : cet essai le remplacerait. Lance-le sur une copie propre du dépôt (CI) ou déplace .env." >&2; exit 2; }
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
  docker rm -f fakepve >/dev/null 2>&1 || true
  rm -f "$ROOT/.env"
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

chiffre-https)
  SECRET="secret-de-essai-$(openssl rand -hex 8)"
  export KAJI_TLS_PORT=18443 KAJI_HTTP_PORT=18081 KAJI_TLS_BIND=127.0.0.1 KAJI_TLS_SITE=localhost KAJI_TLS_NAME=kaji.localhost
  export COMPOSE_FILE=docker-compose.yml:docker-compose.tls.yml
  write_env "$ROOT"
  echo "KAJI_COOKIE_SECURE=true" >> .env      # la dernière valeur l'emporte pour compose, mais le fichier a déjà « false » : on réécrit proprement
  sed -i '/^KAJI_COOKIE_SECURE=false$/d' .env
  compose up -d --build --wait --wait-timeout 300
  HB=https://localhost:18443          # le NOM compte : Caddy ne répond (200 vide) à aucun autre Host que KAJI_TLS_SITE / KAJI_TLS_NAME
  cu() { curl -sk --resolve localhost:18443:127.0.0.1 "$@"; }
  [ "$(cu $HB/api/health)" = '{"status":"ok"}' ] || fail "HTTPS ne relaie pas vers Kaji : $(cu $HB/api/health)"
  [ "$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost' http://127.0.0.1:18081/api/health)" = 308 ] || fail "le port 80 ne renvoie pas vers HTTPS (308 attendu)"
  ok "HTTPS Caddy : 200 en HTTPS, 308 en HTTP"
  # Par défaut, l'accès HTTP clair de nginx reste LOCAL à la machine (127.0.0.1) : il ne s'ouvre au réseau que par KAJI_BIND (docs/deploiement.md)
  (unset KAJI_BIND KAJI_PORT; compose config | grep -B2 'published: "8080"' | grep -q 'host_ip: 127.0.0.1') || fail "nginx n'est pas limité à 127.0.0.1 par défaut"
  ok "nginx limité à 127.0.0.1 par défaut (accès réseau = HTTPS Caddy seulement)"
  B=$HB
  code() { cu -o /dev/null -w '%{http_code}' "$@"; }
  json() { cu -H 'content-type: application/json' "$@"; }
  cu -D "$WORK/h" -o /dev/null -c "$JAR" -X POST $B/api/auth/setup -H 'content-type: application/json' -d "{\"username\":\"admin\",\"password\":\"$PASS\"}"
  grep -qi "^set-cookie:.*secure" "$WORK/h" || { cat "$WORK/h" >&2; fail "le cookie de session n'est pas marqué Secure"; }
  grep -qi '^set-cookie:.*httponly' "$WORK/h" || fail "le cookie de session n'est pas HttpOnly"
  ok "cookie de session Secure et HttpOnly en HTTPS"
  [ "$(code -b "$JAR" $B/api/auth/me)" = 200 ] || fail "session refusée en HTTPS"

  # Faux Proxmox dans un conteneur du même réseau (le conteneur backend a déjà `cryptography`)
  IMG=$(compose images backend -q | head -1)
  docker run -d --name fakepve --network kajiessai_default -e KAJI_FAKE_BIND=0.0.0.0 -v "$ROOT/tools:/tools:ro" --entrypoint python "$IMG" /tools/fake_proxmox.py --port 8643 >/dev/null
  sleep 3
  PVE=$(docker inspect -f '{{(index .NetworkSettings.Networks "kajiessai_default").IPAddress}}' fakepve)
  CODE=$(code -b "$JAR" -X POST $B/api/connections -H 'content-type: application/json' \
    -d "{\"name\":\"faux\",\"host\":\"$PVE\",\"port\":8643,\"user\":\"kaji@pve\",\"token_id\":\"kaji\",\"token_secret\":\"$SECRET\",\"verify_ssl\":false}")
  [ "$CODE" = 201 ] || fail "création de la connexion : $CODE"
  ok "connexion Proxmox créée (jeton chiffré)"
  CID=$(cu -b "$JAR" $B/api/connections | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["id"])')
  [ "$(code -b "$JAR" -X POST $B/api/connections/$CID/test)" = 200 ] || fail "le test de la connexion échoue"
  ok "Kaji joint le faux Proxmox avec le jeton déchiffré"

  # Le secret n'est écrit en clair ni dans la base, ni dans la sauvegarde, ni dans les journaux
  compose exec -T backend sh -c "grep -c '$SECRET' /data/kaji.db" | grep -qx 0 || fail "le jeton est en clair dans la base"
  sh tools/backup.sh "$WORK/sauv" > "$WORK/backup.log"
  grep -q "Connexions Proxmox : 1 ; jetons déchiffrés : 1/1" "$WORK/backup.log" || fail "la sauvegarde ne relit pas le jeton"
  if grep -rq "$SECRET" "$WORK/sauv" "$WORK/backup.log"; then fail "le jeton est en clair dans la sauvegarde"; fi
  compose logs --no-color 2>&1 | grep -q "$SECRET" && fail "le jeton apparaît dans les journaux"
  ok "jeton chiffré dans la base et la sauvegarde, relu 1/1, absent des journaux"

  FILE=$(ls "$WORK"/sauv/kaji-*.db)
  # Mauvaise clé : la restauration est REFUSÉE et l'installation reste intacte
  cp .env "$WORK/env.bon"
  sed -i "s/^KAJI_SECRET_KEY=.*/KAJI_SECRET_KEY=$(openssl rand -hex 24)/" .env
  if sh tools/restore.sh "$FILE" --yes > "$WORK/restore-mauvaise-cle.log" 2>&1; then fail "restore.sh a accepté une mauvaise clé"; fi
  grep -q "REFUSÉE" "$WORK/restore-mauvaise-cle.log" || { cat "$WORK/restore-mauvaise-cle.log" >&2; fail "refus pour une autre raison qu'une clé illisible"; }
  grep -qi "cl[ée]" "$WORK/restore-mauvaise-cle.log" || fail "le refus ne parle pas de la clé"
  ok "restauration avec une mauvaise clé refusée (message sur la clé)"
  cp "$WORK/env.bon" .env
  compose up -d --wait --wait-timeout 120 backend
  cu -c "$JAR" -o /dev/null -X POST $B/api/auth/login -H 'content-type: application/json' -d "{\"username\":\"admin\",\"password\":\"$PASS\"}"
  [ "$(code -b "$JAR" -X POST $B/api/connections/$CID/test)" = 200 ] || fail "après le refus, la connexion ne marche plus"

  # Restauration normale avec la bonne clé : la connexion est toujours utilisable
  sh tools/restore.sh "$FILE" --yes > "$WORK/restore.log" 2>&1 || { cat "$WORK/restore.log"; fail "restauration avec la bonne clé"; }
  cu -c "$JAR" -o /dev/null -X POST $B/api/auth/login -H 'content-type: application/json' -d "{\"username\":\"admin\",\"password\":\"$PASS\"}"
  [ "$(code -b "$JAR" -X POST $B/api/connections/$CID/test)" = 200 ] || fail "après restauration, la connexion ne marche plus"
  ok "restauration avec la bonne clé : connexion et jeton utilisables, HTTPS toujours en service"
  docker rm -f fakepve >/dev/null 2>&1 || true
  ;;

*)
  echo "usage : tools/essai_docker.sh sauvegarde | mise-a-jour | chiffre-https" >&2
  exit 2
  ;;
esac
echo "ESSAI RÉUSSI : $MODE"
