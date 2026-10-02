#!/usr/bin/env bash
# Récupère le kubeconfig du cluster k3s et l'écrit dans .kube/config (local au repo).
#
# Usage :
#   scripts/get-kubeconfig.sh          # API joignable directement sur l'IP publique
#                                      # (nécessite admin_source_ranges dans Terraform)
#   scripts/get-kubeconfig.sh --iap    # API via tunnel IAP sur localhost:6443
#                                      # (lancer ensuite : make tunnel)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-$ROOT_DIR/infra/gcp-k3s}"
OUT="${KUBECONFIG_OUT:-$ROOT_DIR/.kube/config}"
MODE="direct"
[[ "${1:-}" == "--iap" ]] && MODE="iap"

tf_out() { terraform -chdir="$TF_DIR" output -raw "$1"; }

PROJECT="$(tf_out project_id)"
ZONE="$(tf_out zone)"
INSTANCE="$(tf_out instance_name)"
EXTERNAL_IP="$(tf_out external_ip)"

if [[ "$MODE" == "iap" ]]; then
  SERVER="https://127.0.0.1:6443"
else
  SERVER="https://${EXTERNAL_IP}:6443"
fi

mkdir -p "$(dirname "$OUT")"
umask 077

echo "Lecture du kubeconfig sur $INSTANCE ($ZONE)..." >&2
gcloud compute ssh "$INSTANCE" \
  --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
  --command "sudo cat /etc/rancher/k3s/k3s.yaml" \
  | sed -e "s#https://127.0.0.1:6443#${SERVER}#" \
        -e "s#: default\$#: ai4ops#" > "$OUT"

echo "Kubeconfig écrit dans $OUT (server: $SERVER)" >&2
echo "  export KUBECONFIG=$OUT" >&2
