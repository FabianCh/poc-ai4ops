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

_MEMORY = "container_memory_working_set_bytes"
_CPU_USAGE = "container_cpu_usage_seconds_total"
_LIMITS = "kube_pod_container_resource_limits"
_RESTARTS = "kube_pod_container_status_restarts_total"
_LAST_TERMINATED = "kube_pod_container_status_last_terminated_reason"
_BY_POD = "namespace, pod, container"
# Mêmes fenêtres que les règles otel-demo.containers (CPU 5 m, OOMKilled 10 m).
_CPU_WINDOW = "5m"
_RESTART_WINDOW = "10m"
_OBSERVATION_KEYS = (
    "error_rate",
    "request_rate",
    "latency_p95_ms",
    "memory_ratio",
    "memory_working_set_mb",
    "cpu_cores",
    "restarts_10m",
)


def _span_queries(service: str, window: str) -> dict[str, str]:
    service_matcher = f"service_name={json.dumps(service)}"
    calls = f"{_CALLS}{{{service_matcher}, {_SERVER_SPANS}}}"
    error_calls = (
        f'{_CALLS}{{{service_matcher}, {_SERVER_SPANS}, status_code="STATUS_CODE_ERROR"}}'
    )
    return {
        "error_rate": f"sum(rate({error_calls}[{window}])) / sum(rate({calls}[{window}]))",
        "request_rate": f"sum(rate({calls}[{window}]))",
        "latency_p95_ms": (
            "histogram_quantile(0.95, "
            f"sum by (le) (rate({_DURATION_BUCKETS}{{{service_matcher}, "
            f"{_SERVER_SPANS}}}[{window}])))"
        ),
    }


def _container_queries(service: str, namespace: str) -> dict[str, str]:
    """Requêtes cAdvisor / kube-state-metrics (le conteneur porte le nom du service)."""
    sel = f"namespace={json.dumps(namespace)}, container={json.dumps(service)}"
    limit = f'{_LIMITS}{{{sel}, resource="%s"}}'
    return {
        # Ratio calculé pod par pod (jamais l'usage d'un pod divisé par la limite d'un autre),
        # puis pire pod du service.
        "memory_ratio": (
            f"max(max by ({_BY_POD}) ({_MEMORY}{{{sel}}}) "
            f"/ on ({_BY_POD}) max by ({_BY_POD}) ({limit % 'memory'}))"
        ),
        "memory_working_set_bytes": f"max({_MEMORY}{{{sel}}})",
        "memory_limit_bytes": f"max({limit % 'memory'})",
        "cpu_cores": (
            f"max(sum by ({_BY_POD}) (rate({_CPU_USAGE}{{{sel}}}[{_CPU_WINDOW}])))"
        ),
        "cpu_limit_cores": f"max({limit % 'cpu'})",
        "restarts_10m": f"sum(increase({_RESTARTS}{{{sel}}}[{_RESTART_WINDOW}]))",
        "oom_last_terminated": (
            f'max({_LAST_TERMINATED}{{{sel}, reason="OOMKilled"}})'
        ),
    }


def _rounded(value: float, digits: int = 3) -> float:
    return round(value, digits)


def _add_container_metrics(data: dict[str, Any], values: dict[str, float | None]) -> None:
    """Ajoute les métriques de conteneur présentes ; cpu_ratio seulement avec une limite CPU."""
    megabyte = 1024 * 1024
    if values.get("memory_ratio") is not None:
        data["memory_ratio"] = _rounded(values["memory_ratio"])
    if values.get("memory_working_set_bytes") is not None:
        data["memory_working_set_mb"] = _rounded(values["memory_working_set_bytes"] / megabyte, 1)
    if values.get("memory_limit_bytes") is not None:
        data["memory_limit_mb"] = _rounded(values["memory_limit_bytes"] / megabyte, 1)
    cpu_cores = values.get("cpu_cores")
    if cpu_cores is not None:
        data["cpu_cores"] = _rounded(cpu_cores)
        cpu_limit = values.get("cpu_limit_cores")
        if cpu_limit:
            data["cpu_ratio"] = _rounded(cpu_cores / cpu_limit)
    restarts = values.get("restarts_10m")
    if restarts is not None:
        data["restarts_10m"] = int(round(restarts))
        # Même corrélation que OtelDemoContainerOOMKilled : redémarrage récent ET dernière
        # terminaison en OOMKilled.
        data["oom_killed"] = data["restarts_10m"] > 0 and values.get("oom_last_terminated") == 1.0



class PrometheusProvider:
    """Collecte les métriques applicatives (spanmetrics) et de conteneur (cAdvisor, KSM).

    Les deux familles sont indépendantes : une requête en échec n'annule jamais les autres. Le
    résultat liste les requêtes en échec (`failed`) et le statut vaut `partial` dès qu'une famille
    ou une requête manque.
    """

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

    async def _query_family(
        self, queries: dict[str, str]
    ) -> tuple[dict[str, float | None], list[str]]:
        """Exécute les requêtes d'une famille ; retourne (valeurs, noms des requêtes en échec)."""
        names = list(queries)
        results = await asyncio.gather(
            *(self._query(queries[name]) for name in names), return_exceptions=True
        )
        values: dict[str, float | None] = {}
        failed: list[str] = []
        for name, result in zip(names, results, strict=True):
            if isinstance(result, MetricsUnavailableError):
                failed.append(name)
                values[name] = None
            elif isinstance(result, BaseException):
                raise result
            else:
                values[name] = result
        return values, failed

    async def get_service_metrics(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
    ) -> dict[str, Any]:
        if window_minutes < 1:
            raise ValueError("window_minutes doit être supérieur ou égal à 1")

        try:
            grafana_connection()  # configuration absente : inutile de lancer les requêtes
        except GrafanaConfigurationError as exc:
            raise MetricsUnavailableError(str(exc)) from exc

        window = f"{window_minutes}m"
        span_values, span_failed = await self._query_family(_span_queries(service, window))
        container_values, container_failed = await self._query_family(
            _container_queries(service, namespace)
        )
        failed = [*span_failed, *container_failed]

        data: dict[str, Any] = {
            "service": service,
            "namespace": namespace,
            "window_minutes": window_minutes,
            "status": "success",
        }
        request_rate = span_values.get("request_rate")
        error_rate = span_values.get("error_rate")
        latency_p95 = span_values.get("latency_p95_ms")
        if request_rate is not None:
            data["request_rate"] = request_rate
        if error_rate is not None:
            data["error_rate"] = error_rate
        elif request_rate is not None:
            data["error_rate"] = 0.0
        if latency_p95 is not None:
            data["latency_p95_ms"] = latency_p95

        _add_container_metrics(data, container_values)

        span_complete = request_rate is not None and latency_p95 is not None
        container_present = any(
            key in data for key in ("memory_ratio", "memory_working_set_mb", "cpu_cores")
        )
        if not any(key in data for key in _OBSERVATION_KEYS):
            reason = (
                f"requêtes en échec : {', '.join(failed)}" if failed else "aucune série trouvée"
            )
            raise MetricsUnavailableError(
                f"Aucune métrique Prometheus pour le service {service!r} ({reason})."
            )
        if failed:
            data["failed"] = failed
        if failed or not span_complete or not container_present:
            data["status"] = "partial"
        return data
