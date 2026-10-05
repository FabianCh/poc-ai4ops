#!/usr/bin/env bash
# send_test_alert.sh — Envoie un payload Alertmanager v4 simulé à l'agent local.
#
# Usage :
#   bash scripts/send_test_alert.sh case_a          # product-catalog (timeout Redis)
#   bash scripts/send_test_alert.sh case_b          # checkout (OOMKilled)
#   bash scripts/send_test_alert.sh case_c          # frontend (données insuffisantes)
#   bash scripts/send_test_alert.sh watchdog        # heartbeat Alertmanager
#
# Variables d'environnement :
#   AGENT_URL   URL de base de l'agent (défaut : http://localhost:8000)
#
# Prérequis : curl, jq (optionnel pour pretty-print)

set -euo pipefail

AGENT_URL="${AGENT_URL:-http://localhost:8000}"
ENDPOINT="${AGENT_URL}/webhooks/alertmanager"
STARTS_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

case="${1:-}"

# --------------------------------------------------------------------------
# Fonctions helpers
# --------------------------------------------------------------------------

send() {
  local payload="$1"
  echo "→ POST ${ENDPOINT}"
  echo ""
  RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${ENDPOINT}" \
    -H "Content-Type: application/json" \
    -d "${payload}")
  HTTP_CODE=$(echo "${RESPONSE}" | tail -1)
  BODY=$(echo "${RESPONSE}" | head -n -1)

  echo "← HTTP ${HTTP_CODE}"
  if command -v jq &>/dev/null; then
    echo "${BODY}" | jq .
  else
    echo "${BODY}"
  fi
  echo ""

  # Extraire l'incident_id pour le poll
  if command -v jq &>/dev/null; then
    INCIDENT_ID=$(echo "${BODY}" | jq -r '.incident_id // empty')
    if [[ -n "${INCIDENT_ID}" && "${INCIDENT_ID}" != "watchdog" ]]; then
      echo "→ Attente du diagnostic (poll GET /api/v1/incidents/${INCIDENT_ID})..."
      for i in $(seq 1 20); do
        sleep 0.5
        POLL=$(curl -s "${AGENT_URL}/api/v1/incidents/${INCIDENT_ID}")
        STATUS=$(echo "${POLL}" | jq -r '.status')
        echo "   [${i}] status=${STATUS}"
        if [[ "${STATUS}" == "completed" || "${STATUS}" == "completed_with_errors" || "${STATUS}" == "failed" ]]; then
          echo ""
          echo "← Rapport final :"
          echo "${POLL}" | jq .
          break
        fi
      done
    fi
  fi
}

# --------------------------------------------------------------------------
# Payloads par cas
# --------------------------------------------------------------------------

case_a_payload() {
  cat <<EOF
{
  "version": "4",
  "groupKey": "{/}{namespace='otel-demo'}:{alertname='OtelDemoServiceHighErrorRate'}",
  "truncatedAlerts": 0,
  "status": "firing",
  "receiver": "ai4ops-agent",
  "groupLabels": {"namespace": "otel-demo"},
  "commonLabels": {
    "namespace": "otel-demo",
    "alertname": "OtelDemoServiceHighErrorRate"
  },
  "commonAnnotations": {},
  "externalURL": "http://alertmanager:9093",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "OtelDemoServiceHighErrorRate",
        "namespace": "otel-demo",
        "severity": "critical",
        "service_name": "product-catalog"
      },
      "annotations": {
        "summary": "High error rate on product-catalog",
        "description": "Error rate exceeded 5% threshold for 2 minutes."
      },
      "startsAt": "${STARTS_AT}",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus/graph",
      "fingerprint": "script-case-a-$(date +%s)"
    }
  ]
}
EOF
}

case_b_payload() {
  cat <<EOF
{
  "version": "4",
  "groupKey": "{/}{namespace='otel-demo'}:{alertname='OtelDemoServiceHighErrorRate'}",
  "truncatedAlerts": 0,
  "status": "firing",
  "receiver": "ai4ops-agent",
  "groupLabels": {"namespace": "otel-demo"},
  "commonLabels": {
    "namespace": "otel-demo",
    "alertname": "OtelDemoServiceHighErrorRate"
  },
  "commonAnnotations": {},
  "externalURL": "http://alertmanager:9093",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "OtelDemoServiceHighErrorRate",
        "namespace": "otel-demo",
        "severity": "critical",
        "service_name": "checkout"
      },
      "annotations": {
        "summary": "High error rate on checkout",
        "description": "Error rate exceeded 5% threshold for 2 minutes."
      },
      "startsAt": "${STARTS_AT}",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus/graph",
      "fingerprint": "script-case-b-$(date +%s)"
    }
  ]
}
EOF
}

case_c_payload() {
  cat <<EOF
{
  "version": "4",
  "groupKey": "{/}{namespace='otel-demo'}:{alertname='OtelDemoServiceHighErrorRate'}",
  "truncatedAlerts": 0,
  "status": "firing",
  "receiver": "ai4ops-agent",
  "groupLabels": {"namespace": "otel-demo"},
  "commonLabels": {
    "namespace": "otel-demo",
    "alertname": "OtelDemoServiceHighErrorRate"
  },
  "commonAnnotations": {},
  "externalURL": "http://alertmanager:9093",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "OtelDemoServiceHighErrorRate",
        "namespace": "otel-demo",
        "severity": "warning",
        "service_name": "frontend"
      },
      "annotations": {
        "summary": "High error rate on frontend",
        "description": "Error rate exceeded 5% threshold for 2 minutes."
      },
      "startsAt": "${STARTS_AT}",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://prometheus/graph",
      "fingerprint": "script-case-c-$(date +%s)"
    }
  ]
}
EOF
}

watchdog_payload() {
  cat <<EOF
{
  "version": "4",
  "groupKey": "{/}{alertname='Watchdog'}",
  "truncatedAlerts": 0,
  "status": "firing",
  "receiver": "ai4ops-agent",
  "groupLabels": {},
  "commonLabels": {"alertname": "Watchdog"},
  "commonAnnotations": {},
  "externalURL": "http://alertmanager:9093",
  "alerts": [
    {
      "status": "firing",
      "labels": {"alertname": "Watchdog", "namespace": "monitoring"},
      "annotations": {"summary": "Alertmanager heartbeat"},
      "startsAt": "${STARTS_AT}",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "",
      "fingerprint": "watchdog-$(date +%s)"
    }
  ]
}
EOF
}

# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

case "${case}" in
  case_a|a)
    echo "=== Cas A : product-catalog (timeout Redis) ==="
    send "$(case_a_payload)"
    ;;
  case_b|b)
    echo "=== Cas B : checkout (OOMKilled) ==="
    send "$(case_b_payload)"
    ;;
  case_c|c)
    echo "=== Cas C : frontend (données insuffisantes) ==="
    send "$(case_c_payload)"
    ;;
  watchdog|w)
    echo "=== Watchdog (heartbeat Alertmanager) ==="
    send "$(watchdog_payload)"
    ;;
  all)
    echo "=== Envoi des 3 cas ==="
    send "$(case_a_payload)"
    sleep 1
    send "$(case_b_payload)"
    sleep 1
    send "$(case_c_payload)"
    ;;
  *)
    echo "Usage: $0 {case_a|case_b|case_c|watchdog|all}"
    echo ""
    echo "  case_a   product-catalog — timeout dépendance Redis"
    echo "  case_b   checkout        — pod OOMKilled / CrashLoop"
    echo "  case_c   frontend        — données insuffisantes"
    echo "  watchdog Heartbeat Alertmanager (ignoré)"
    echo "  all      Envoie les 3 cas successivement"
    exit 1
    ;;
esac
