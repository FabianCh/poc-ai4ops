"""Jaeger provider (traces en erreur) via le proxy Grafana datasource API.

Les traces sont du contenu externe non fiable. Le provider ne copie que des champs d'une liste
blanche (service, opération, codes de statut, message d'erreur tronqué) : aucun autre tag Jaeger
n'est transmis, ni au LLM, ni à l'audit.
"""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx

from ia4ops_agent.providers.interfaces import TracesUnavailableError
from ia4ops_agent.providers.real._grafana import (
    GrafanaConfigurationError,
    grafana_connection,
)

_DATASOURCE_UID = "webstore-traces"
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_MAX_TRACES = 20
_MAX_TOP_SPANS = 5
_MAX_CHAIN = 6
_MAX_SAMPLE_TRACE_IDS = 3
_MAX_OPERATION_LENGTH = 100
_MAX_DESCRIPTION_LENGTH = 200
_MAX_CODE_LENGTH = 20


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _code(value: Any) -> str | None:
    """Code de statut (entier ou court texte) ; les autres types sont ignorés."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    return _text(str(value), _MAX_CODE_LENGTH)


def _tags(span: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for tag in span.get("tags") or []:
        if isinstance(tag, dict) and isinstance(tag.get("key"), str):
            result[tag["key"]] = tag.get("value")
    return result


def _is_error(tags: dict[str, Any]) -> bool:
    return tags.get("otel.status_code") == "ERROR" or tags.get("error") in (True, "true")


def _summarize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Réponse Jaeger invalide")
    traces = payload.get("data")
    if traces is None:
        traces = []
    if not isinstance(traces, list):
        raise ValueError("Réponse Jaeger sans liste de traces")

    span_counts: Counter[tuple[str, str, str | None, str | None, str | None, str | None]] = (
        Counter()
    )
    chains: Counter[tuple[str, ...]] = Counter()
    trace_ids: list[str] = []
    max_duration_us = 0
    for trace in traces:
        if not isinstance(trace, dict):
            raise ValueError("Trace Jaeger invalide")
        processes = trace.get("processes") or {}
        spans = trace.get("spans") or []
        if not isinstance(processes, dict) or not isinstance(spans, list):
            raise ValueError("Trace Jaeger sans spans")
        trace_id = trace.get("traceID")
        if isinstance(trace_id, str) and _TRACE_ID.match(trace_id):
            trace_ids.append(trace_id)
        first_error: dict[str, int] = {}
        for span in spans:
            if not isinstance(span, dict):
                continue
            duration = span.get("duration")
            if isinstance(duration, int) and not isinstance(duration, bool):
                max_duration_us = max(max_duration_us, duration)
            tags = _tags(span)
            if not _is_error(tags):
                continue
            process = processes.get(span.get("processID"))
            service = _text(process.get("serviceName") if isinstance(process, dict) else None, 80)
            service = service or "inconnu"
            operation = _text(span.get("operationName"), _MAX_OPERATION_LENGTH) or "inconnue"
            start = span.get("startTime")
            if isinstance(start, int) and not isinstance(start, bool):
                first_error[service] = min(first_error.get(service, start), start)
            span_counts[(
                service,
                operation,
                _text(tags.get("otel.status_description"), _MAX_DESCRIPTION_LENGTH),
                _code(tags.get("http.status_code")),
                _code(tags.get("rpc.grpc.status_code")),
                _code(tags.get("error.type")),
            )] += 1
        if first_error:
            # services en erreur, de l'amont (span le plus ancien) vers l'aval
            chains[tuple(sorted(first_error, key=first_error.__getitem__))] += 1

    # Spans portant un message d'erreur d'abord (plus informatifs), puis les plus fréquents.
    ranked = sorted(span_counts.items(), key=lambda item: (item[0][2] is None, -item[1]))
    top_spans = []
    for (service, operation, description, http, grpc, error_type), count in ranked[:_MAX_TOP_SPANS]:
        entry: dict[str, Any] = {"service": service, "operation": operation, "count": count}
        for key, value in (
            ("status_description", description),
            ("http_status_code", http),
            ("grpc_status_code", grpc),
            ("error_type", error_type),
        ):
            if value is not None:
                entry[key] = value
        top_spans.append(entry)

    chain = list(chains.most_common(1)[0][0][:_MAX_CHAIN]) if chains else []
    return {
        "error_trace_count": len(traces),
        "top_error_spans": top_spans,
        "services_in_error_chain": chain,
        "max_duration_ms": round(max_duration_us / 1000, 1),
        "sample_trace_ids": trace_ids[:_MAX_SAMPLE_TRACE_IDS],
    }


class JaegerProvider:
    """Collecte une synthèse bornée des traces en erreur d'un service."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def get_error_traces(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
    ) -> dict[str, Any]:
        if window_minutes < 1:
            raise ValueError("window_minutes doit être supérieur ou égal à 1")

        end = datetime.now(UTC).timestamp()
        params = {
            "service": service,
            "tags": json.dumps({"error": "true"}),
            "start": str(int((end - window_minutes * 60) * 1_000_000)),
            "end": str(int(end * 1_000_000)),
            "limit": str(_MAX_TRACES),
        }
        try:
            base_url, auth = grafana_connection()
            url = f"{base_url}/api/datasources/proxy/uid/{_DATASOURCE_UID}/api/traces"
            async with httpx.AsyncClient(
                auth=auth,
                timeout=15.0,
                transport=self._transport,
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                summary = _summarize(response.json())
        except GrafanaConfigurationError as exc:
            raise TracesUnavailableError(str(exc)) from exc
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise TracesUnavailableError(
                f"Échec de la requête Jaeger via Grafana ({type(exc).__name__})."
            ) from exc

        return {
            "service": service,
            "namespace": namespace,
            "window_minutes": window_minutes,
            "status": "success",
            "truncated": summary["error_trace_count"] >= _MAX_TRACES,
            **summary,
        }
