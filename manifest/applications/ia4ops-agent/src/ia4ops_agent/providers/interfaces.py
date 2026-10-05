"""
Interfaces (Protocols) pour les providers de données d'observabilité.

Le workflow LangGraph dépend uniquement de ces interfaces — jamais des
implémentations concrètes (mock ou réelles). Principe : Dependency Inversion.

Référence : ia4ops-scenario1-reference.md section 10.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MetricsProvider(Protocol):
    """
    Fournit les métriques d'un service sur une fenêtre temporelle.
    Implémentations : MockMetricsProvider, PrometheusProvider (Task 8).
    """

    async def get_service_metrics(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
    ) -> dict[str, Any]:
        """
        Retourne les métriques agrégées du service.

        Sortie attendue (toutes les clés sont optionnelles) :
        {
            "error_rate": float,        # 0.0–1.0
            "latency_p95_ms": float,
            "cpu_ratio": float,         # cœurs utilisés / limite
            "memory_ratio": float,      # mémoire utilisée / limite
            "request_rate": float,      # req/s
            "window_minutes": int,
            "status": "success" | "partial" | "unavailable" | "invalid",
        }
        """
        ...


@runtime_checkable
class LogsProvider(Protocol):
    """
    Fournit les logs d'erreur d'un service sur une fenêtre temporelle.
    Implémentations : MockLogsProvider, LokiProvider (Task 8).
    """

    async def get_recent_errors(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Retourne les logs d'erreur normalisés.

        Chaque entrée attendue :
        {
            "event_id": str,
            "timestamp": str,   # ISO 8601
            "level": str,       # "error" | "warn" | ...
            "message": str,
            "service": str,
        }

        En cas d'indisponibilité, lever LogsUnavailableError.
        """
        ...


@runtime_checkable
class ClusterProvider(Protocol):
    """
    Fournit l'état du workload Kubernetes et les événements cluster.
    Implémentations : MockClusterProvider, KubernetesProvider (Task 8).
    """

    async def get_workload_status(
        self,
        service: str,
        namespace: str,
    ) -> dict[str, Any]:
        """
        Retourne l'état du deployment/pod pour le service.

        Sortie attendue :
        {
            "desired_replicas": int,
            "ready_replicas": int,
            "restart_count": int,
            "pod_statuses": list[dict],
            "status": "success" | "partial" | "unavailable" | "invalid",
        }
        """
        ...

    async def get_cluster_events(
        self,
        namespace: str,
        service: str,
        window_minutes: int = 15,
    ) -> list[dict[str, Any]]:
        """
        Retourne les événements Kubernetes pertinents (Warning, BackOff, etc.).

        Chaque entrée attendue :
        {
            "type": str,        # "Warning" | "Normal"
            "reason": str,
            "message": str,
            "timestamp": str,   # ISO 8601
            "object": str,
        }
        """
        ...


# --- Exceptions métier pour les providers ---

class ProviderUnavailableError(Exception):
    """Levée quand une source de données est inaccessible."""

    def __init__(self, provider: str, reason: str = "") -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"Provider '{provider}' indisponible : {reason}")


class LogsUnavailableError(ProviderUnavailableError):
    """Spécialisation pour Loki/logs."""

    def __init__(self, reason: str = "") -> None:
        super().__init__("logs", reason)


class MetricsUnavailableError(ProviderUnavailableError):
    """Spécialisation pour Prometheus/métriques."""

    def __init__(self, reason: str = "") -> None:
        super().__init__("metrics", reason)


class ClusterUnavailableError(ProviderUnavailableError):
    """Spécialisation pour l'API Kubernetes."""

    def __init__(self, reason: str = "") -> None:
        super().__init__("cluster", reason)
