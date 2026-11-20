#!/bin/sh
# Crée le conteneur de Kaji depuis un NŒUD Proxmox, y installe Docker et Kaji : une commande, en root sur le nœud.
#   sh proxmox-create-ct.sh [options]
#
# Ce que fait le script (relis-le avant de le lancer ; --dry-run affiche tout sans rien faire) :
#   1. choisit un identifiant LIBRE (pvesh get /cluster/nextid) et REFUSE un identifiant déjà pris par une VM ou un conteneur ;
#   2. télécharge le modèle Debian 12 s'il manque ;
#   3. crée un conteneur LXC non privilégié (options nesting et keyctl, nécessaires à Docker) et le démarre ;
#   4. y installe curl et git, télécharge install.sh (le script d'installation express) et le lance ;
#   5. affiche l'adresse de Kaji et le jeton de première configuration (sortie d'install.sh).
# Il ne touche à AUCUN conteneur ni VM existant. Si la création ou le démarrage échoue, le conteneur qu'il vient de créer est détruit ;
# une fois l'installation de Kaji commencée, le conteneur est GARDÉ (pour lire les journaux) et la commande pour le supprimer est affichée.
# Docker dans un conteneur non privilégié marche en général sur Proxmox VE 8 et 9, mais peut échouer selon le noyau ou AppArmor ;
# en cas d'échec, utilise plutôt une VM Debian (docs/installation-lab.md § 1.1).
#
# Options :
#   --vmid N          identifiant du conteneur (défaut : le prochain libre)
#   --name NOM        nom d'hôte (défaut : kaji)
#   --storage S       stockage du disque (défaut : le premier actif qui accepte les conteneurs)
#   --template-storage S  stockage des modèles (défaut : local)
#   --bridge B        pont réseau (défaut : vmbr0)
#   --ip dhcp|CIDR    adresse du conteneur (défaut : dhcp ; ex. 192.168.1.50/24, avec --gw)
#   --gw ADRESSE      passerelle (obligatoire avec une adresse fixe)
#   --cores N         cœurs (défaut : 2)    --memory MO  mémoire (défaut : 2048)    --disk GO  disque (défaut : 16)
#   --pool POOL       pool Proxmox où ranger le conteneur
#   --address ADR     adresse par laquelle on ouvrira Kaji (défaut : l'adresse du conteneur) ; --local : accès local seulement
#   --ref ETIQUETTE   version de Kaji ; --image : utiliser les images publiées
#   --yes             ne pas demander confirmation          --dry-run   afficher sans rien faire
set -eu

VMID=""; NAME="kaji"; STORAGE=""; TSTORE="local"; BRIDGE="vmbr0"; IPCFG="dhcp"; GW=""
CORES=2; MEMORY=2048; DISK=16; POOL=""; ADDRESS=""; LOCALONLY=""; REF=""; IMAGE=""; YES=""; DRY=""
INSTALL_URL="https://raw.githubusercontent.com/Ek8Oxilive/kaji/main/install.sh"

die() { printf 'ERREUR : %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }
need() { [ $# -ge 2 ] || die "$1 demande une valeur"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --vmid) need "$@"; VMID=$2; shift 2 ;;
    --name) need "$@"; NAME=$2; shift 2 ;;
    --storage) need "$@"; STORAGE=$2; shift 2 ;;
    --template-storage) need "$@"; TSTORE=$2; shift 2 ;;
    --bridge) need "$@"; BRIDGE=$2; shift 2 ;;
    --ip) need "$@"; IPCFG=$2; shift 2 ;;
    --gw) need "$@"; GW=$2; shift 2 ;;
    --cores) need "$@"; CORES=$2; shift 2 ;;
    --memory) need "$@"; MEMORY=$2; shift 2 ;;
    --disk) need "$@"; DISK=$2; shift 2 ;;
    --pool) need "$@"; POOL=$2; shift 2 ;;
    --address) need "$@"; ADDRESS=$2; shift 2 ;;
    --local) LOCALONLY=1; shift ;;
    --ref) need "$@"; REF=$2; shift 2 ;;
    --image) IMAGE=1; shift ;;
    --yes|-y) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) die "option inconnue : $1 (voir --help)" ;;
  esac
done

# --- validations : tout est contrôlé AVANT la première commande ------------------------------------------------------
num() { case "$2" in ""|*[!0-9]*) die "$1 doit être un nombre entier" ;; esac; }
word() { case "$2" in ""|*[!A-Za-z0-9._-]*|-*) die "$1 invalide (lettres, chiffres, point, tiret, souligné)" ;; esac; }
[ -z "$VMID" ] || { num --vmid "$VMID"; [ "$VMID" -ge 100 ] && [ "$VMID" -le 999999999 ] || die "--vmid doit valoir au moins 100"; }
case "$NAME" in ""|*[!A-Za-z0-9-]*|-*|*-) die "--name invalide (lettres, chiffres et tirets ; pas de tiret au début ni à la fin)" ;; esac
word --template-storage "$TSTORE"; word --bridge "$BRIDGE"
[ -z "$STORAGE" ] || word --storage "$STORAGE"
[ -z "$POOL" ] || word --pool "$POOL"
num --cores "$CORES"; num --memory "$MEMORY"; num --disk "$DISK"
[ "$CORES" -ge 1 ] && [ "$CORES" -le 64 ] || die "--cores entre 1 et 64"
[ "$MEMORY" -ge 1024 ] && [ "$MEMORY" -le 262144 ] || die "--memory entre 1024 et 262144 (Mo) : Docker et la construction demandent au moins 1 Go"
[ "$DISK" -ge 8 ] && [ "$DISK" -le 4096 ] || die "--disk entre 8 et 4096 (Go)"
ipv4() {
  case "$1" in ""|*[!0-9.]*|*..*|.*|*.) return 1 ;; esac
  [ "$(printf '%s' "$1" | tr -cd . | wc -c)" -eq 3 ] || return 1
  old=$IFS; IFS=.; set -- $1; IFS=$old
  for o in "$@"; do [ "$o" -le 255 ] || return 1; done
}
if [ "$IPCFG" != "dhcp" ]; then
  case "$IPCFG" in */*) ;; *) die "--ip : « dhcp » ou une adresse avec son masque (ex. 192.168.1.50/24)" ;; esac
  ipv4 "${IPCFG%/*}" || die "--ip : adresse IPv4 invalide"
  num "masque de --ip" "${IPCFG#*/}"; [ "${IPCFG#*/}" -ge 1 ] && [ "${IPCFG#*/}" -le 32 ] || die "--ip : masque entre 1 et 32"
  [ -n "$GW" ] || die "--gw est obligatoire avec une adresse fixe"
  ipv4 "$GW" || die "--gw : adresse IPv4 invalide"
else
  [ -z "$GW" ] || die "--gw n'a de sens qu'avec une adresse fixe"
fi
case "$ADDRESS" in *[!A-Za-z0-9.-]*|.*|-*|*.|*-) die "--address invalide (lettres, chiffres, points et tirets ; sans port)" ;; esac
[ -z "$ADDRESS" ] || [ -z "$LOCALONLY" ] || die "--address et --local s'excluent"
case "$REF" in *[!A-Za-z0-9._/-]*) die "--ref invalide" ;; esac

[ -n "$DRY" ] || [ "$(id -u)" -eq 0 ] || die "à lancer en root sur un nœud Proxmox."
for c in pct pvesh pveam pvesm; do command -v "$c" >/dev/null 2>&1 || die "$c est introuvable : ce script se lance sur un nœud Proxmox VE."; done

# --- choix des valeurs libres ----------------------------------------------------------------------------------------
if [ -z "$VMID" ]; then
  VMID=$(pvesh get /cluster/nextid 2>/dev/null | tr -d '"[:space:]') || VMID=""
  num "identifiant libre trouvé par Proxmox" "$VMID"
fi
if pct status "$VMID" >/dev/null 2>&1 || { command -v qm >/dev/null 2>&1 && qm status "$VMID" >/dev/null 2>&1; }; then
  die "l'identifiant $VMID est déjà utilisé par une VM ou un conteneur : je n'y touche pas. Choisis-en un autre (--vmid)."
fi
if [ -z "$STORAGE" ]; then
  STORAGE=$(pvesm status --content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}') || STORAGE=""
  [ -n "$STORAGE" ] || die "aucun stockage actif n'accepte les conteneurs : indique-en un avec --storage."
fi
TEMPLATE=$(pveam list "$TSTORE" 2>/dev/null | awk 'NR>1 {n=split($1,a,"/"); print a[n]}' | grep '^debian-12-standard_' | sort -V | tail -n 1) || TEMPLATE=""
NEED_DL=""
if [ -z "$TEMPLATE" ]; then
  TEMPLATE=$(pveam available --section system 2>/dev/null | awk '{print $2}' | grep '^debian-12-standard_' | sort -V | tail -n 1) || TEMPLATE=""
  [ -n "$TEMPLATE" ] || die "aucun modèle Debian 12 trouvé (pveam update, puis réessaie ; ou télécharge-le dans l'interface)."
  NEED_DL=1
fi
case "$TEMPLATE" in *[!A-Za-z0-9._-]*) die "nom de modèle inattendu" ;; esac

NET="name=eth0,bridge=$BRIDGE,ip=$IPCFG"
[ "$IPCFG" = "dhcp" ] || NET="$NET,gw=$GW"
POOL_OPT=""; [ -z "$POOL" ] || POOL_OPT="--pool $POOL"

say "Je vais créer sur ce nœud :"
say "  conteneur $VMID « $NAME » : Debian 12, $CORES cœur(s), $MEMORY Mo, disque $DISK Go sur $STORAGE, réseau $BRIDGE ($IPCFG)${POOL:+, pool $POOL}"
say "  non privilégié, options nesting + keyctl (Docker), démarrage automatique"
[ -z "$NEED_DL" ] || say "  après avoir téléchargé le modèle $TEMPLATE dans $TSTORE"
say "  puis y installer Docker et Kaji (install.sh, depuis $INSTALL_URL)"

if [ -n "$DRY" ]; then
  say ""; say "(simulation) commandes qui seraient lancées :"
  [ -z "$NEED_DL" ] || say "  pveam download $TSTORE $TEMPLATE"
  say "  pct create $VMID $TSTORE:vztmpl/$TEMPLATE --hostname $NAME --cores $CORES --memory $MEMORY --swap 512 --rootfs $STORAGE:$DISK --net0 $NET --unprivileged 1 --features nesting=1,keyctl=1 --onboot 1 --tags kaji $POOL_OPT"
  say "  pct start $VMID"
  say "  pct exec $VMID -- ...  (apt-get install curl git ; curl -fsSL $INSTALL_URL -o /root/install.sh ; sh /root/install.sh --yes ...)"
  exit 0
fi

if [ -z "$YES" ]; then
  printf 'Continuer ? [o/N] : '
  ans=""; read -r ans || ans=""
  case "$ans" in o|O|oui|OUI|y|Y|yes) ;; *) die "annulé : rien n'a été créé." ;; esac
fi

CREATED=""
cleanup_failed() {  # uniquement le conteneur créé par CE script, et seulement avant l'installation de Kaji
  [ -n "$CREATED" ] || return 0
  pct stop "$VMID" >/dev/null 2>&1 || true
  pct destroy "$VMID" --purge >/dev/null 2>&1 || true
}
fail() { cleanup_failed; die "$1 Le conteneur $VMID que le script venait de créer a été supprimé."; }

[ -z "$NEED_DL" ] || pveam download "$TSTORE" "$TEMPLATE" || die "téléchargement du modèle impossible."
# shellcheck disable=SC2086
pct create "$VMID" "$TSTORE:vztmpl/$TEMPLATE" --hostname "$NAME" --cores "$CORES" --memory "$MEMORY" --swap 512 --rootfs "$STORAGE:$DISK" --net0 "$NET" \
  --unprivileged 1 --features nesting=1,keyctl=1 --onboot 1 --tags kaji $POOL_OPT || die "création du conteneur impossible (rien à supprimer)."
CREATED=1
pct start "$VMID" || fail "démarrage du conteneur impossible."

say "Attente du réseau du conteneur…"
TRIES=${KAJI_CT_TRIES:-30}; PAUSE=${KAJI_CT_PAUSE:-2}
i=0; up=""
while [ "$i" -lt "$TRIES" ]; do
  if pct exec "$VMID" -- sh -c 'getent hosts deb.debian.org >/dev/null 2>&1'; then up=1; break; fi
  i=$((i + 1)); sleep "$PAUSE"
done
[ -n "$up" ] || fail "le conteneur n'a pas d'accès réseau (pont, DHCP, passerelle ou DNS ?)."

CT_IP=$(pct exec "$VMID" -- sh -c "hostname -I | awk '{print \$1}'" 2>/dev/null | tr -d '[:space:]') || CT_IP=""
[ -z "$LOCALONLY" ] && [ -z "$ADDRESS" ] && ADDRESS=$CT_IP
[ -n "$LOCALONLY" ] || [ -n "$ADDRESS" ] || fail "adresse du conteneur introuvable."

pct exec "$VMID" -- sh -c 'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates git' || fail "installation de curl et git impossible dans le conteneur."
pct exec "$VMID" -- sh -c "curl -fsSL '$INSTALL_URL' -o /root/install.sh" || fail "téléchargement d'install.sh impossible."

OPTS="--yes"
[ -z "$LOCALONLY" ] || OPTS="$OPTS --local"
[ -n "$LOCALONLY" ] || OPTS="$OPTS --address $ADDRESS"
[ -z "$REF" ] || OPTS="$OPTS --ref $REF"
[ -z "$IMAGE" ] || OPTS="$OPTS --image"
CREATED=""     # à partir d'ici le conteneur est GARDÉ, même si l'installation de Kaji échoue (journaux à lire)
say "Installation de Kaji dans le conteneur $VMID (quelques minutes) :"
if ! pct exec "$VMID" -- sh -c "sh /root/install.sh $OPTS"; then
  say "" >&2
  die "l'installation de Kaji a échoué dans le conteneur $VMID, qui est CONSERVÉ pour lire les journaux : pct enter $VMID. Pour le supprimer : pct stop $VMID; pct destroy $VMID --purge"
fi

say ""
say "Conteneur Kaji prêt : identifiant $VMID, adresse ${ADDRESS:-locale}."
say "Pour y entrer : pct enter $VMID    (Kaji est dans /root/kaji ; mise à jour : sh /root/install.sh --yes ${ADDRESS:+--address $ADDRESS})"
say "Suite : crée l'utilisateur et le jeton dans Proxmox (lecture seule) avec tools/proxmox-setup.sh, puis ajoute le cluster dans Kaji."
