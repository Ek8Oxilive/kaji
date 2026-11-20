#!/bin/sh
# Prépare Proxmox pour Kaji : un utilisateur, un jeton à privilèges séparés et les droits de LECTURE SEULE (PVEAuditor), en une commande.
# À lancer sur un NŒUD Proxmox, en root :   sh proxmox-setup.sh
#
# Ce que fait le script (les mêmes trois commandes que docs/installation-lab.md § 2, sans erreur de recopie) :
#   1. crée l'utilisateur kaji@pve (s'il n'existe pas déjà) ;
#   2. crée le jeton « kaji » avec séparation de privilèges ET une date d'expiration ;
#   3. donne le rôle PVEAuditor sur / à l'utilisateur ET au jeton (avec la séparation des privilèges, les droits du jeton sont l'intersection des deux) ;
#   4. affiche le secret du jeton UNE SEULE FOIS, avec les valeurs à saisir dans la page « Connexions » de Kaji et l'empreinte du certificat à comparer.
# Jamais Administrator. Jamais root@pam. Un jeton ou un rôle qui existe déjà n'est JAMAIS écrasé : le script s'arrête et le dit.
# Si une étape échoue après la création du jeton, ce que le script vient de créer est retiré.
#
# Options :
#   --user  COMPTE   compte Proxmox de Kaji (défaut : kaji@pve ; jamais root@pam)
#   --token ID       identifiant du jeton (défaut : kaji)
#   --days  N        validité du jeton en jours, 1 à 3650 (défaut : 365)
#   --yes            ne pas demander confirmation
#   --dry-run        afficher les commandes sans rien exécuter
# Pour donner plus de droits ensuite (démarrer des machines, snapshots…) : page « Accès » de Kaji, qui affiche les commandes à copier.
set -eu

PVE_USER="kaji@pve"
TOKEN_ID="kaji"
DAYS=365
YES=""
DRY=""

die() { printf 'ERREUR : %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --user)  [ $# -ge 2 ] || die "--user demande un compte"; PVE_USER=$2; shift 2 ;;
    --token) [ $# -ge 2 ] || die "--token demande un identifiant"; TOKEN_ID=$2; shift 2 ;;
    --days)  [ $# -ge 2 ] || die "--days demande un nombre"; DAYS=$2; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) die "option inconnue : $1 (voir --help)" ;;
  esac
done

# Valeurs validées AVANT toute commande : ni espace, ni guillemet, ni caractère que le shell ou Proxmox interpréterait.
case "$PVE_USER" in *@*) ;; *) die "compte invalide : il doit s'écrire nom@realm (ex. kaji@pve)" ;; esac
NAME=${PVE_USER%@*}; REALM=${PVE_USER#*@}
case "$NAME" in ""|*[!A-Za-z0-9._-]*) die "nom de compte invalide (lettres, chiffres, point, tiret, souligné)" ;; esac
case "$REALM" in ""|*[!A-Za-z0-9]*) die "realm invalide (lettres et chiffres seulement)" ;; esac
[ "$PVE_USER" != "root@pam" ] || die "jamais root@pam : Kaji n'a pas besoin du compte administrateur de Proxmox."
case "$TOKEN_ID" in ""|[!A-Za-z]*|*[!A-Za-z0-9._-]*) die "identifiant de jeton invalide (commence par une lettre ; lettres, chiffres, point, tiret, souligné)" ;; esac
case "$DAYS" in ""|*[!0-9]*) die "--days doit être un nombre entier" ;; esac
[ "$DAYS" -ge 1 ] && [ "$DAYS" -le 3650 ] || die "--days doit être compris entre 1 et 3650"

[ -n "$DRY" ] || [ "$(id -u)" -eq 0 ] || die "à lancer en root sur un nœud Proxmox."
command -v pveum >/dev/null 2>&1 || die "pveum est introuvable : ce script se lance sur un nœud Proxmox VE, pas sur la machine de Kaji."

FULL="$PVE_USER!$TOKEN_ID"
EXPIRE=$(date -d "+$DAYS days" +%s) || die "impossible de calculer la date d'expiration."

if [ -n "$DRY" ]; then
  say "(simulation) commandes qui seraient lancées :"
  say "  pveum user add $PVE_USER --comment 'Kaji (interface web)'            # seulement si le compte n'existe pas"
  say "  pveum user token add $PVE_USER $TOKEN_ID --privsep 1 --expire $EXPIRE --comment 'jeton de Kaji'"
  say "  pveum acl modify / --roles PVEAuditor --users '$PVE_USER' --tokens '$FULL'"
  exit 0
fi

USER_EXISTS=""
if pveum user list --output-format json 2>/dev/null | grep -q "\"userid\":\"$PVE_USER\""; then USER_EXISTS=1; fi
if [ -n "$USER_EXISTS" ] && pveum user token list "$PVE_USER" --output-format json 2>/dev/null | grep -q "\"tokenid\":\"$TOKEN_ID\""; then
  die "le jeton $FULL existe déjà : je ne l'écrase pas (son secret est introuvable). Choisis un autre identifiant (--token) ou supprime-le toi-même : pveum user token remove $PVE_USER $TOKEN_ID"
fi

say "Je vais créer, sur ce nœud :"
[ -n "$USER_EXISTS" ] && say "  - (le compte $PVE_USER existe déjà : réutilisé)" || say "  - le compte $PVE_USER"
say "  - le jeton $FULL (privilèges séparés, expire dans $DAYS jours)"
say "  - le rôle PVEAuditor (lecture seule) sur /, pour le compte ET pour le jeton"
if [ -z "$YES" ]; then
  printf 'Continuer ? [o/N] : '
  ans=""; read -r ans || ans=""
  case "$ans" in o|O|oui|OUI|y|Y|yes) ;; *) die "annulé : rien n'a été créé." ;; esac
fi

CREATED_USER=""; CREATED_TOKEN=""
rollback() {
  [ -z "$CREATED_TOKEN" ] || pveum user token remove "$PVE_USER" "$TOKEN_ID" >/dev/null 2>&1 || true
  [ -z "$CREATED_USER" ] || pveum user delete "$PVE_USER" >/dev/null 2>&1 || true
}
fail() { rollback; die "$1 Ce que le script venait de créer a été retiré."; }

if [ -z "$USER_EXISTS" ]; then
  pveum user add "$PVE_USER" --comment "Kaji (interface web)" >/dev/null || die "création du compte impossible."
  CREATED_USER=1
fi
out=$(pveum user token add "$PVE_USER" "$TOKEN_ID" --privsep 1 --expire "$EXPIRE" --comment "jeton de Kaji" --output-format json 2>/dev/null) || fail "création du jeton impossible."
CREATED_TOKEN=1
SECRET=$(printf '%s' "$out" | sed -n 's/.*"value":"\([^"]*\)".*/\1/p')
out=""
[ -n "$SECRET" ] || fail "le secret du jeton n'a pas pu être lu."
pveum acl modify / --roles PVEAuditor --users "$PVE_USER" --tokens "$FULL" >/dev/null 2>&1 || fail "attribution des droits impossible."

HOST=$(hostname -I 2>/dev/null | awk '{print $1}') || HOST=""
FP=$(openssl x509 -noout -fingerprint -sha256 -in /etc/pve/local/pve-ssl.pem 2>/dev/null | sed 's/^.*=//') || FP=""
say ""
say "==================== Prêt : à saisir dans Kaji (page « Connexions ») ===================="
say "  Hôte               : ${HOST:-<adresse de ce nœud>}"
say "  Port               : 8006"
say "  Utilisateur        : $PVE_USER"
say "  ID du token        : $TOKEN_ID"
say "  Secret du token    : $SECRET"
say "  Expire dans        : $DAYS jours (à renouveler avant)"
[ -z "$FP" ] || say "  Empreinte SHA-256 du certificat de ce nœud (à comparer quand Kaji propose d'épingler) :
    $FP"
say ""
say "LE SECRET N'EST AFFICHÉ QU'UNE FOIS : copie-le maintenant dans ton gestionnaire de mots de passe."
say "Ne le colle ni dans un chat, ni dans un fichier du dépôt, ni dans un ticket."
say "Droits donnés : lecture seule (PVEAuditor). Pour démarrer des machines, faire des snapshots, etc. : page « Accès » de Kaji (commandes à copier)."
