"""Loki provider via le proxy Grafana datasource API."""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from ia4ops_agent.providers.interfaces import LogsUnavailableError
from ia4ops_agent.providers.real._grafana import (
    GrafanaConfigurationError,
    grafana_connection,
)

_LEVEL_PATTERN = re.compile(r"(?i)\b(error|fatal|critical|warn(?:ing)?)\b")


def _timestamp_iso(timestamp_ns: str) -> str:
    timestamp = datetime.fromtimestamp(int(timestamp_ns) / 1_000_000_000, UTC)
    return timestamp.isoformat()


def _normalize_log(
    timestamp_ns: str,
    line: str,
    labels: dict[str, str],
    service: str,
) -> dict[str, str]:
    message = line
    level = str(labels.get("detected_level", labels.get("severity_text", ""))).lower()
    try:
        decoded = json.loads(line)
    except json.JSONDecodeError:
        decoded = None

    if isinstance(decoded, dict):
        message = str(decoded.get("message", decoded.get("msg", decoded.get("log", line))))
        level = str(decoded.get("level", decoded.get("severity", level))).lower()

    if not level:
        match = _LEVEL_PATTERN.search(line)
        level = match.group(1).lower() if match else "error"

    event_id = hashlib.sha256(f"{timestamp_ns}:{line}".encode()).hexdigest()[:16]
    return {
        "event_id": f"loki-{event_id}",
        "timestamp": _timestamp_iso(timestamp_ns),
        "level": level,
        "message": message,
        "service": labels.get("service_name", service),
    }


class LokiProvider:
    """Collecte les lignes de logs d'erreur associées à un service."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def get_recent_errors(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if window_minutes < 1:
            raise ValueError("window_minutes doit être supérieur ou égal à 1")
        if limit < 1:
            raise ValueError("limit doit être supérieur ou égal à 1")

        end = datetime.now(UTC)
        start = end.timestamp() - window_minutes * 60
        service_selector = (
            f"service_name={json.dumps(service)}, "
            f"k8s_namespace_name={json.dumps(namespace)}, "
            'detected_level=~"(?i)(error|fatal|critical|warn(?:ing)?)"'
        )
        params = {
            "query": f"{{{service_selector}}}",
            "start": f"{int(start * 1_000_000_000)}",
            "end": f"{int(end.timestamp() * 1_000_000_000)}",
            "limit": str(limit),
            "direction": "backward",
        }

        try:
            base_url, auth = grafana_connection()
            url = f"{base_url}/api/datasources/proxy/uid/loki/loki/api/v1/query_range"
            async with httpx.AsyncClient(
                auth=auth,
                timeout=15.0,
                transport=self._transport,
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Réponse Loki invalide")
                if payload.get("status") != "success":
                    raise ValueError("Loki a retourné un statut non-success")
                data = payload.get("data")
                if not isinstance(data, dict):
                    raise ValueError("Réponse Loki sans objet data")
                streams = data.get("result")
                if not isinstance(streams, list):
                    raise ValueError("Réponse Loki sans liste de streams")
                logs: list[dict[str, str]] = []
                for stream in streams:
                    if not isinstance(stream, dict):
                        raise ValueError("Stream Loki invalide")
                    labels = stream.get("stream")
                    values = stream.get("values")
                    if not isinstance(labels, dict) or not isinstance(values, list):
                        raise ValueError("Stream Loki sans labels/valeurs")
                    for pair in values:
                        if (
                            not isinstance(pair, list)
                            or len(pair) != 2
                            or not isinstance(pair[0], str)
                            or not isinstance(pair[1], str)
                        ):
                            raise ValueError("Entrée de log Loki invalide")
                        logs.append(_normalize_log(pair[0], pair[1], labels, service))
                return logs[:limit]
        except GrafanaConfigurationError as exc:
            raise LogsUnavailableError(str(exc)) from exc
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise LogsUnavailableError(
                f"Échec de la requête Loki via Grafana ({type(exc).__name__})."
            ) from exc
