#!/bin/bash
# Déchiffre un Secret Kubernetes en place (inspection / édition locale).
# Nécessite la clé privée age : export SOPS_AGE_KEY_FILE=./age.agekey
set -eu

sops --decrypt --in-place "$1"
