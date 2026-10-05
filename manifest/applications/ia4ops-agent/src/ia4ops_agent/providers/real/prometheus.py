"""
Provider Prometheus réel — squelette (Task 8).

Endpoint : https://grafana.<IP>.sslip.io/api/datasources/proxy/uid/prometheus/api/v1/query_range
Auth     : Basic auth admin:<password> via GRAFANA_USER / GRAFANA_PASSWORD
"""

from typing import Any

from ia4ops_agent.providers.interfaces import MetricsUnavailableError


class PrometheusProvider:
    """Implémentation réelle de MetricsProvider via le proxy Grafana → Prometheus."""

    async def get_service_metrics(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "PrometheusProvider non implémenté — utiliser LLM_PROVIDER=mock. "
            "Voir providers/real/README.md pour les variables de configuration."
        )
