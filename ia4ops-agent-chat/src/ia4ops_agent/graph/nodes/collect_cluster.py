"""
Nœud collect_cluster — collecte l'état du workload Kubernetes via ClusterProvider.

Cas C : workload retourne status="partial" → le graphe continue avec données partielles.
"""

import time
from typing import Any

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.audit.trace_logging import emit_trace_event
from ia4ops_agent.graph.state import IncidentState
from ia4ops_agent.providers.interfaces import ClusterProvider, ClusterUnavailableError


def make_collect_cluster_node(provider: ClusterProvider):
    """Factory : retourne le nœud avec le provider injecté."""

    async def collect_cluster_node(state: IncidentState) -> dict[str, Any]:
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
            workload = await provider.get_workload_status(service, namespace)
            events = await provider.get_cluster_events(namespace, service)
            status = workload.get("status", "success")
            if status == "partial":
                missing.append("État Kubernetes partiel — données de réplicas non disponibles")
                warnings.append(f"Cluster partial pour {service}")
            cluster_data = {**workload, "events": events}
        except ClusterUnavailableError as exc:
            status = "unavailable"
            cluster_data = {}
            missing.append(f"État cluster indisponible pour {service} : {exc.reason}")
            warnings.append(f"Source cluster unavailable : {exc}")
        except Exception as exc:  # noqa: BLE001
            status = "invalid"
            cluster_data = {}
            errors.append({"step": "collect_cluster", "error": str(exc)})

        duration_ms = int((time.monotonic() - start) * 1000)
        event = AuditEvent(
            event_id=AuditEvent.make_id(incident_id, "collect_cluster", len(audit_events)),
            incident_id=incident_id,
            step="collect_cluster",
            status=status,
            input_summary={"service": service, "namespace": namespace},
            output_summary={
                "status": status,
                "events_count": len(cluster_data.get("events", [])),
            },
            duration_ms=duration_ms,
        )
        audit_events.append(event.model_dump())
        emit_trace_event(
            "data_collected",
            incident_id,
            source="kubernetes",
            status=status,
            service=service,
            namespace=namespace,
            observations=cluster_data,
        )

        return {
            "cluster_status": status,
            "cluster_data": cluster_data,
            "audit_events": audit_events,
            "warnings": warnings,
            "errors": errors,
            "missing_information": missing,
        }

    return collect_cluster_node
