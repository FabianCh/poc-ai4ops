#!/usr/bin/env bash
# Déploie l'application de démo exposée sur Internet :
#   https://whoami.<IP>.sslip.io
#
# Usage : scripts/deploy-demo.sh [letsencrypt-prod|letsencrypt-staging]
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-$ROOT_DIR/infra/gcp-k3s}"
ISSUER="${1:-letsencrypt-prod}"

BASE_DOMAIN="$(terraform -chdir="$TF_DIR" output -raw ingress_base_domain)"
HOST="whoami.${BASE_DOMAIN}"

sed -e "s#__HOST__#${HOST}#g" -e "s#__CLUSTER_ISSUER__#${ISSUER}#g" \
  "$ROOT_DIR/apps/demo-whoami/manifest.yaml" \
  | kubectl apply -f -

kubectl -n demo rollout status deploy/whoami --timeout=120s

echo
echo "HTTP  : http://${HOST}"
echo "HTTPS : https://${HOST}  (certificat émis par ${ISSUER} sous 1 à 2 minutes)"
echo "Suivi : kubectl -n demo get certificate,ingress"
