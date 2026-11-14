# À « sourcer » par tools/backup.sh et tools/restore.sh : choisit les fichiers Docker Compose de l'installation.
# Si le HTTPS est actif (conteneur « tls » en marche), les deux fichiers sont utilisés ; sinon `docker compose` ne verrait pas le même réseau.
# Une installation qui a déjà réglé COMPOSE_FILE (variable standard de Docker Compose) est laissée telle quelle.
if [ -z "${COMPOSE_FILE:-}" ] && [ -f docker-compose.tls.yml ]; then
  if docker compose -f docker-compose.yml -f docker-compose.tls.yml ps --status running --services 2>/dev/null | grep -qx tls; then
    COMPOSE_FILE=docker-compose.yml:docker-compose.tls.yml
    export COMPOSE_FILE
  fi
fi
