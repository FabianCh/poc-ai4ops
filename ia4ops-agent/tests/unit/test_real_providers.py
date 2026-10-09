"""Tests des adaptateurs Prometheus et Loki via réponses HTTP simulées."""

import json

import httpx
import pytest

from ia4ops_agent.config import settings
from ia4ops_agent.providers.interfaces import (
    ClusterUnavailableError,
    LogsUnavailableError,
    MetricsUnavailableError,
)
from ia4ops_agent.providers.real.kubernetes import KubernetesProvider
from ia4ops_agent.providers.real.loki import LokiProvider
from ia4ops_agent.providers.real.prometheus import PrometheusProvider


@pytest.fixture(autouse=True)
def grafana_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "grafana_base_url", "https://grafana.example.test/")
    monkeypatch.setattr(settings, "grafana_username", "test-user")
    monkeypatch.setattr(settings, "grafana_password", "test-password")


def _prometheus_response(value: str | None, request: httpx.Request | None = None) -> httpx.Response:
    result = []
    if value is not None:
        result = [{"metric": {}, "value": [1_791_390_000, value]}]
    return httpx.Response(
        200,
        json={"status": "success", "data": {"resultType": "vector", "result": result}},
        request=request,
    )


_SPAN_ANSWERS: dict[str, str | None] = {"error_rate": "0.08", "request_rate": "12.0",
                                          "latency_p95_ms": "72.5"}
_CONTAINER_ANSWERS: dict[str, str | None] = {
    "memory_ratio": "0.5", "memory_working_set_bytes": str(256 * 1024 * 1024),
    "memory_limit_bytes": str(512 * 1024 * 1024), "cpu_cores": "0.25", "cpu_limit_cores": None,
    "restarts_10m": "0", "oom_last_terminated": None,
}


def _query_name(query: str) -> str:
    """Identifie la requête du provider (le contenu des requêtes est vérifié par ailleurs)."""
    if "STATUS_CODE_ERROR" in query:
        return "error_rate"
    if "histogram_quantile" in query:
        return "latency_p95_ms"
    if "traces_span_metrics_calls_total" in query:
        return "request_rate"
    if "last_terminated_reason" in query:
        return "oom_last_terminated"
    if "restarts_total" in query:
        return "restarts_10m"
    if "container_cpu_usage" in query:
        return "cpu_cores"
    if 'resource="cpu"' in query:
        return "cpu_limit_cores"
    if "/ on (" in query:
        return "memory_ratio"
    if "container_memory_working_set_bytes" in query:
        return "memory_working_set_bytes"
    return "memory_limit_bytes"


def _prom_provider(
    overrides: dict[str, str | None] | None = None,
    *,
    failing: set[str] | None = None,
    queries: list[str] | None = None,
) -> PrometheusProvider:
    """Provider dont chaque requête répond selon son nom ; `failing` → HTTP 500."""
    answers = {**_SPAN_ANSWERS, **_CONTAINER_ANSWERS, **(overrides or {})}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Basic dGVzdC11c2VyOnRlc3QtcGFzc3dvcmQ="
        query = request.url.params["query"]
        if queries is not None:
            queries.append(query)
        name = _query_name(query)
        if failing and name in failing:
            return httpx.Response(500, text="boom", request=request)
        return _prometheus_response(answers[name], request)

    return PrometheusProvider(transport=httpx.MockTransport(handler))


async def test_prometheus_provider_queries_and_normalizes_metrics() -> None:
    queries: list[str] = []
    provider = _prom_provider(queries=queries)
    result = await provider.get_service_metrics("product-catalog", "otel-demo", 5)

    assert result == {
        "service": "product-catalog",
        "namespace": "otel-demo",
        "window_minutes": 5,
        "status": "success",
        "request_rate": 12.0,
        "error_rate": 0.08,
        "latency_p95_ms": 72.5,
        "memory_ratio": 0.5,
        "memory_working_set_mb": 256.0,
        "memory_limit_mb": 512.0,
        "cpu_cores": 0.25,
        "restarts_10m": 0,
        "oom_killed": False,
    }
    span_queries = [q for q in queries if "traces_span_metrics" in q]
    assert len(span_queries) == 3
    assert all('service_name="product-catalog"' in q and "[5m]" in q for q in span_queries)
    container_queries = [q for q in queries if "traces_span_metrics" not in q]
    assert len(container_queries) == 7
    assert all('container="product-catalog"' in q for q in container_queries)
    assert all('namespace="otel-demo"' in q for q in container_queries)


async def test_prometheus_memory_ratio_is_computed_pod_by_pod() -> None:
    queries: list[str] = []
    await _prom_provider(queries=queries).get_service_metrics("recommendation", "otel-demo")

    ratio = next(q for q in queries if _query_name(q) == "memory_ratio")
    # même granularité que la règle OtelDemoContainerMemoryNearLimit
    assert "on (namespace, pod, container)" in ratio
    assert ratio.count("max by (namespace, pod, container)") == 2


async def test_prometheus_oom_requires_recent_restart_and_oomkilled_reason() -> None:
    result = await _prom_provider({"restarts_10m": "2", "oom_last_terminated": "1"}) \
        .get_service_metrics("recommendation", "otel-demo")
    assert result["restarts_10m"] == 2
    assert result["oom_killed"] is True

    # OOMKilled ancien : la dernière terminaison l'indique, mais aucun redémarrage récent
    old = await _prom_provider({"restarts_10m": "0", "oom_last_terminated": "1"}) \
        .get_service_metrics("recommendation", "otel-demo")
    assert old["oom_killed"] is False


async def test_prometheus_cpu_ratio_absent_without_cpu_limit() -> None:
    result = await _prom_provider({"cpu_cores": "0.8"}).get_service_metrics("ad", "otel-demo")
    assert result["cpu_cores"] == 0.8
    assert "cpu_ratio" not in result

    limited = await _prom_provider({"cpu_cores": "0.5", "cpu_limit_cores": "1"}) \
        .get_service_metrics("ad", "otel-demo")
    assert limited["cpu_ratio"] == 0.5


async def test_prometheus_provider_container_only_service_is_partial() -> None:
    """load-generator : pas de spanmetrics, mais des métriques de conteneur exploitables."""
    spanless = {"error_rate": None, "request_rate": None, "latency_p95_ms": None}
    result = await _prom_provider(spanless).get_service_metrics("load-generator", "otel-demo")

    assert result["status"] == "partial"
    assert result["memory_ratio"] == 0.5
    assert "request_rate" not in result
    assert "error_rate" not in result
    assert "failed" not in result


async def test_prometheus_provider_keeps_container_data_when_spanmetrics_fail() -> None:
    provider = _prom_provider(failing={"error_rate", "request_rate", "latency_p95_ms"})
    result = await provider.get_service_metrics("checkout", "otel-demo")

    assert result["status"] == "partial"
    assert result["memory_ratio"] == 0.5
    assert sorted(result["failed"]) == ["error_rate", "latency_p95_ms", "request_rate"]
    assert "request_rate" not in result


async def test_prometheus_provider_keeps_spanmetrics_when_container_queries_fail() -> None:
    failing = set(_CONTAINER_ANSWERS)
    result = await _prom_provider(failing=failing).get_service_metrics("checkout", "otel-demo")

    assert result["status"] == "partial"
    assert result["request_rate"] == 12.0
    assert result["error_rate"] == 0.08
    assert "memory_ratio" not in result
    assert set(result["failed"]) == failing


async def test_prometheus_provider_treats_absent_error_series_as_zero() -> None:
    result = await _prom_provider({"error_rate": None}).get_service_metrics(
        "product-catalog", "otel-demo"
    )

    assert result["status"] == "success"
    assert result["error_rate"] == 0.0
    assert result["request_rate"] == 12.0
    assert result["latency_p95_ms"] == 72.5


async def test_prometheus_provider_marks_missing_latency_partial() -> None:
    result = await _prom_provider({"latency_p95_ms": None}).get_service_metrics(
        "product-catalog", "otel-demo"
    )

    assert result["status"] == "partial"
    assert result["error_rate"] == 0.08
    assert result["request_rate"] == 12.0
    assert "latency_p95_ms" not in result


async def test_prometheus_provider_marks_absent_series_unavailable() -> None:
    provider = PrometheusProvider(
        transport=httpx.MockTransport(lambda request: _prometheus_response(None, request=request))
    )

    with pytest.raises(MetricsUnavailableError, match="Aucune métrique"):
        await provider.get_service_metrics("unknown-service", "otel-demo")


async def test_prometheus_provider_reports_api_errors() -> None:
    provider = PrometheusProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, text="unavailable", request=request)
        )
    )

    with pytest.raises(MetricsUnavailableError, match="Prometheus"):
        await provider.get_service_metrics("product-catalog", "otel-demo")


async def test_prometheus_provider_requires_grafana_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "grafana_base_url", None)

    provider = PrometheusProvider()
    with pytest.raises(MetricsUnavailableError, match="GRAFANA_BASE_URL"):
        await provider.get_service_metrics("product-catalog", "otel-demo")


async def test_loki_provider_queries_and_normalizes_streams() -> None:
    request_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_params.update(dict(request.url.params))
        assert request.url.path.endswith("/loki/api/v1/query_range")
        assert request.headers["authorization"] == "Basic dGVzdC11c2VyOnRlc3QtcGFzc3dvcmQ="
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "streams",
                    "result": [
                        {
                            "stream": {
                                "service_name": "product-catalog",
                                "k8s_namespace_name": "otel-demo",
                                "detected_level": "ERROR",
                            },
                            "values": [
                                [
                                    "1791390000000000000",
                                    json.dumps(
                                        {
                                            "level": "error",
                                            "message": "redis connection timeout",
                                        }
                                    ),
                                ],
                                ["1791390001000000000", "database connection refused"],
                            ],
                        }
                    ],
                },
            },
        )

    provider = LokiProvider(transport=httpx.MockTransport(handler))
    logs = await provider.get_recent_errors(
        "product-catalog", "otel-demo", window_minutes=5, limit=1
    )

    assert len(logs) == 1
    assert logs[0]["event_id"].startswith("loki-")
    assert logs[0]["timestamp"] == "2026-10-07T16:20:00+00:00"
    assert logs[0]["level"] == "error"
    assert logs[0]["message"] == "redis connection timeout"
    assert logs[0]["service"] == "product-catalog"
    assert 'service_name="product-catalog"' in request_params["query"]
    assert 'k8s_namespace_name="otel-demo"' in request_params["query"]
    assert 'detected_level=~"(?i)(error|fatal|critical|warn(?:ing)?)"' in request_params["query"]
    assert request_params["direction"] == "backward"
    assert request_params["limit"] == "1"


async def test_loki_provider_returns_empty_when_no_matching_logs() -> None:
    provider = LokiProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"resultType": "streams", "result": []},
                },
                request=request,
            )
        )
    )

    assert await provider.get_recent_errors("product-catalog", "otel-demo") == []


async def test_loki_provider_reports_api_errors() -> None:
    provider = LokiProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, text="unavailable", request=request)
        )
    )

    with pytest.raises(LogsUnavailableError, match="Loki"):
        await provider.get_recent_errors("product-catalog", "otel-demo")


async def test_loki_provider_requires_grafana_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "grafana_password", None)

    provider = LokiProvider()
    with pytest.raises(LogsUnavailableError, match="GRAFANA_PASSWORD"):
        await provider.get_recent_errors("product-catalog", "otel-demo")


async def test_kubernetes_provider_reports_out_of_scope_data() -> None:
    provider = KubernetesProvider()

    with pytest.raises(ClusterUnavailableError, match="hors du périmètre"):
        await provider.get_workload_status("product-catalog", "otel-demo")
    with pytest.raises(ClusterUnavailableError, match="hors du périmètre"):
        await provider.get_cluster_events("otel-demo", "product-catalog")
