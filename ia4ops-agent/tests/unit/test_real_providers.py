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


async def test_prometheus_provider_queries_and_normalizes_metrics() -> None:
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/prometheus/api/v1/query")
        assert request.headers["authorization"] == "Basic dGVzdC11c2VyOnRlc3QtcGFzc3dvcmQ="
        query = request.url.params["query"]
        queries.append(query)
        if "STATUS_CODE_ERROR" in query:
            return _prometheus_response("0.08")
        if "histogram_quantile" in query:
            return _prometheus_response("72.5")
        return _prometheus_response("12.0")

    provider = PrometheusProvider(transport=httpx.MockTransport(handler))
    result = await provider.get_service_metrics("product-catalog", "otel-demo", 5)

    assert result == {
        "service": "product-catalog",
        "namespace": "otel-demo",
        "window_minutes": 5,
        "status": "success",
        "request_rate": 12.0,
        "error_rate": 0.08,
        "latency_p95_ms": 72.5,
    }
    assert len(queries) == 3
    assert all('service_name="product-catalog"' in query for query in queries)
    assert all("[5m]" in query for query in queries)


async def test_prometheus_provider_treats_absent_error_series_as_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        if "STATUS_CODE_ERROR" in query:
            return _prometheus_response(None)
        if "histogram_quantile" in query:
            return _prometheus_response("72.5")
        return _prometheus_response("12.0")

    provider = PrometheusProvider(transport=httpx.MockTransport(handler))
    result = await provider.get_service_metrics("product-catalog", "otel-demo")

    assert result["status"] == "success"
    assert result["error_rate"] == 0.0
    assert result["request_rate"] == 12.0
    assert result["latency_p95_ms"] == 72.5


async def test_prometheus_provider_marks_missing_latency_partial() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        if "histogram_quantile" in query:
            return _prometheus_response(None)
        if "STATUS_CODE_ERROR" in query:
            return _prometheus_response("0.08")
        return _prometheus_response("12.0")

    provider = PrometheusProvider(transport=httpx.MockTransport(handler))
    result = await provider.get_service_metrics("product-catalog", "otel-demo")

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
