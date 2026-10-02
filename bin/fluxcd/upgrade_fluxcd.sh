#!/bin/bash
# Met à jour les composants FluxCD : mettre à jour la CLI flux, puis lancer ce script.
set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

flux install --export > "$ROOT_DIR/manifest/flux-system/gotk-components.yaml"
git -C "$ROOT_DIR" add manifest/flux-system/gotk-components.yaml
git -C "$ROOT_DIR" commit -m "feat(fluxcd): Update $(flux -v) on k3s"
