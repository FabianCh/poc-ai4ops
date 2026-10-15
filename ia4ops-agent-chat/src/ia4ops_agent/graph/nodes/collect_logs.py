"""
Nœud collect_logs — collecte les logs d'erreur via LogsProvider.

Cas C : LogsUnavailableError → status "unavailable", le graphe continue.
"""

import time
from typing import Any

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.audit.trace_logging import emit_trace_event, sanitized_log_samples
from ia4ops_agent.graph.state import IncidentState
from ia4ops_agent.providers.interfaces import LogsProvider, LogsUnavailableError


def make_collect_logs_node(provider: LogsProvider):
    """Factory : retourne le nœud avec le provider injecté."""

    async def collect_logs_node(state: IncidentState) -> dict[str, Any]:
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
            # Traces en erreur (collect_traces) : corrélation logs ↔ traces, si disponible.
            trace_ids = state.get("traces_data", {}).get("sample_trace_ids") or None
            logs = await provider.get_recent_errors(service, namespace, trace_ids=trace_ids)
            status = "success"
            logs_data = logs
            if not logs:
                missing.append(
                    f"Aucun log d'erreur trouvé pour {service} sur la fenêtre : "
                    "l'absence de logs ne prouve pas l'absence de problème"
                )
        except LogsUnavailableError as exc:
            status = "unavailable"
            logs_data = []
            missing.append(f"Logs indisponibles pour {service} : {exc.reason}")
            warnings.append(f"Source logs unavailable : {exc}")
        except Exception as exc:  # noqa: BLE001
            status = "invalid"
            logs_data = []
            errors.append({"step": "collect_logs", "error": str(exc)})

        duration_ms = int((time.monotonic() - start) * 1000)
        event = AuditEvent(
            event_id=AuditEvent.make_id(incident_id, "collect_logs", len(audit_events)),
            incident_id=incident_id,
            step="collect_logs",
            status=status,
            input_summary={"service": service, "namespace": namespace},
            output_summary={"status": status, "log_count": len(logs_data)},
            duration_ms=duration_ms,
            error=str(warnings[-1]) if status == "unavailable" and warnings else None,
        )
        audit_events.append(event.model_dump())
        emit_trace_event(
            "data_collected",
            incident_id,
            source="loki",
            status=status,
            service=service,
            namespace=namespace,
            window_minutes=15,
            log_count=len(logs_data),
            log_samples=sanitized_log_samples(logs_data),
        )

        return {
            "logs_status": status,
            "logs_data": logs_data,
            "audit_events": audit_events,
            "warnings": warnings,
            "errors": errors,
            "missing_information": missing,
        }

    return collect_logs_node
