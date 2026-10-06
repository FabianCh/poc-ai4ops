#!/usr/bin/env bash
# run_local.sh — Démarre l'agent IA4Ops en local avec les providers mockés.
#
# Usage :
#   bash scripts/run_local.sh              # mode mock (défaut)
#   bash scripts/run_local.sh --reload     # mode watch (développement)
#   LLM_PROVIDER=gemini bash scripts/run_local.sh  # mode Gemini (prod)
#
# Prérequis :
#   - uv installé (https://docs.astral.sh/uv/)
#   - Environnement virtuel initialisé : uv sync
#   - Fichier .env présent (copier depuis .env.example)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Charger .env si présent
if [[ -f "${PROJECT_DIR}/.env" ]]; then
  echo "→ Chargement de ${PROJECT_DIR}/.env"
  set -a
  # shellcheck disable=SC1090
  source "${PROJECT_DIR}/.env"
  set +a
else
  echo "⚠  Pas de fichier .env trouvé — variables d'environnement système utilisées"
  echo "   (copier .env.example vers .env pour personnaliser)"
fi

# Valeurs par défaut
export LLM_PROVIDER="${LLM_PROVIDER:-mock}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8000}"
export AUDIT_DIR="${AUDIT_DIR:-audit_logs}"

# Créer le dossier audit_logs si nécessaire
mkdir -p "${PROJECT_DIR}/${AUDIT_DIR}"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║         IA4Ops Agent — Local Dev          ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  LLM_PROVIDER : ${LLM_PROVIDER}"
echo "  HOST:PORT    : ${HOST}:${PORT}"
echo "  AUDIT_DIR    : ${AUDIT_DIR}"
echo ""
echo "  Endpoints :"
echo "  POST http://${HOST}:${PORT}/webhooks/alertmanager"
echo "  GET  http://${HOST}:${PORT}/api/v1/incidents/{id}"
echo "  GET  http://${HOST}:${PORT}/health"
echo "  GET  http://${HOST}:${PORT}/docs"
echo ""

# Vérifier la présence des credentials Gemini si mode gemini
if [[ "${LLM_PROVIDER}" == "gemini" ]]; then
  if [[ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
    echo "⚠  LLM_PROVIDER=gemini mais GOOGLE_APPLICATION_CREDENTIALS n'est pas défini"
    echo "   Voir .env.example pour les variables requises"
    exit 1
  fi
  if [[ ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
    echo "⚠  Fichier credentials introuvable : ${GOOGLE_APPLICATION_CREDENTIALS}"
    exit 1
  fi
  echo "  Credentials GCP : ${GOOGLE_APPLICATION_CREDENTIALS}"
  echo ""
fi

# Mode rechargement (développement)
RELOAD_FLAG=""
if [[ "${1:-}" == "--reload" ]]; then
  RELOAD_FLAG="--reload"
  echo "→ Mode rechargement activé (--reload)"
fi

echo "→ Démarrage du serveur..."
echo ""

cd "${PROJECT_DIR}"
exec uv run uvicorn ia4ops_agent.main:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --log-level info \
  ${RELOAD_FLAG}
