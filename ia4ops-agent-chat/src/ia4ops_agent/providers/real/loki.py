"""Loki provider via le proxy Grafana datasource API."""

import asyncio
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

# Contenu évoquant une panne, pour retrouver les erreurs journalisées en INFO.
_CONTENT_PATTERN = "(?i)(error|exception|fail|panic|timeout|refused|unavailable|oom|killed)"
_ERROR_LEVELS = "(?i)(error|fatal|critical|warn(?:ing)?)"
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_MAX_TRACE_IDS = 3
_MAX_TRACE_LOGS = 20
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
    """Collecte les lignes de logs en cause pour un service.

    Trois requêtes, la première seule étant indispensable :
    (a) logs de niveau error/warn du service ;
    (b) logs du service dont le *contenu* évoque une erreur, quel que soit leur niveau (certaines
        applications journalisent leurs échecs en INFO) ;
    (c) logs error/warn de toutes les applications du namespace pour les traces en erreur
        fournies (`trace_id` est une métadonnée structurée Loki, jamais interpolée sans
        validation).
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        url: str,
        query: str,
        *,
        start: float,
        end: float,
        limit: int,
        service: str,
    ) -> list[dict[str, str]]:
        params = {
            "query": query,
            "start": f"{int(start * 1_000_000_000)}",
            "end": f"{int(end * 1_000_000_000)}",
            "limit": str(limit),
            "direction": "backward",
        }
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
        return logs

    async def get_recent_errors(
        self,
        service: str,
        namespace: str,
        window_minutes: int = 15,
        limit: int = 100,
        trace_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if window_minutes < 1:
            raise ValueError("window_minutes doit être supérieur ou égal à 1")
        if limit < 1:
            raise ValueError("limit doit être supérieur ou égal à 1")

        end = datetime.now(UTC).timestamp()
        start = end - window_minutes * 60
        base_selector = (
            f"service_name={json.dumps(service)}, k8s_namespace_name={json.dumps(namespace)}"
        )
        queries = {
            "level": f'{{{base_selector}, detected_level=~"{_ERROR_LEVELS}"}}',
            "content": f'{{{base_selector}}} |~ "{_CONTENT_PATTERN}"',
        }
        valid_trace_ids = [t for t in (trace_ids or []) if _TRACE_ID.match(t)][:_MAX_TRACE_IDS]
        if valid_trace_ids:
            queries["trace"] = (
                f"{{k8s_namespace_name={json.dumps(namespace)}}} "
                f'| trace_id=~"{"|".join(valid_trace_ids)}" '
                f'| detected_level=~"{_ERROR_LEVELS}"'
            )
        limits = {"level": limit, "content": limit, "trace": min(limit, _MAX_TRACE_LOGS)}

        try:
            base_url, auth = grafana_connection()
            url = f"{base_url}/api/datasources/proxy/uid/loki/loki/api/v1/query_range"
            async with httpx.AsyncClient(
                auth=auth,
                timeout=15.0,
                transport=self._transport,
            ) as client:
                names = list(queries)
                results = await asyncio.gather(
                    *(
                        self._fetch(
                            client, url, queries[name],
                            start=start, end=end, limit=limits[name], service=service,
                        )
                        for name in names
                    ),
                    return_exceptions=True,
                )
        except GrafanaConfigurationError as exc:
            raise LogsUnavailableError(str(exc)) from exc

        by_name = dict(zip(names, results, strict=True))
        primary = by_name["level"]
        if isinstance(primary, BaseException):
            # La requête indispensable a échoué : source indisponible.
            if isinstance(primary, (httpx.HTTPError, ValueError, TypeError, KeyError)):
                raise LogsUnavailableError(
                    f"Échec de la requête Loki via Grafana ({type(primary).__name__})."
                ) from primary
            raise primary

        merged: dict[str, dict[str, str]] = {}
        for name in names:  # priorité : niveau, puis contenu, puis traces
            result = by_name[name]
            if isinstance(result, BaseException):
                continue  # requêtes complémentaires : meilleur effort
            for log in result:
                merged.setdefault(log["event_id"], log)
        return sorted(merged.values(), key=lambda log: log["timestamp"], reverse=True)[:limit]
