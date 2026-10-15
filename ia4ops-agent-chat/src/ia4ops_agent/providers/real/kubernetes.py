"""
Provider Kubernetes réel — squelette (Task 8).

Accès : API Kubernetes in-cluster ou via kubeconfig
RBAC  : ServiceAccount read-only sur pods, events, deployments dans otel-demo
"""

from typing import Any

from ia4ops_agent.providers.interfaces import ClusterUnavailableError


class KubernetesProvider:
    """Implémentation réelle de ClusterProvider via l'API Kubernetes."""

    async def get_workload_status(
        self,
        service: str,
        namespace: str,
    ) -> dict[str, Any]:
        raise ClusterUnavailableError(
            f"L'état Kubernetes de {service!r} dans {namespace!r} n'est pas collecté : "
            "le provider réel est hors du périmètre courant."
        )

    async def get_cluster_events(
        self,
        namespace: str,
        service: str,
        window_minutes: int = 15,
    ) -> list[dict[str, Any]]:
        raise ClusterUnavailableError(
            f"Les événements Kubernetes de {service!r} dans {namespace!r} "
            f"ne sont pas collectés ({window_minutes} min) : le provider réel "
            "est hors du périmètre courant."
        )
