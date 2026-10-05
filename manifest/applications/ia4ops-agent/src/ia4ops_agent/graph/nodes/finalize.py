"""
Nœud finalize — construit le rapport final et écrit l'audit trail sur disque.

Le rapport est la sortie publique de l'incident :
- lecture seule, jamais d'action exécutée
- contient un résumé de l'état des sources
- pointe vers le fichier d'audit pour la traçabilité complète
"""

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.audit.writer import AuditWriter
from ia4ops_agent.graph.state import IncidentState


def make_finalize_node(audit_writer: AuditWriter):
    """Factory : retourne le nœud avec l'AuditWriter injecté."""

    async def finalize_node(state: IncidentState) -> dict[str, Any]:
        start = time.monotonic()
        incident_id = state["incident_id"]
        diagnosis = state.get("diagnosis", {})
        audit_events = list(state.get("audit_events", []))
        warnings = list(state.get("warnings", []))
        errors = list(state.get("errors", []))
        missing = list(state.get("missing_information", []))

        # Construire le rapport final
        report = {
            "incident_id": incident_id,
            "finalized_at": datetime.now(UTC).isoformat(),
            "status": "completed" if not errors else "completed_with_errors",
            "diagnosis": diagnosis,
            "source_status": {
                "metrics": state.get("metrics_status", "not_started"),
                "logs": state.get("logs_status", "not_started"),
                "cluster": state.get("cluster_status", "not_started"),
            },
            "missing_information": missing,
            "warnings": warnings,
            "errors": errors,
            "audit_events_count": len(audit_events) + 1,  # +1 pour cet événement
            "action_executed": False,  # invariant scénario 1
        }

        duration_ms = int((time.monotonic() - start) * 1000)
        final_event = AuditEvent(
            event_id=AuditEvent.make_id(incident_id, "finalize", len(audit_events)),
            incident_id=incident_id,
            step="finalize",
            status="success",
            input_summary={"errors_count": len(errors), "warnings_count": len(warnings)},
            output_summary={
                "report_status": report["status"],
                "diagnosis_summary": str(diagnosis.get("summary", ""))[:100],
            },
            duration_ms=duration_ms,
        )
        audit_events.append(final_event.model_dump())

        # Écrire tous les événements d'audit sur disque
        for raw_event in audit_events:
            try:
                evt = AuditEvent(**raw_event)
                audit_writer.write(evt)
            except Exception:  # noqa: BLE001
                pass  # L'audit ne bloque jamais le workflow

        return {
            "report": report,
            "audit_events": audit_events,
        }

    return finalize_node
