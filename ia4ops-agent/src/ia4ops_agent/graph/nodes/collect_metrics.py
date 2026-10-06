"""
Nœud collect_metrics — collecte les métriques du service via MetricsProvider.

Gère les 4 statuts : success, partial, unavailable, invalid.
Une source unavailable/invalid ne bloque pas le graphe.
"""

import time
from typing import Any

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.audit.trace_logging import emit_trace_event
from ia4ops_agent.graph.state import IncidentState
from ia4ops_agent.providers.interfaces import MetricsProvider, MetricsUnavailableError


def make_collect_metrics_node(provider: MetricsProvider):
    """Factory : retourne le nœud avec le provider injecté."""

    async def collect_metrics_node(state: IncidentState) -> dict[str, Any]:
        start = time.monotonic()
        incident_id = state["incident_id"]
        normalized = state["normalized_alert"]
        service = normalized.get("service", "unknown")
        namespace = normalized.get("namespace", "otel-demo")

        audit_events = list(state.get("audit_events", []))
        warnings = list(state.get("warnings", []))
        errors = list(state.get("errors", []))

        try:
            data = await provider.get_service_metrics(service, namespace)
            status = data.get("status", "success")
            if status not in ("success", "partial"):
                status = "invalid"
            metrics_data = data
        except MetricsUnavailableError as exc:
            status = "unavailable"
            metrics_data = {}
            warnings.append(f"Métriques indisponibles pour {service} : {exc}")
        except Exception as exc:  # noqa: BLE001
            status = "invalid"
            metrics_data = {}
            errors.append({"step": "collect_metrics", "error": str(exc)})

        duration_ms = int((time.monotonic() - start) * 1000)
        event = AuditEvent(
            event_id=AuditEvent.make_id(incident_id, "collect_metrics", len(audit_events)),
            incident_id=incident_id,
            step="collect_metrics",
            status=status,
            input_summary={"service": service, "namespace": namespace},
            output_summary={"status": status, "keys": list(metrics_data.keys())},
            duration_ms=duration_ms,
            error=(
                errors[-1]["error"]
                if errors and errors[-1].get("step") == "collect_metrics"
                else None
            ),
        )
        audit_events.append(event.model_dump())
        emit_trace_event(
            "data_collected",
            incident_id,
            source="prometheus",
            status=status,
            service=service,
            namespace=namespace,
            window_minutes=metrics_data.get("window_minutes", 15),
            observations=metrics_data,
        )

        return {
            "metrics_status": status,
            "metrics_data": metrics_data,
            "audit_events": audit_events,
            "warnings": warnings,
            "errors": errors,
        }

    return collect_metrics_node
