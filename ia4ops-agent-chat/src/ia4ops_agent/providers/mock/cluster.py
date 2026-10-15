"""
Provider de données cluster Kubernetes mocké.

Cas particulier :
  "frontend" (cas C) → get_workload_status retourne status "partial"
                        pour tester le branch partial du workflow.

Mapping service → scénario :
  "product-catalog" → cas A : workload stable, pas de redémarrages
  "checkout"        → cas B : pod non-ready, redémarrages fréquents, events Warning
  "frontend"        → cas C : données partielles (API K8s dégradée simulée)
"""

from typing import Any

from ia4ops_agent.providers.interfaces import ClusterProvider

# Cas A : workload stable
_WORKLOAD_CASE_A: dict[str, Any] = {
    "desired_replicas": 2,
    "ready_replicas": 2,
    "restart_count": 0,
    "pod_statuses": [
        {"name": "product-catalog-abc-001", "phase": "Running", "ready": True},
        {"name": "product-catalog-abc-002", "phase": "Running", "ready": True},
    ],
    "status": "success",
}

_EVENTS_CASE_A: list[dict[str, Any]] = []  # Pas d'événements anormaux

# Cas B : pod instable, CrashLoopBackOff
_WORKLOAD_CASE_B: dict[str, Any] = {
    "desired_replicas": 2,
    "ready_replicas": 1,
    "restart_count": 7,
    "pod_statuses": [
        {"name": "checkout-7d4f9b-xk2pq", "phase": "CrashLoopBackOff", "ready": False},
        {"name": "checkout-7d4f9b-mn9rs", "phase": "Running", "ready": True},
    ],
    "status": "success",
}

_EVENTS_CASE_B: list[dict[str, Any]] = [
    {
        "type": "Warning",
        "reason": "BackOff",
        "message": "Back-off restarting failed container checkout in pod checkout-7d4f9b-xk2pq",
        "timestamp": "2026-10-02T19:06:05Z",
        "object": "pod/checkout-7d4f9b-xk2pq",
    },
    {
        "type": "Warning",
        "reason": "OOMKilling",
        "message": "Memory limit reached, killed process in container checkout",
        "timestamp": "2026-10-02T19:05:02Z",
        "object": "pod/checkout-7d4f9b-xk2pq",
    },
]

# Cas C : données partielles (API K8s répond mais incomplète)
_WORKLOAD_CASE_C: dict[str, Any] = {
    "desired_replicas": None,   # indisponible
    "ready_replicas": None,     # indisponible
    "restart_count": 0,
    "pod_statuses": [],
    "status": "partial",        # signal explicite au workflow
}

_EVENTS_CASE_C: list[dict[str, Any]] = []  # Pas d'événements récupérables


_WORKLOADS: dict[str, dict[str, Any]] = {
    "product-catalog": _WORKLOAD_CASE_A,
    "checkout": _WORKLOAD_CASE_B,
    "frontend": _WORKLOAD_CASE_C,
}

_EVENTS: dict[str, list[dict[str, Any]]] = {
    "product-catalog": _EVENTS_CASE_A,
    "checkout": _EVENTS_CASE_B,
    "frontend": _EVENTS_CASE_C,
}

_DEFAULT_WORKLOAD: dict[str, Any] = {
    "desired_replicas": 1,
    "ready_replicas": 1,
    "restart_count": 0,
    "pod_statuses": [],
    "status": "success",
}


class MockClusterProvider:
    """
    Implémentation mock de ClusterProvider.

    Pour "frontend" (cas C), retourne un statut "partial" dans workload_status
    afin de tester le comportement du workflow quand l'API K8s est dégradée.
    """

    async def get_workload_status(
        self,
        service: str,
        namespace: str,
    ) -> dict[str, Any]:
        return _WORKLOADS.get(service, _DEFAULT_WORKLOAD).copy()

    async def get_cluster_events(
        self,
        namespace: str,
        service: str,
        window_minutes: int = 15,
    ) -> list[dict[str, Any]]:
        return _EVENTS.get(service, [])


# Vérification statique que MockClusterProvider satisfait le Protocol
assert isinstance(MockClusterProvider(), ClusterProvider)
