"""
Provider de logs mocké — retourne des données synthétiques par service.

Cas particulier :
  "frontend" (cas C) → lève LogsUnavailableError pour tester le branch unavailable.

Mapping service → scénario :
  "product-catalog" → cas A : logs avec timeouts vers dépendance Redis
  "checkout"        → cas B : logs avec erreur de démarrage / OOMKilled
  "frontend"        → cas C : Loki indisponible → LogsUnavailableError
"""

from typing import Any

from ia4ops_agent.providers.interfaces import LogsProvider, LogsUnavailableError

# Cas A : timeouts répétés vers une dépendance
_LOGS_CASE_A: list[dict[str, Any]] = [
    {
        "event_id": "log-a-001",
        "timestamp": "2026-10-02T18:41:30Z",
        "level": "error",
        "message": "timeout connecting to redis:6379 after 5000ms",
        "service": "product-catalog",
    },
    {
        "event_id": "log-a-002",
        "timestamp": "2026-10-02T18:41:35Z",
        "level": "error",
        "message": "timeout connecting to redis:6379 after 5000ms",
        "service": "product-catalog",
    },
    {
        "event_id": "log-a-003",
        "timestamp": "2026-10-02T18:41:40Z",
        "level": "error",
        "message": "timeout connecting to redis:6379 after 5000ms",
        "service": "product-catalog",
    },
    {
        "event_id": "log-a-004",
        "timestamp": "2026-10-02T18:42:00Z",
        "level": "warn",
        "message": "retrying request to downstream service, attempt 3/3",
        "service": "product-catalog",
    },
    {
        "event_id": "log-a-005",
        "timestamp": "2026-10-02T18:42:10Z",
        "level": "error",
        "message": "all retries exhausted for redis connection pool",
        "service": "product-catalog",
    },
]

# Cas B : erreurs de démarrage et OOM
_LOGS_CASE_B: list[dict[str, Any]] = [
    {
        "event_id": "log-b-001",
        "timestamp": "2026-10-02T19:05:05Z",
        "level": "error",
        "message": "container checkout terminated with exit code 137 (OOMKilled)",
        "service": "checkout",
    },
    {
        "event_id": "log-b-002",
        "timestamp": "2026-10-02T19:05:20Z",
        "level": "error",
        "message": "failed to initialize database connection pool: connection refused",
        "service": "checkout",
    },
    {
        "event_id": "log-b-003",
        "timestamp": "2026-10-02T19:05:45Z",
        "level": "error",
        "message": "container checkout terminated with exit code 137 (OOMKilled)",
        "service": "checkout",
    },
    {
        "event_id": "log-b-004",
        "timestamp": "2026-10-02T19:06:00Z",
        "level": "warn",
        "message": "pod checkout-7d4f9b-xk2pq entering CrashLoopBackOff",
        "service": "checkout",
    },
]


_LOGS_BY_SERVICE: dict[str, list[dict[str, Any]]] = {
    "product-catalog": _LOGS_CASE_A,
    "checkout": _LOGS_CASE_B,
    # "frontend" est absent volontairement → déclenche LogsUnavailableError
}

_DEFAULT_LOGS: list[dict[str, Any]] = []


class MockLogsProvider:
    """
    Implémentation mock de LogsProvider.

    Pour le service "frontend" (cas C), lève LogsUnavailableError afin de
    tester le comportement du workflow quand Loki est indisponible.
    """

    async def get_recent_errors(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
        limit: int = 100,
        trace_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if service == "frontend":
            raise LogsUnavailableError(
                "Mock Loki indisponible pour le service 'frontend' (cas C simulé)."
            )
        logs = _LOGS_BY_SERVICE.get(service, _DEFAULT_LOGS)
        return logs[:limit]


# Vérification statique que MockLogsProvider satisfait le Protocol
assert isinstance(MockLogsProvider(), LogsProvider)
