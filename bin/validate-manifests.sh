#!/bin/bash
# Construit chaque kustomization de manifest/ et valide le résultat avec kubeconform
# (schémas Kubernetes + CRDs Flux / cert-manager du catalogue datreeio).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRDS_CATALOG='https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

find "$ROOT_DIR/manifest" -name kustomization.yaml -print0 | sort -z | while IFS= read -r -d '' file; do
  dir="$(dirname "$file")"
  echo "--- ${dir#"$ROOT_DIR"/}"
  kustomize build "$dir" \
    | kubeconform -strict -summary \
        -schema-location default -schema-location "$CRDS_CATALOG" \
        -skip CustomResourceDefinition
done
