"""
Nœud collect_traces — collecte une synthèse des traces en erreur via TracesProvider.

Une source unavailable ne bloque pas le graphe : collect_logs s'exécute alors sans identifiants
de trace (la corrélation logs ↔ traces est un bonus, jamais un prérequis).
"""

import time
from typing import Any

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.audit.trace_logging import emit_trace_event
from ia4ops_agent.graph.state import IncidentState
from ia4ops_agent.providers.interfaces import TracesProvider, TracesUnavailableError


def make_collect_traces_node(provider: TracesProvider):
    """Factory : retourne le nœud avec le provider injecté."""

    async def collect_traces_node(state: IncidentState) -> dict[str, Any]:
        start = time.monotonic()
        incident_id = state["incident_id"]
        normalized = state["normalized_alert"]
        service = normalized.get("service", "unknown")
        namespace = normalized.get("namespace", "otel-demo")

        audit_events = list(state.get("audit_events", []))
        warnings = list(state.get("warnings", []))
        errors = list(state.get("errors", []))
        missing = list(state.get("missing_information", []))

        try:
            traces_data = await provider.get_error_traces(service, namespace)
            status = traces_data.get("status", "success")
            if status not in ("success", "partial"):
                status = "invalid"
        except TracesUnavailableError as exc:
            status = "unavailable"
            traces_data = {}
            missing.append(f"Traces indisponibles pour {service} : {exc.reason}")
            warnings.append(f"Source traces unavailable : {exc}")
        except Exception as exc:  # noqa: BLE001
            status = "invalid"
            traces_data = {}
            errors.append({"step": "collect_traces", "error": str(exc)})

        duration_ms = int((time.monotonic() - start) * 1000)
        event = AuditEvent(
            event_id=AuditEvent.make_id(incident_id, "collect_traces", len(audit_events)),
            incident_id=incident_id,
            step="collect_traces",
            status=status,
            input_summary={"service": service, "namespace": namespace},
            output_summary={
                "status": status,
                "error_trace_count": traces_data.get("error_trace_count", 0),
            },
            duration_ms=duration_ms,
            error=str(warnings[-1]) if status == "unavailable" and warnings else None,
        )
        audit_events.append(event.model_dump())
        emit_trace_event(
            "data_collected",
            incident_id,
            source="jaeger",
            status=status,
            service=service,
            namespace=namespace,
            window_minutes=traces_data.get("window_minutes", 15),
            observations=traces_data,
        )

        return {
            "traces_status": status,
            "traces_data": traces_data,
            "audit_events": audit_events,
            "warnings": warnings,
            "errors": errors,
            "missing_information": missing,
        }

    return collect_traces_node
