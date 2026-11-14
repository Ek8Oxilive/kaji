#!/bin/sh
# Vérifie une version signée de Kaji (jalon J4, ticket #458, docs/signature.md) :
#
#   tools/verify_release.sh kaji-v1.0.0.tar.gz [dépôt]        (défaut : Ek8Oxilive/kaji)
#
# Il faut dans le même dossier : l'archive, `<archive>.sha256` et `<archive>.sigstore.json` (joints à la release GitHub, ou artefacts du workflow « Signature des versions »).
# 1. la somme SHA-256 correspond ; 2. la signature Sigstore est valide ET l'identité qui a signé est le workflow de ce dépôt (pas une autre personne, pas un autre dépôt).
# Besoin : sha256sum et cosign (https://docs.sigstore.dev/cosign/). Code de sortie : 0 = version authentique, 1 = refusée, 2 = usage ou outil manquant.
set -eu
ARCHIVE=${1:-}
REPO=${2:-Ek8Oxilive/kaji}
[ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ] || { echo "usage : $0 ARCHIVE.tar.gz [dépôt]" >&2; exit 2; }
command -v sha256sum >/dev/null && command -v cosign >/dev/null || { echo "sha256sum et cosign sont nécessaires" >&2; exit 2; }
case "$REPO" in *[!A-Za-z0-9._/-]*|"") echo "nom de dépôt invalide" >&2; exit 2 ;; esac
DIR=$(dirname "$ARCHIVE"); BASE=$(basename "$ARCHIVE")
[ -f "$DIR/$BASE.sha256" ] && [ -f "$DIR/$BASE.sigstore.json" ] || { echo "il manque $BASE.sha256 ou $BASE.sigstore.json à côté de l'archive" >&2; exit 2; }
(cd "$DIR" && sha256sum -c "$BASE.sha256") || { echo "REFUSÉE : la somme SHA-256 ne correspond pas." >&2; exit 1; }
ESCAPED=$(printf '%s' "$REPO" | sed 's/\./\\./g')
cosign verify-blob --bundle "$DIR/$BASE.sigstore.json" \
  --certificate-identity-regexp "^https://github.com/${ESCAPED}/\.github/workflows/release-sign\.yml@" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  "$ARCHIVE" || { echo "REFUSÉE : la signature n'est pas valide ou n'a pas été faite par le workflow de $REPO." >&2; exit 1; }
echo "AUTHENTIQUE : $BASE est bien l'archive des sources signée par le workflow « Signature des versions » de $REPO."
