"""Configuration partagée pour les proxies de datasource Grafana."""

from ia4ops_agent.config import settings


class GrafanaConfigurationError(ValueError):
    """Erreur d'environnement nécessaire pour interroger les proxies Grafana."""


def grafana_connection() -> tuple[str, tuple[str, str]]:
    """Retourne la base URL et l'auth Basic, ou échoue sans exposer de secrets."""
    if not settings.grafana_base_url:
        raise GrafanaConfigurationError("GRAFANA_BASE_URL n'est pas configurée.")
    if not settings.grafana_password:
        raise GrafanaConfigurationError("GRAFANA_PASSWORD n'est pas configuré.")
    return (
        settings.grafana_base_url.rstrip("/"),
        (settings.grafana_username, settings.grafana_password),
    )
