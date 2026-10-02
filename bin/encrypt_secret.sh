#!/bin/bash
# Chiffre un Secret Kubernetes pour FluxCD (règles dans .sops.yaml) :
# https://fluxcd.io/flux/guides/mozilla-sops/#encrypting-secrets-using-age
set -eu

sops --encrypt --in-place "$1"
