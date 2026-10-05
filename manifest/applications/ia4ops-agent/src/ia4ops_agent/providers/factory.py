"""
Factory de providers — sélectionne mock ou real selon la configuration.

Principe : le workflow ne connaît que les interfaces (Protocols).
La factory résout les dépendances concrètes au démarrage de l'application.

Variable de contrôle : LLM_PROVIDER (dans .env)
  "mock"   → MockMetricsProvider, MockLogsProvider, MockClusterProvider
  "gemini" → PrometheusProvider, LokiProvider, KubernetesProvider (Task 8)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ia4ops_agent.providers.interfaces import (
        ClusterProvider,
        LogsProvider,
        MetricsProvider,
    )


def _get_provider_mode() -> str:
    """Lit LLM_PROVIDER depuis l'environnement. Défaut : 'mock'."""
    return os.environ.get("LLM_PROVIDER", "mock").lower().strip()


def get_metrics_provider() -> MetricsProvider:
    """Retourne le MetricsProvider approprié selon LLM_PROVIDER."""
    mode = _get_provider_mode()
    if mode == "mock":
        from ia4ops_agent.providers.mock.metrics import MockMetricsProvider
        return MockMetricsProvider()

    # mode == "gemini" ou autre → real providers (implémentés en Task 8)
    from ia4ops_agent.providers.real.prometheus import PrometheusProvider
    return PrometheusProvider()


def get_logs_provider() -> LogsProvider:
    """Retourne le LogsProvider approprié selon LLM_PROVIDER."""
    mode = _get_provider_mode()
    if mode == "mock":
        from ia4ops_agent.providers.mock.logs import MockLogsProvider
        return MockLogsProvider()

    from ia4ops_agent.providers.real.loki import LokiProvider
    return LokiProvider()


def get_cluster_provider() -> ClusterProvider:
    """Retourne le ClusterProvider approprié selon LLM_PROVIDER."""
    mode = _get_provider_mode()
    if mode == "mock":
        from ia4ops_agent.providers.mock.cluster import MockClusterProvider
        return MockClusterProvider()

    from ia4ops_agent.providers.real.kubernetes import KubernetesProvider
    return KubernetesProvider()


class Providers:
    """
    Conteneur de providers instanciés — passé aux nœuds du graphe via la config.
    Permet de tester en injectant des providers arbitraires sans toucher à l'env.
    """

    def __init__(
        self,
        metrics: MetricsProvider | None = None,
        logs: LogsProvider | None = None,
        cluster: ClusterProvider | None = None,
    ) -> None:
        self.metrics = metrics or get_metrics_provider()
        self.logs = logs or get_logs_provider()
        self.cluster = cluster or get_cluster_provider()

    @classmethod
    def from_env(cls) -> Providers:
        """Crée les providers depuis la configuration d'environnement."""
        return cls()

    @classmethod
    def mock(cls) -> Providers:
        """Crée systématiquement des providers mockés (utile dans les tests)."""
        from ia4ops_agent.providers.mock.cluster import MockClusterProvider
        from ia4ops_agent.providers.mock.logs import MockLogsProvider
        from ia4ops_agent.providers.mock.metrics import MockMetricsProvider

        return cls(
            metrics=MockMetricsProvider(),
            logs=MockLogsProvider(),
            cluster=MockClusterProvider(),
        )
