#!/bin/bash
# Installation initiale (one-shot) de FluxCD sur le cluster k3s.
#
# Usage : bin/fluxcd/bootstrap.sh <cle-privee-deploy-key> <age.agekey>
#
#   <cle-privee-deploy-key> : clé SSH dont la partie publique est déclarée en
#                             "Deploy key" (lecture seule) sur le repo GitHub
#   <age.agekey>            : clé privée age utilisée par SOPS (cf. .sops.yaml)
#
# Variables optionnelles : FLUX_KEY_PASSWORD (si la clé SSH est chiffrée), GIT_URL.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FLUX_DIR="$ROOT_DIR/manifest/flux-system"
GIT_URL="${GIT_URL:-ssh://git@github.com/FabianCh/poc-ai4ops}"

if [[ $# -ne 2 ]]; then
  sed -n '2,11p' "$0"
  exit 1
fi
PRIVATE_KEY="$1"
AGE_KEY="$2"

kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -

echo "Secret Git flux-system ($GIT_URL)"
flux create secret git flux-system \
  --url="$GIT_URL" \
  --private-key-file="$PRIVATE_KEY" \
  ${FLUX_KEY_PASSWORD:+--password="$FLUX_KEY_PASSWORD"}

echo "Secret SOPS sops-age"
kubectl -n flux-system create secret generic sops-age \
  --from-file=age.agekey="$AGE_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Installation des contrôleurs Flux"
kubectl apply --server-side -f "$FLUX_DIR/gotk-components.yaml"
kubectl -n flux-system wait --for=condition=Available deployment --all --timeout=5m

echo "Synchronisation avec le repo"
kubectl apply --server-side -k "$FLUX_DIR"

flux check
echo "Suivi : flux get kustomizations --watch"
