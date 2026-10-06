#!/usr/bin/env bash
# Affiche les URLs publiques et les identifiants générés du POC (lus dans les Secrets du cluster).
#
# Usage : bin/get-secrets.sh [grafana|keep|all]     (défaut : all)
# Prérequis : kubectl joint le cluster (make kubeconfig, ou make tunnel + make kubeconfig-iap).
set -euo pipefail

TARGET="${1:-all}"

# secret <namespace> <nom> <clé> : valeur décodée, ou vide si le Secret n'existe pas encore
secret() {
  kubectl -n "$1" get secret "$2" -o "jsonpath={.data.$3}" 2>/dev/null | base64 -d || true
}

# host <namespace> <ingress> : premier hôte de l'Ingress
host() {
  kubectl -n "$1" get ingress "$2" -o 'jsonpath={.spec.rules[0].host}' 2>/dev/null || true
}

show() { # <titre> <namespace> <ingress> <utilisateur> <valeur> <aide si absent>
  local title="$1" url="$3" user="$4" value="$5" missing="$6"
  url="$(host "$2" "$url")"
  printf '%s\n' "$title"
  if [[ -n "$url" ]]; then
    printf '  URL          : https://%s\n' "$url"
  else
    printf '  URL          : (Ingress introuvable, Flux n a pas encore déployé ce composant)\n'
  fi
  printf '  Utilisateur  : %s\n' "$user"
  if [[ -n "$value" ]]; then
    printf '  Mot de passe : %s\n' "$value"
  else
    printf '  Mot de passe : (introuvable) %s\n' "$missing"
  fi
}

case "$TARGET" in grafana | keep | all) ;; *)
  echo "Usage : $0 [grafana|keep|all]" >&2
  exit 1
  ;;
esac

if [[ "$TARGET" == grafana || "$TARGET" == all ]]; then
  show "Grafana" monitoring kube-prometheus-stack-grafana admin \
    "$(secret monitoring kube-prometheus-stack-grafana admin-password)" \
    "Grafana n est pas encore déployé (kubectl get helmrelease -A)."
fi

if [[ "$TARGET" == keep || "$TARGET" == all ]]; then
  [[ "$TARGET" == all ]] && echo
  show "Keep" keep keep admin \
    "$(secret keep keep-backend-auth KEEP_DEFAULT_PASSWORD)" \
    "Lancer make keep-secrets."
fi
