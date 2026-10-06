"""
Provider Kubernetes réel — squelette (Task 8).

Accès : API Kubernetes in-cluster ou via kubeconfig
RBAC  : ServiceAccount read-only sur pods, events, deployments dans otel-demo
"""

from typing import Any


class KubernetesProvider:
    """Implémentation réelle de ClusterProvider via l'API Kubernetes."""

    async def get_workload_status(
        self,
        service: str,
        namespace: str,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "KubernetesProvider non implémenté — utiliser LLM_PROVIDER=mock. "
            "Voir providers/real/README.md pour les variables de configuration."
        )

    async def get_cluster_events(
        self,
        namespace: str,
        service: str,
        window_minutes: int = 15,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "KubernetesProvider non implémenté — utiliser LLM_PROVIDER=mock. "
            "Voir providers/real/README.md pour les variables de configuration."
        )
