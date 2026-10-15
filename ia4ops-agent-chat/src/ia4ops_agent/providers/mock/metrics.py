"""
Provider de métriques mocké — retourne des données synthétiques par service.

Mapping service → scénario :
  "product-catalog" → cas A (taux d'erreur élevé, latence haute)
  "checkout"        → cas B (métriques dégradées, pod instable)
  "frontend"        → cas C (métriques disponibles, mais logs/cluster partiels)
  tout autre        → données neutres

Ne lève jamais MetricsUnavailableError — le mock métriques est toujours disponible.
C'est intentionnel : le cas C teste l'indisponibilité des logs et du cluster, pas des métriques.
"""

from typing import Any

from ia4ops_agent.providers.interfaces import MetricsProvider

# Mapping service → données synthétiques
_METRICS_BY_SERVICE: dict[str, dict[str, Any]] = {
    # Cas A : dépendance indisponible — taux d'erreur élevé, latence haute
    "product-catalog": {
        "error_rate": 0.18,
        "latency_p95_ms": 4200.0,
        "cpu_ratio": 0.42,
        "memory_ratio": 0.55,
        "request_rate": 120.0,
        "window_minutes": 15,
        "status": "success",
    },
    # Cas B : pod instable — erreurs élevées, CPU modéré
    "checkout": {
        "error_rate": 0.31,
        "latency_p95_ms": 2800.0,
        "cpu_ratio": 0.38,
        "memory_ratio": 0.72,
        "request_rate": 85.0,
        "window_minutes": 15,
        "status": "success",
    },
    # Cas C : données métriques disponibles (seuls logs + cluster manquent)
    "frontend": {
        "error_rate": 0.09,
        "latency_p95_ms": 1500.0,
        "cpu_ratio": 0.21,
        "memory_ratio": 0.44,
        "request_rate": 200.0,
        "window_minutes": 15,
        "status": "success",
    },
}

_DEFAULT_METRICS: dict[str, Any] = {
    "error_rate": 0.01,
    "latency_p95_ms": 120.0,
    "cpu_ratio": 0.10,
    "memory_ratio": 0.30,
    "request_rate": 50.0,
    "window_minutes": 15,
    "status": "success",
}


class MockMetricsProvider:
    """
    Implémentation mock de MetricsProvider.
    Retourne des données synthétiques selon le nom du service.
    Conforme au Protocol MetricsProvider (duck typing vérifié par runtime_checkable).
    """

    async def get_service_metrics(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
    ) -> dict[str, Any]:
        data = _METRICS_BY_SERVICE.get(service, _DEFAULT_METRICS).copy()
        data["window_minutes"] = window_minutes
        return data


# Vérification statique que MockMetricsProvider satisfait le Protocol
assert isinstance(MockMetricsProvider(), MetricsProvider)
