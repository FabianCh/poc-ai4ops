"""Provider de traces mocké — synthèse d'erreurs synthétique par service.

Mapping service → scénario :
  "product-catalog" → cas A : erreurs de la dépendance, propagées jusqu'au frontend
  "checkout"        → cas B : échec de préparation de commande
  "frontend"        → cas C : Jaeger indisponible → TracesUnavailableError
  tout autre        → aucune trace en erreur
"""

from typing import Any

from ia4ops_agent.providers.interfaces import TracesProvider, TracesUnavailableError

_TRACES_BY_SERVICE: dict[str, dict[str, Any]] = {
    "product-catalog": {
        "error_trace_count": 14,
        "top_error_spans": [
            {
                "service": "product-catalog",
                "operation": "oteldemo.ProductCatalogService/GetProduct",
                "count": 14,
                "status_description": "timeout connecting to redis:6379 after 5000ms",
            },
            {
                "service": "checkout",
                "operation": "oteldemo.CheckoutService/PlaceOrder",
                "count": 9,
                "status_description": "failed to prepare order",
            },
        ],
        "services_in_error_chain": ["frontend", "checkout", "product-catalog"],
        "max_duration_ms": 5012.0,
        "sample_trace_ids": ["0123456789abcdef0123456789abcdef"],
    },
    "checkout": {
        "error_trace_count": 6,
        "top_error_spans": [
            {
                "service": "checkout",
                "operation": "oteldemo.CheckoutService/PlaceOrder",
                "count": 6,
                "status_description": "failed to initialize database connection pool",
            }
        ],
        "services_in_error_chain": ["frontend", "checkout"],
        "max_duration_ms": 1800.0,
        "sample_trace_ids": [],
    },
}

_NO_ERRORS: dict[str, Any] = {
    "error_trace_count": 0,
    "top_error_spans": [],
    "services_in_error_chain": [],
    "max_duration_ms": 0.0,
    "sample_trace_ids": [],
}


class MockTracesProvider:
    """Implémentation mock de TracesProvider."""

    async def get_error_traces(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
    ) -> dict[str, Any]:
        if service == "frontend":
            raise TracesUnavailableError(
                "Mock Jaeger indisponible pour le service 'frontend' (cas C simulé)."
            )
        summary = _TRACES_BY_SERVICE.get(service, _NO_ERRORS)
        return {
            "service": service,
            "namespace": namespace,
            "window_minutes": window_minutes,
            "status": "success",
            "truncated": False,
            **summary,
        }


assert isinstance(MockTracesProvider(), TracesProvider)
