#!/bin/sh
# Installation express de Kaji : UNE commande, sur une machine Linux (Debian / Ubuntu : Docker est installé au besoin ; ailleurs, Docker doit déjà être là).
#
#   sh install.sh [options]
#
# Ce que fait le script, dans l'ordre (rien n'est caché, relis-le avant de le lancer) :
#   1. vérifie Docker et Docker Compose v2 (sur Debian / Ubuntu : propose de les installer depuis le dépôt officiel de Docker) ;
#   2. récupère Kaji (git clone, ou git pull --ff-only s'il est déjà là) ;
#   3. crée le fichier .env avec des secrets tirés au hasard (droits 600). Un .env EXISTANT n'est JAMAIS modifié ;
#   4. choisit HTTPS (Caddy, certificat interne) si tu donnes l'adresse par laquelle tu ouvriras Kaji, sinon accès local seulement ;
#   5. construit et démarre les conteneurs, attend que Kaji réponde, récupère le certificat de Caddy ;
#   6. affiche l'adresse, le jeton de première configuration et la suite (utilisateur et jeton Proxmox : tools/proxmox-setup.sh).
# Relancer le script met Kaji à jour (git pull, reconstruction) sans toucher à .env ni aux données (volume kaji-data).
#
# Options :
#   --dir DOSSIER      où installer Kaji (défaut : ~/kaji)
#   --address ADRESSE  adresse ou nom par lequel on ouvrira Kaji, SANS port (ex. 192.168.1.50 ou kaji.home) : active HTTPS
#   --local            pas de HTTPS : Kaji n'écoute que sur cette machine (http://127.0.0.1:8080)
#   --yes              ne rien demander (réponses par défaut ; pour un script)
#   --dry-run          afficher ce qui serait fait, sans rien écrire ni installer
#   --ref ETIQUETTE    version à installer (étiquette ou branche ; défaut : main)
#   --repo URL         dépôt à cloner (défaut : le dépôt public de Kaji)
#   --no-docker-install  ne jamais installer Docker : s'arrêter s'il manque
#   --image            utiliser les images publiées (docker compose pull) au lieu de les construire ; voir docker-compose.image.yml
set -eu

REPO_URL="https://github.com/Ek8Oxilive/kaji.git"
DIR="$HOME/kaji"
ADDRESS=""
LOCAL=""
YES=""
DRY=""
REF=""
NO_DOCKER_INSTALL=""
USE_IMAGE=""

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'ERREUR : %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)      [ $# -ge 2 ] || die "--dir demande un dossier"; DIR=$2; shift 2 ;;
    --address)  [ $# -ge 2 ] || die "--address demande une adresse"; ADDRESS=$2; shift 2 ;;
    --local)    LOCAL=1; shift ;;
    --yes|-y)   YES=1; shift ;;
    --dry-run)  DRY=1; shift ;;
    --ref)      [ $# -ge 2 ] || die "--ref demande une étiquette"; REF=$2; shift 2 ;;
    --repo)     [ $# -ge 2 ] || die "--repo demande une adresse"; REPO_URL=$2; shift 2 ;;
    --no-docker-install) NO_DOCKER_INSTALL=1; shift ;;
    --image)    USE_IMAGE=1; shift ;;
    -h|--help)  sed -n '2,29p' "$0"; exit 0 ;;
    *)          die "option inconnue : $1 (voir --help)" ;;
  esac
done

# Une adresse ne contient que lettres, chiffres, points et tirets : jamais de caractère que le shell ou Caddy interpréterait.
valid_address() { case "$1" in ""|*[!A-Za-z0-9.-]*|.*|-*|*.|*-) return 1 ;; *) return 0 ;; esac; }
[ -z "$ADDRESS" ] || valid_address "$ADDRESS" || die "adresse invalide (lettres, chiffres, points et tirets seulement, sans port ni https://)"
[ -z "$ADDRESS" ] || [ -z "$LOCAL" ] || die "--address et --local s'excluent"

ask() {  # ask "question" "défaut" -> réponse sur stdout
  if [ -n "$YES" ]; then printf '%s' "$2"; return; fi
  printf '%s [%s] : ' "$1" "$2" >&2
  ans=""; read -r ans || ans=""
  [ -n "$ans" ] && printf '%s' "$ans" || printf '%s' "$2"
}
confirm() {  # confirm "question" -> 0 si oui (--yes : oui)
  [ -n "$YES" ] && return 0
  printf '%s [o/N] : ' "$1" >&2
  ans=""; read -r ans || ans=""
  case "$ans" in o|O|oui|OUI|y|Y|yes) return 0 ;; *) return 1 ;; esac
}
run() { if [ -n "$DRY" ]; then say "  (simulation) $*"; else "$@"; fi; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null 2>&1 && SUDO="sudo"
fi

# --- 1. Docker ---------------------------------------------------------------------------------------------------
step "1/5 Docker et Docker Compose"
DOCKER="docker"
have_compose() { $DOCKER compose version >/dev/null 2>&1; }
docker_cmd_works() { docker info >/dev/null 2>&1; }

install_docker() {
  [ -r /etc/os-release ] || die "système inconnu : installe Docker à la main (https://docs.docker.com/engine/install/) puis relance."
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in
    debian|ubuntu) distro=$ID ;;
    *) die "installation automatique de Docker prévue pour Debian et Ubuntu seulement (ici : ${ID:-inconnu}). Installe Docker et Compose v2 (https://docs.docker.com/engine/install/) puis relance ce script." ;;
  esac
  codename=${VERSION_CODENAME:-}
  [ -n "$codename" ] || die "version de $distro non reconnue (VERSION_CODENAME vide) : installe Docker à la main."
  [ "$(id -u)" -eq 0 ] || [ -n "$SUDO" ] || die "il faut les droits root (ou sudo) pour installer Docker."
  say "Installation de Docker depuis le dépôt officiel (download.docker.com/linux/$distro)."
  run $SUDO apt-get update
  run $SUDO apt-get install -y ca-certificates curl git
  run $SUDO install -m 0755 -d /etc/apt/keyrings
  run $SUDO curl -fsSL "https://download.docker.com/linux/$distro/gpg" -o /etc/apt/keyrings/docker.asc
  arch=$(dpkg --print-architecture 2>/dev/null || echo amd64)
  if [ -n "$DRY" ]; then
    say "  (simulation) écrire /etc/apt/sources.list.d/docker.list pour $distro $codename ($arch)"
  else
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' "$arch" "$distro" "$codename" | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null
  fi
  run $SUDO apt-get update
  run $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

if command -v docker >/dev/null 2>&1 && have_compose; then
  say "Docker et Compose v2 sont présents."
else
  say "Docker ou Docker Compose v2 est absent."
  [ -z "$NO_DOCKER_INSTALL" ] || die "Docker manque et --no-docker-install est donné."
  confirm "Installer Docker maintenant (dépôt officiel, droits root requis) ?" || die "Docker est nécessaire. Voir docs/installation-lab.md § 1.2."
  install_docker
  [ -n "$DRY" ] || { command -v docker >/dev/null 2>&1 && have_compose; } || die "Docker n'est pas utilisable après l'installation."
fi
if [ -z "$DRY" ] && ! docker_cmd_works; then
  if [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then
    DOCKER="$SUDO docker"
    say "Ton compte n'est pas dans le groupe « docker » : les commandes Docker du script passent par sudo."
  else
    die "le démon Docker ne répond pas (est-il démarré ? 'sudo systemctl enable --now docker')."
  fi
fi
dc() { $DOCKER compose "$@"; }

command -v git >/dev/null 2>&1 || [ -n "$DRY" ] || die "git est absent : installe-le (sudo apt-get install -y git) puis relance."

# --- 2. Récupérer Kaji -----------------------------------------------------------------------------------------------
step "2/5 Récupération de Kaji dans $DIR"
if [ -e "$DIR" ] && [ ! -d "$DIR/.git" ]; then
  [ -d "$DIR" ] && [ -z "$(ls -A "$DIR" 2>/dev/null)" ] || die "$DIR existe et n'est pas un dépôt Kaji : choisis un autre dossier (--dir)."
fi
if [ -d "$DIR/.git" ]; then
  say "Kaji est déjà là : mise à jour."
  if [ -z "$DRY" ]; then
    [ -z "$(git -C "$DIR" status --porcelain --untracked-files=no)" ] || die "$DIR contient des modifications locales : commite-les ou annule-les, puis relance."
    git -C "$DIR" fetch --tags --quiet
    if [ -n "$REF" ]; then git -C "$DIR" checkout --quiet "$REF"; fi
    git -C "$DIR" pull --ff-only --quiet || say "(pas de mise à jour automatique : étiquette figée ou branche locale)"
  else
    say "  (simulation) git -C $DIR fetch / pull --ff-only"
  fi
else
  run git clone --quiet "$REPO_URL" "$DIR"
  if [ -n "$REF" ]; then run git -C "$DIR" checkout --quiet "$REF"; fi
fi
if [ -n "$DRY" ]; then
  say "(simulation) la suite lit les fichiers de $DIR : arrêt ici."
  exit 0
fi
cd "$DIR"
[ -f docker-compose.yml ] && [ -f .env.example ] || die "$DIR ne ressemble pas à Kaji (docker-compose.yml ou .env.example absent)."

# --- 3. Réglages (.env) --------------------------------------------------------------------------------------------
step "3/5 Réglages (.env)"
NEW_ENV=""
SETUP_TOKEN=""
if [ -f .env ]; then
  say ".env existe : il n'est pas modifié (secrets conservés)."
else
  if [ -z "$ADDRESS" ] && [ -z "$LOCAL" ]; then
    guess=$(hostname -I 2>/dev/null | awk '{print $1}') || guess=""
    say "Par quelle adresse ouvriras-tu Kaji depuis ton poste ? (adresse IP de cette machine ou nom DNS, sans port)"
    say "Réponds « local » pour un accès depuis cette machine seulement (pas de HTTPS)."
    ADDRESS=$(ask "Adresse" "${guess:-local}")
    if [ "$ADDRESS" = "local" ]; then ADDRESS=""; LOCAL=1; fi
    [ -z "$ADDRESS" ] || valid_address "$ADDRESS" || die "adresse invalide (lettres, chiffres, points et tirets seulement)."
  fi
  rand() { LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$1"; }
  SECRET=$(rand 64)
  SETUP_TOKEN=$(rand 32)
  [ "${#SECRET}" -ge 32 ] && [ "${#SETUP_TOKEN}" -ge 24 ] || die "impossible de tirer des secrets au hasard (/dev/urandom)."
  umask 077
  tmp=".env.nouveau.$$"
  sed -e "s|^KAJI_SECRET_KEY=.*|KAJI_SECRET_KEY=$SECRET|" -e "s|^KAJI_SETUP_TOKEN=.*|KAJI_SETUP_TOKEN=$SETUP_TOKEN|" .env.example > "$tmp"
  if [ -n "$ADDRESS" ]; then
    sed -e "s|^# KAJI_TLS_SITE=.*|KAJI_TLS_SITE=$ADDRESS|" "$tmp" > "$tmp.2" && mv "$tmp.2" "$tmp"
  fi
  chmod 600 "$tmp"
  mv "$tmp" .env
  NEW_ENV=1
  say ".env créé (droits 600) avec une clé et un jeton de première configuration tirés au hasard."
fi

TLS=""
grep -q '^KAJI_TLS_SITE=.' .env && TLS=1
PORT=$(sed -n 's/^KAJI_PORT=//p' .env | tail -n 1); PORT=${PORT:-8080}
case "$PORT" in ""|*[!0-9]*) PORT=8080 ;; esac
COMPOSE_ARGS="-f docker-compose.yml"
if [ -n "$USE_IMAGE" ]; then
  [ -f docker-compose.image.yml ] || die "docker-compose.image.yml est absent de cette version : retire --image (Kaji sera construit sur place)."
  COMPOSE_ARGS="$COMPOSE_ARGS -f docker-compose.image.yml"
fi
[ -z "$TLS" ] || COMPOSE_ARGS="$COMPOSE_ARGS -f docker-compose.tls.yml"
# shellcheck disable=SC2086
dcf() { dc $COMPOSE_ARGS "$@"; }

# --- 4. Démarrage -------------------------------------------------------------------------------------------------------
step "4/5 Démarrage (la première fois, la construction prend quelques minutes)"
if [ -n "$USE_IMAGE" ]; then
  dcf pull || die "images introuvables ou inaccessibles (aucune image n'est peut-être publiée pour cette version : voir docs/images-et-versions.md § 3). Relance sans --image pour construire Kaji sur place."
  dcf up -d
else
  dcf up -d --build
fi

step "5/5 Vérification"
# Attente : 60 essais de 2 s (réglable pour les tests : KAJI_INSTALL_TRIES, KAJI_INSTALL_PAUSE).
TRIES=${KAJI_INSTALL_TRIES:-60}; PAUSE=${KAJI_INSTALL_PAUSE:-2}
health="http://127.0.0.1:$PORT/api/health"
ok=""
fetch() { if command -v curl >/dev/null 2>&1; then curl -fsS -o /dev/null "$1"; elif command -v wget >/dev/null 2>&1; then wget -q -O /dev/null "$1"; else return 2; fi; }
rc=0; fetch "$health" 2>/dev/null || rc=$?
if [ "$rc" -eq 2 ]; then
  say "(ni curl ni wget : attente de la santé ignorée ; vérifie avec 'docker compose ps')"
  ok=1
else
  i=0
  while [ "$i" -lt "$TRIES" ]; do
    if fetch "$health" 2>/dev/null; then ok=1; break; fi
    i=$((i + 1)); sleep "$PAUSE"
  done
fi
[ -n "$ok" ] || { dcf ps >&2 || true; die "Kaji ne répond pas sur $health après 2 minutes. Journal : 'cd $DIR && docker compose $COMPOSE_ARGS logs backend'."; }
say "Kaji répond."

CERT=""
if [ -n "$TLS" ]; then
  i=0
  while [ "$i" -lt "$TRIES" ]; do
    if dcf cp tls:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt >/dev/null 2>&1; then CERT=1; break; fi
    i=$((i + 1)); sleep "$PAUSE"
  done
  [ -n "$CERT" ] && say "Certificat de Caddy copié : $DIR/caddy-root.crt" || say "(certificat de Caddy pas encore disponible : relance la commande 'cp' de docs/installation-lab.md § 5)"
fi

SITE=$(sed -n 's/^KAJI_TLS_SITE=//p' .env | tail -n 1)
say ""
say "==================== Kaji est installé ===================="
if [ -n "$TLS" ]; then
  say "Adresse (HTTPS)    : https://$SITE"
  say "Certificat         : installe $DIR/caddy-root.crt comme autorité de confiance sur TON poste"
  say "                     (copie : scp $(id -un)@$SITE:$DIR/caddy-root.crt .  ; marche à suivre : docs/installation-lab.md § 5)"
else
  say "Adresse (locale)   : http://127.0.0.1:$PORT   (depuis un autre poste : ssh -L $PORT:127.0.0.1:$PORT <utilisateur>@<cette machine>)"
fi
if [ -n "$NEW_ENV" ]; then
  say "Jeton de première configuration (à saisir UNE fois pour créer le compte administrateur) :"
  say "    $SETUP_TOKEN"
  say "La clé KAJI_SECRET_KEY est dans $DIR/.env : sauvegarde ce fichier à part (docs/installation-lab.md § 7). Elle n'est pas affichée ici."
else
  say "Kaji a été mis à jour. .env et données conservés."
fi
say ""
say "Suite : crée l'utilisateur et le jeton dans Proxmox (lecture seule), sur un nœud, en root :"
say "    sh $DIR/tools/proxmox-setup.sh        (ou voir docs/installation-lab.md § 2)"
say "puis, dans Kaji, page « Connexions » : ajoute ton cluster avec ce jeton."
