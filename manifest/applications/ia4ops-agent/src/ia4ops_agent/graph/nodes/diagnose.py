"""
Nœud diagnose — appelle le LLMClient et stocke le résultat brut dans l'état.

En cas d'échec persistant : stocke un DiagnosticFailure et continue vers finalize.
"""

import time
from typing import Any

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.domain.diagnosis import DiagnosticFailure
from ia4ops_agent.graph.state import IncidentState
from ia4ops_agent.llm.interface import DiagnosisError, LLMClient


def make_diagnose_node(llm_client: LLMClient):
    """Factory : retourne le nœud avec le client LLM injecté."""

    async def diagnose_node(state: IncidentState) -> dict[str, Any]:
        start = time.monotonic()
        incident_id = state["incident_id"]
        incident_context = state.get("incident_context", {})
        audit_events = list(state.get("audit_events", []))
        errors = list(state.get("errors", []))

        try:
            output, llm_summary = await llm_client.diagnose(incident_context)
            diagnosis = output.model_dump()
            diag_status = "success"
            error_msg = None
        except DiagnosisError as exc:
            failure = DiagnosticFailure(
                incident_id=incident_id,
                failure_reason=exc.reason,
                attempts=exc.attempts,
                last_error=str(exc),
            )
            diagnosis = failure.model_dump()
            diag_status = "error"
            error_msg = str(exc)
            errors.append({"step": "diagnose", "error": error_msg})
            llm_summary = None
        except Exception as exc:  # noqa: BLE001
            failure = DiagnosticFailure(
                incident_id=incident_id,
                failure_reason="Erreur inattendue du LLM",
                last_error=str(exc),
            )
            diagnosis = failure.model_dump()
            diag_status = "error"
            error_msg = str(exc)
            errors.append({"step": "diagnose", "error": error_msg})
            llm_summary = None

        duration_ms = int((time.monotonic() - start) * 1000)
        event = AuditEvent(
            event_id=AuditEvent.make_id(incident_id, "diagnose", len(audit_events)),
            incident_id=incident_id,
            step="diagnose",
            status=diag_status,
            input_summary={"context_keys": list(incident_context.keys())},
            output_summary={
                "model": llm_summary.model_name if llm_summary else "n/a",
                "attempts": llm_summary.total_attempts if llm_summary else 0,
                "severity": diagnosis.get("severity_assessment", "unknown"),
            },
            duration_ms=duration_ms,
            error=error_msg,
        )
        audit_events.append(event.model_dump())

        return {
            "diagnosis": diagnosis,
            "audit_events": audit_events,
            "errors": errors,
        }

    return diagnose_node
