"""Prometheus provider via le proxy Grafana datasource API."""

import asyncio
import json
import math
from typing import Any

import httpx

from ia4ops_agent.providers.interfaces import MetricsUnavailableError
from ia4ops_agent.providers.real._grafana import (
    GrafanaConfigurationError,
    grafana_connection,
)

_CALLS = "traces_span_metrics_calls_total"
_DURATION_BUCKETS = "traces_span_metrics_duration_milliseconds_bucket"
_SERVER_SPANS = 'span_kind="SPAN_KIND_SERVER"'


def _query_value(payload: dict[str, Any]) -> float | None:
    if not isinstance(payload, dict):
        raise ValueError("Réponse Prometheus invalide")
    if payload.get("status") != "success":
        raise ValueError("Prometheus a retourné un statut non-success")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Réponse Prometheus sans objet data")
    results = data.get("result")
    if not isinstance(results, list):
        raise ValueError("Réponse Prometheus sans liste de résultats")
    if not results:
        return None
    if not isinstance(results[0], dict):
        raise ValueError("Résultat Prometheus invalide")
    value = results[0].get("value")
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("Résultat Prometheus sans valeur instantanée")
    result = float(value[1])
    return result if math.isfinite(result) else None


class PrometheusProvider:
    """Collecte taux d'erreur, débit et p95 des spans serveur."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def _query(self, query: str) -> float | None:
        try:
            base_url, auth = grafana_connection()
            url = f"{base_url}/api/datasources/proxy/uid/prometheus/api/v1/query"
            async with httpx.AsyncClient(
                auth=auth,
                timeout=15.0,
                transport=self._transport,
            ) as client:
                response = await client.get(url, params={"query": query})
                response.raise_for_status()
                return _query_value(response.json())
        except GrafanaConfigurationError as exc:
            raise MetricsUnavailableError(str(exc)) from exc
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise MetricsUnavailableError(
                f"Échec de la requête Prometheus via Grafana ({type(exc).__name__})."
            ) from exc

    async def get_service_metrics(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
    ) -> dict[str, Any]:
        if window_minutes < 1:
            raise ValueError("window_minutes doit être supérieur ou égal à 1")

        service_matcher = f"service_name={json.dumps(service)}"
        window = f"{window_minutes}m"
        calls = f"{_CALLS}{{{service_matcher}, {_SERVER_SPANS}}}"
        error_calls = (
            f'{_CALLS}{{{service_matcher}, {_SERVER_SPANS}, status_code="STATUS_CODE_ERROR"}}'
        )

        error_rate_query = f"sum(rate({error_calls}[{window}])) / sum(rate({calls}[{window}]))"
        request_rate_query = f"sum(rate({calls}[{window}]))"
        latency_query = (
            "histogram_quantile(0.95, "
            f"sum by (le) (rate({_DURATION_BUCKETS}{{{service_matcher}, "
            f"{_SERVER_SPANS}}}[{window}])))"
        )

        error_rate, request_rate, latency_p95 = await asyncio.gather(
            self._query(error_rate_query),
            self._query(request_rate_query),
            self._query(latency_query),
        )

        data: dict[str, Any] = {
            "service": service,
            "namespace": namespace,
            "window_minutes": window_minutes,
            "status": "success",
        }
        if request_rate is not None:
            data["request_rate"] = request_rate
        if error_rate is not None:
            data["error_rate"] = error_rate
        elif request_rate is not None:
            data["error_rate"] = 0.0
        if latency_p95 is not None:
            data["latency_p95_ms"] = latency_p95

        if request_rate is None and error_rate is None and latency_p95 is None:
            raise MetricsUnavailableError(
                f"Aucune métrique applicative Prometheus pour le service {service!r}."
            )
        if request_rate is None or latency_p95 is None:
            data["status"] = "partial"
        return data
