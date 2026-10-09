"""
Nœud initialize — premier nœud du graphe.

Responsabilités :
- Générer un incident_id unique
- Extraire le service et les infos clés du payload brut
- Créer le premier AuditEvent
- Initialiser les listes audit_events, warnings, errors, missing_information
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.audit.trace_logging import emit_trace_event
from ia4ops_agent.domain.alerts import AlertmanagerWebhook, service_from_labels
from ia4ops_agent.graph.state import IncidentState


def initialize_node(state: IncidentState) -> dict[str, Any]:
    """Initialise l'incident à partir du payload brut Alertmanager."""
    start = datetime.now(UTC)
    raw = state["raw_alert"]

    # Parser le webhook pour extraire les infos normalisées
    webhook = AlertmanagerWebhook(**raw)
    primary = webhook.primary_alert()

    incident_id = state.get("incident_id") or (
        f"inc-{start.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    )
    correlation_id = webhook.groupKey

    normalized = {
        "incident_id": incident_id,
        "alert_name": primary.labels.alertname,
        "service": service_from_labels(primary.labels) or "unknown",
        "namespace": primary.labels.namespace,
        "severity": primary.labels.severity or "unknown",
        "started_at": primary.startsAt.isoformat(),
        "fingerprint": primary.fingerprint,
        "status": webhook.status,
        "is_watchdog": webhook.is_watchdog(),
        "affected_services": webhook.affected_services(),
        "alerts_count": len(webhook.alerts),
        # Annotations de l'alerte principale : texte externe, borné plus loin (build_context)
        "summary": primary.annotations.summary,
        "description": primary.annotations.description,
        "runbook_url": primary.annotations.runbook_url,
    }

    duration_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
    event = AuditEvent(
        event_id=AuditEvent.make_id(incident_id, "initialize", 0),
        incident_id=incident_id,
        step="initialize",
        status="success",
        input_summary={"group_key": correlation_id, "alerts_count": len(webhook.alerts)},
        output_summary={"service": normalized["service"], "severity": normalized["severity"]},
        duration_ms=duration_ms,
    )
    emit_trace_event(
        "incident_initialized",
        incident_id,
        correlation_id=correlation_id,
        normalized_alert=normalized,
    )

    return {
        "incident_id": incident_id,
        "correlation_id": correlation_id,
        "received_at": start.isoformat(),
        "normalized_alert": normalized,
        "audit_events": [event.model_dump()],
        "warnings": [],
        "errors": [],
        "missing_information": [],
    }
