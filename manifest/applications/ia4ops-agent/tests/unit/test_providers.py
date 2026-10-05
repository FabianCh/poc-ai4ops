"""
Tests unitaires — providers mockés (Task 3).

Couvre :
- MockMetricsProvider : structure de sortie, valeurs par service, window override
- MockLogsProvider : structure de sortie, cas C lève LogsUnavailableError, limit
- MockClusterProvider : structure de sortie, cas C status=partial, events
- Factory Providers : mock() retourne bien des instances mock, from_env() avec LLM_PROVIDER=mock
- Conformité Protocol (isinstance checks runtime_checkable)
"""


import pytest

from ia4ops_agent.providers.factory import Providers
from ia4ops_agent.providers.interfaces import (
    ClusterProvider,
    LogsProvider,
    LogsUnavailableError,
    MetricsProvider,
)
from ia4ops_agent.providers.mock.cluster import MockClusterProvider
from ia4ops_agent.providers.mock.logs import MockLogsProvider
from ia4ops_agent.providers.mock.metrics import MockMetricsProvider

# ---------------------------------------------------------------------------
# Tests MockMetricsProvider
# ---------------------------------------------------------------------------


class TestMockMetricsProvider:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(MockMetricsProvider(), MetricsProvider)

    async def test_case_a_product_catalog(self) -> None:
        provider = MockMetricsProvider()
        result = await provider.get_service_metrics("product-catalog", "otel-demo")
        assert result["status"] == "success"
        assert result["error_rate"] == pytest.approx(0.18)
        assert result["latency_p95_ms"] == pytest.approx(4200.0)

    async def test_case_b_checkout(self) -> None:
        provider = MockMetricsProvider()
        result = await provider.get_service_metrics("checkout", "otel-demo")
        assert result["status"] == "success"
        assert result["error_rate"] == pytest.approx(0.31)

    async def test_case_c_frontend(self) -> None:
        provider = MockMetricsProvider()
        result = await provider.get_service_metrics("frontend", "otel-demo")
        # Cas C : métriques disponibles (seuls logs/cluster manquent)
        assert result["status"] == "success"
        assert "error_rate" in result

    async def test_unknown_service_returns_defaults(self) -> None:
        provider = MockMetricsProvider()
        result = await provider.get_service_metrics("unknown-service", "otel-demo")
        assert result["status"] == "success"
        assert result["error_rate"] == pytest.approx(0.01)

    async def test_window_minutes_override(self) -> None:
        provider = MockMetricsProvider()
        result = await provider.get_service_metrics(
            "product-catalog", "otel-demo", window_minutes=5
        )
        assert result["window_minutes"] == 5

    async def test_required_keys_present(self) -> None:
        provider = MockMetricsProvider()
        result = await provider.get_service_metrics("product-catalog", "otel-demo")
        for key in ("error_rate", "latency_p95_ms", "window_minutes", "status"):
            assert key in result, f"Clé manquante : {key}"

    async def test_namespace_ignored_in_mock(self) -> None:
        """Le mock ignore le namespace — comportement attendu."""
        provider = MockMetricsProvider()
        r1 = await provider.get_service_metrics("product-catalog", "otel-demo")
        r2 = await provider.get_service_metrics("product-catalog", "autre-namespace")
        assert r1["error_rate"] == r2["error_rate"]


# ---------------------------------------------------------------------------
# Tests MockLogsProvider
# ---------------------------------------------------------------------------


class TestMockLogsProvider:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(MockLogsProvider(), LogsProvider)

    async def test_case_a_returns_timeout_logs(self) -> None:
        provider = MockLogsProvider()
        logs = await provider.get_recent_errors("product-catalog", "otel-demo")
        assert len(logs) > 0
        messages = [l["message"] for l in logs]
        assert any("timeout" in m.lower() or "redis" in m.lower() for m in messages)

    async def test_case_a_log_structure(self) -> None:
        provider = MockLogsProvider()
        logs = await provider.get_recent_errors("product-catalog", "otel-demo")
        for log in logs:
            assert "event_id" in log
            assert "timestamp" in log
            assert "level" in log
            assert "message" in log
            assert "service" in log

    async def test_case_b_returns_oom_logs(self) -> None:
        provider = MockLogsProvider()
        logs = await provider.get_recent_errors("checkout", "otel-demo")
        assert len(logs) > 0
        messages = [l["message"] for l in logs]
        assert any("oom" in m.lower() or "137" in m or "crash" in m.lower() for m in messages)

    async def test_case_c_raises_logs_unavailable(self) -> None:
        """Cas C : LogsUnavailableError doit être levée pour 'frontend'."""
        provider = MockLogsProvider()
        with pytest.raises(LogsUnavailableError) as exc_info:
            await provider.get_recent_errors("frontend", "otel-demo")
        assert exc_info.value.provider == "logs"

    async def test_case_c_is_provider_unavailable_subclass(self) -> None:
        """LogsUnavailableError doit hériter de ProviderUnavailableError."""
        from ia4ops_agent.providers.interfaces import ProviderUnavailableError
        provider = MockLogsProvider()
        with pytest.raises(ProviderUnavailableError):
            await provider.get_recent_errors("frontend", "otel-demo")

    async def test_limit_is_respected(self) -> None:
        provider = MockLogsProvider()
        logs = await provider.get_recent_errors("product-catalog", "otel-demo", limit=2)
        assert len(logs) <= 2

    async def test_unknown_service_returns_empty(self) -> None:
        provider = MockLogsProvider()
        logs = await provider.get_recent_errors("unknown-service", "otel-demo")
        assert logs == []


# ---------------------------------------------------------------------------
# Tests MockClusterProvider
# ---------------------------------------------------------------------------


class TestMockClusterProvider:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(MockClusterProvider(), ClusterProvider)

    async def test_case_a_workload_stable(self) -> None:
        provider = MockClusterProvider()
        result = await provider.get_workload_status("product-catalog", "otel-demo")
        assert result["status"] == "success"
        assert result["desired_replicas"] == result["ready_replicas"]
        assert result["restart_count"] == 0

    async def test_case_b_workload_unstable(self) -> None:
        provider = MockClusterProvider()
        result = await provider.get_workload_status("checkout", "otel-demo")
        assert result["status"] == "success"
        assert result["ready_replicas"] < result["desired_replicas"]
        assert result["restart_count"] > 0

    async def test_case_c_workload_partial(self) -> None:
        """Cas C : status doit être 'partial' pour 'frontend'."""
        provider = MockClusterProvider()
        result = await provider.get_workload_status("frontend", "otel-demo")
        assert result["status"] == "partial"
        assert result["desired_replicas"] is None
        assert result["ready_replicas"] is None

    async def test_case_a_no_events(self) -> None:
        provider = MockClusterProvider()
        events = await provider.get_cluster_events("otel-demo", "product-catalog")
        assert events == []

    async def test_case_b_has_warning_events(self) -> None:
        provider = MockClusterProvider()
        events = await provider.get_cluster_events("otel-demo", "checkout")
        assert len(events) > 0
        types = [e["type"] for e in events]
        assert "Warning" in types

    async def test_case_b_event_structure(self) -> None:
        provider = MockClusterProvider()
        events = await provider.get_cluster_events("otel-demo", "checkout")
        for evt in events:
            assert "type" in evt
            assert "reason" in evt
            assert "message" in evt
            assert "timestamp" in evt
            assert "object" in evt

    async def test_case_c_no_events(self) -> None:
        provider = MockClusterProvider()
        events = await provider.get_cluster_events("otel-demo", "frontend")
        assert events == []

    async def test_workload_status_structure(self) -> None:
        provider = MockClusterProvider()
        result = await provider.get_workload_status("product-catalog", "otel-demo")
        for key in ("desired_replicas", "ready_replicas", "restart_count", "pod_statuses", "status"):
            assert key in result, f"Clé manquante : {key}"


# ---------------------------------------------------------------------------
# Tests Factory Providers
# ---------------------------------------------------------------------------


class TestProvidersFactory:
    def test_mock_classmethod_returns_mock_instances(self) -> None:
        providers = Providers.mock()
        assert isinstance(providers.metrics, MockMetricsProvider)
        assert isinstance(providers.logs, MockLogsProvider)
        assert isinstance(providers.cluster, MockClusterProvider)

    def test_from_env_with_mock_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        providers = Providers.from_env()
        assert isinstance(providers.metrics, MockMetricsProvider)
        assert isinstance(providers.logs, MockLogsProvider)
        assert isinstance(providers.cluster, MockClusterProvider)

    def test_providers_satisfy_protocols(self) -> None:
        providers = Providers.mock()
        assert isinstance(providers.metrics, MetricsProvider)
        assert isinstance(providers.logs, LogsProvider)
        assert isinstance(providers.cluster, ClusterProvider)

    def test_custom_injection(self) -> None:
        """On peut injecter des providers arbitraires pour les tests."""
        custom_metrics = MockMetricsProvider()
        providers = Providers(metrics=custom_metrics)
        assert providers.metrics is custom_metrics
        # Les autres sont résolus depuis l'env
        assert providers.logs is not None
        assert providers.cluster is not None

    async def test_mock_providers_are_functional(self) -> None:
        """Smoke test : les providers mockés répondent sans erreur."""
        providers = Providers.mock()
        metrics = await providers.metrics.get_service_metrics("product-catalog", "otel-demo")
        logs = await providers.logs.get_recent_errors("product-catalog", "otel-demo")
        workload = await providers.cluster.get_workload_status("product-catalog", "otel-demo")
        assert metrics["status"] == "success"
        assert isinstance(logs, list)
        assert workload["status"] == "success"
