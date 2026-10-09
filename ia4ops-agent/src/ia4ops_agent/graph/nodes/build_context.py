"""
Nœud build_context — assemble l'IncidentContext borné depuis l'état.

Traduit les données brutes collectées en un contexte structuré et compact
prêt à être injecté dans le prompt LLM. Ne transmet jamais de volumes bruts.
"""

import time
from typing import Any

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.audit.trace_logging import emit_trace_event
from ia4ops_agent.domain.context import (
    IncidentContext,
    IncidentInfo,
    KubernetesObservation,
    LogPattern,
    LogsObservation,
    MetricsObservation,
    Observations,
    SourceStatuses,
)
from ia4ops_agent.graph.state import IncidentState, SourceStatus


_MAX_ANNOTATION_LENGTH = 300


def _bounded_text(value: Any, limit: int = _MAX_ANNOTATION_LENGTH) -> str | None:
    """Texte externe normalisé (espaces) et tronqué ; None si vide ou non textuel."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _http_url(value: Any) -> str | None:
    text = _bounded_text(value, 300)
    return text if text and text.startswith(("http://", "https://")) else None


def _build_metrics_observation(data: dict[str, Any]) -> MetricsObservation | None:
    if not data:
        return None
    return MetricsObservation(
        error_rate=data.get("error_rate"),
        latency_p95_ms=data.get("latency_p95_ms"),
        cpu_ratio=data.get("cpu_ratio"),
        memory_ratio=data.get("memory_ratio"),
        request_rate=data.get("request_rate"),
        window_minutes=data.get("window_minutes", 15),
    )


def _build_logs_observation(logs: list[dict[str, Any]]) -> LogsObservation | None:
    if not logs:
        return None

    # Agréger les patterns par message (simplifié : top 5 messages)
    patterns: dict[str, int] = {}
    for log in logs:
        msg = log.get("message", "")
        patterns[msg] = patterns.get(msg, 0) + 1

    top = sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:5]
    return LogsObservation(
        error_count=len(logs),
        top_patterns=[
            LogPattern(
                pattern=msg[:200],  # borné
                count=count,
                sample_message=msg[:200],
            )
            for msg, count in top
        ],
        sample_event_ids=[log.get("event_id", "") for log in logs[:3]],
        window_minutes=15,
    )


def _build_k8s_observation(data: dict[str, Any]) -> KubernetesObservation | None:
    if not data:
        return None
    return KubernetesObservation(
        desired_replicas=data.get("desired_replicas"),
        ready_replicas=data.get("ready_replicas"),
        restart_count=data.get("restart_count", 0),
        recent_events=data.get("events", [])[:5],  # borné à 5
        pod_statuses=data.get("pod_statuses", [])[:5],
    )


async def build_context_node(state: IncidentState) -> dict[str, Any]:
    start = time.monotonic()
    incident_id = state["incident_id"]
    normalized = state["normalized_alert"]
    audit_events = list(state.get("audit_events", []))

    metrics_status: SourceStatus = state.get("metrics_status", "not_started")
    logs_status: SourceStatus = state.get("logs_status", "not_started")
    cluster_status: SourceStatus = state.get("cluster_status", "not_started")

    metrics_obs = _build_metrics_observation(state.get("metrics_data", {}))
    logs_obs = _build_logs_observation(state.get("logs_data", []))
    cluster_obs = _build_k8s_observation(state.get("cluster_data", {}))

    ctx = IncidentContext(
        incident=IncidentInfo(
            id=incident_id,
            alert_name=normalized.get("alert_name", "unknown"),
            service=normalized.get("service", "unknown"),
            namespace=normalized.get("namespace", "otel-demo"),
            severity=normalized.get("severity", "unknown"),
            started_at=normalized.get("started_at", ""),
            alerts_count=normalized.get("alerts_count"),
            summary=_bounded_text(normalized.get("summary")),
            description=_bounded_text(normalized.get("description")),
            runbook_url=_http_url(normalized.get("runbook_url")),
        ),
        observations=Observations(
            metrics=metrics_obs,
            logs=logs_obs,
            kubernetes=cluster_obs,
        ),
        source_status=SourceStatuses(
            metrics=metrics_status,
            logs=logs_status,
            cluster=cluster_status,
        ),
        known_missing=list(state.get("missing_information", [])),
    )

    duration_ms = int((time.monotonic() - start) * 1000)
    event = AuditEvent(
        event_id=AuditEvent.make_id(incident_id, "build_context", len(audit_events)),
        incident_id=incident_id,
        step="build_context",
        status="success",
        input_summary={
            "metrics_status": metrics_status,
            "logs_status": logs_status,
            "cluster_status": cluster_status,
        },
        output_summary={
            "has_metrics": metrics_obs is not None,
            "has_logs": logs_obs is not None,
            "has_kubernetes": cluster_obs is not None,
            "known_missing_count": len(ctx.known_missing),
        },
        duration_ms=duration_ms,
    )
    audit_events.append(event.model_dump())
    context_for_llm = ctx.to_llm_dict()
    emit_trace_event(
        "diagnostic_context_built",
        incident_id,
        source_status={
            "metrics": metrics_status,
            "logs": logs_status,
            "cluster": cluster_status,
        },
        context=context_for_llm,
    )

    return {
        "incident_context": context_for_llm,
        "audit_events": audit_events,
    }
