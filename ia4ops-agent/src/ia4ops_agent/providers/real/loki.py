"""
Provider Loki réel — squelette (Task 8).

Endpoint : https://grafana.<IP>.sslip.io/api/datasources/proxy/uid/loki/loki/api/v1/query_range
Auth     : Basic auth admin:<password> via GRAFANA_USER / GRAFANA_PASSWORD
"""

from typing import Any


class LokiProvider:
    """Implémentation réelle de LogsProvider via le proxy Grafana → Loki."""

    async def get_recent_errors(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "LokiProvider non implémenté — utiliser DATA_PROVIDER=mock. "
            "Voir providers/real/README.md pour les variables de configuration."
        )
