"""Publish read-only IA4Ops analyses and alert lifecycle updates to Keep."""

import asyncio
from datetime import datetime
from typing import Any

from ia4ops_agent.config import settings
from ia4ops_agent.domain.alerts import service_from_labels
from ia4ops_agent.integrations.keep import (
    IncidentActivityStatus,
    IncidentSeverity,
    KeepAPIError,
    KeepClient,
)
from ia4ops_agent.integrations.keep_html import (
    build_comments,
    build_resolution_comment,
    grafana_logs_url,
)

_SEVERITY_MAP: dict[str, IncidentSeverity] = {
    "critical": "critical",
    "high": "high",
    "medium": "warning",
    "warning": "warning",
    "low": "low",
    "info": "info",
    "unknown": "info",
}


class KeepPublisher:
    """Serialize Keep updates and reuse Keep incidents linked to alert fingerprints."""

    def __init__(self, client: KeepClient) -> None:
        self._client = client
        self._lock = asyncio.Lock()
        self._incident_by_fingerprint: dict[str, str] = {}
        self._associated_fingerprints: set[str] = set()
        self._published_resolutions: set[str] = set()

    async def publish_diagnosis(
        self,
        *,
        agent_incident_id: str,
        payload: dict[str, Any],
        report: dict[str, Any],
        alert_status: str = "firing",
        resolved_at: str | None = None,
    ) -> str:
        """Find or create one Keep incident, associate its alerts, and add the report."""
        fingerprints = _fingerprints(payload)
        diagnosis = report.get("diagnosis")
        if not fingerprints or not isinstance(diagnosis, dict):
            raise KeepAPIError("Cannot publish a report without alert fingerprints and diagnosis.")

        async with self._lock:
            alert_records = await self._load_alerts(fingerprints)
            incident_ids = {
                incident_id
                for alert in alert_records.values()
                if (incident_id := _alert_incident_id(alert)) is not None
            }
            incident_ids.update(
                self._incident_by_fingerprint[fingerprint]
                for fingerprint in fingerprints
                if fingerprint in self._incident_by_fingerprint
            )
            if len(incident_ids) > 1:
                raise KeepAPIError(
                    "Alert fingerprints are already linked to different Keep incidents."
                )

            if incident_ids:
                keep_incident_id = next(iter(incident_ids))
            else:
                keep_incident_id = await self._create_incident(
                    agent_incident_id=agent_incident_id,
                    payload=payload,
                    diagnosis=diagnosis,
                )

            unattached = [
                fingerprint
                for fingerprint, alert in alert_records.items()
                if _alert_incident_id(alert) != keep_incident_id
                and fingerprint not in self._associated_fingerprints
            ]
            self._incident_by_fingerprint.update(
                {fingerprint: keep_incident_id for fingerprint in fingerprints}
            )
            if unattached:
                await self._client.add_alerts_to_incident(keep_incident_id, unattached)
            self._associated_fingerprints.update(fingerprints)

            # Keep affiche les activités du plus récent au plus ancien : on poste dans l'ordre
            # inverse de lecture (limites, hypothèse, résumé) pour que l'écran lise l'inverse.
            comments = build_comments(
                agent_incident_id=agent_incident_id,
                diagnosis=diagnosis,
                source_status=report.get("source_status", {}),
                alert_status=alert_status,
                resolved_at=resolved_at,
                links=_investigation_links(payload, resolved_at=resolved_at),
            )
            for comment in reversed(comments):
                await self._client.add_comment(
                    keep_incident_id,
                    comment=comment,
                    status=_keep_activity_status(alert_status),
                )
            return keep_incident_id

    async def publish_resolution(
        self,
        *,
        dedup_key: str,
        fingerprints: list[str],
        resolved_at: str | None,
    ) -> list[str]:
        """Add a single resolution activity to each linked Keep incident."""
        unique_fingerprints = list(dict.fromkeys(fingerprints))
        if not dedup_key or not unique_fingerprints:
            raise KeepAPIError("Cannot publish a resolution without a dedup key and fingerprints.")

        async with self._lock:
            if dedup_key in self._published_resolutions:
                return []

            alert_records = await self._load_alerts(unique_fingerprints)
            incident_ids = {
                incident_id
                for alert in alert_records.values()
                if (incident_id := _alert_incident_id(alert)) is not None
            }
            incident_ids.update(
                self._incident_by_fingerprint[fingerprint]
                for fingerprint in unique_fingerprints
                if fingerprint in self._incident_by_fingerprint
            )
            if not incident_ids:
                raise KeepAPIError("Resolved alerts are not associated with a Keep incident.")

            comment = build_resolution_comment(resolved_at)
            for incident_id in sorted(incident_ids):
                await self._client.add_comment(
                    incident_id,
                    comment=comment,
                    status="resolved",
                )
            self._published_resolutions.add(dedup_key)
            return sorted(incident_ids)

    async def _load_alerts(self, fingerprints: list[str]) -> dict[str, dict[str, Any]]:
        """Retry alert lookups briefly because Keep and the agent receive alerts in parallel."""
        for attempt in range(3):
            try:
                return {
                    fingerprint: await self._client.get_alert(fingerprint)
                    for fingerprint in fingerprints
                }
            except KeepAPIError as exc:
                if exc.status_code != 404 or attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (2**attempt))
        raise AssertionError("Unreachable")

    async def _create_incident(
        self,
        *,
        agent_incident_id: str,
        payload: dict[str, Any],
        diagnosis: dict[str, Any],
    ) -> str:
        service = diagnosis.get("affected_service")
        if not isinstance(service, str) or not service:
            service = _service_from_payload(payload) or "unknown-service"
        summary = diagnosis.get("summary")
        if not isinstance(summary, str) or not summary:
            summary = (
                "IA4Ops diagnostic unavailable"
                if diagnosis.get("failure_reason")
                else "IA4Ops pre-analysis"
            )
        response = await self._client.create_incident(
            name=_incident_name(payload, service, agent_incident_id),
            summary=summary[:500],
            severity=_severity(diagnosis, payload),
        )
        incident_id = response.get("id")
        if not isinstance(incident_id, str) or not incident_id:
            raise KeepAPIError("Keep did not return an incident ID after creation.")
        return incident_id


def _fingerprints(payload: dict[str, Any]) -> list[str]:
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        return []
    return list(
        dict.fromkeys(
            alert["fingerprint"]
            for alert in alerts
            if isinstance(alert, dict)
            and isinstance(alert.get("fingerprint"), str)
            and alert["fingerprint"]
        )
    )


def _alert_incident_id(alert: dict[str, Any]) -> str | None:
    value = alert.get("incident")
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict) and isinstance(value.get("id"), str):
        return value["id"] or None
    raise KeepAPIError("Keep alert returned an unexpected incident reference.")


def _severity(diagnosis: dict[str, Any], payload: dict[str, Any]) -> IncidentSeverity:
    assessment = diagnosis.get("severity_assessment")
    if isinstance(assessment, str) and assessment.lower() in _SEVERITY_MAP:
        return _SEVERITY_MAP[assessment.lower()]

    alerts = payload.get("alerts", [])
    if isinstance(alerts, list):
        for alert in alerts:
            labels = alert.get("labels", {}) if isinstance(alert, dict) else {}
            severity = labels.get("severity") if isinstance(labels, dict) else None
            if isinstance(severity, str) and severity.lower() in _SEVERITY_MAP:
                return _SEVERITY_MAP[severity.lower()]
    return "info"


def _keep_activity_status(alert_status: str) -> IncidentActivityStatus:
    return "resolved" if alert_status == "resolved" else "firing"


def _service_from_payload(payload: dict[str, Any]) -> str | None:
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        return None
    for alert in alerts:
        labels = alert.get("labels") if isinstance(alert, dict) else None
        if isinstance(labels, dict) and (service := service_from_labels(labels)):
            return service
    return None


def _first_label(payload: dict[str, Any], name: str) -> str | None:
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        return None
    for alert in alerts:
        labels = alert.get("labels") if isinstance(alert, dict) else None
        value = labels.get(name) if isinstance(labels, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _incident_name(payload: dict[str, Any], service: str, agent_incident_id: str) -> str:
    """Nom lisible dans la liste des incidents : « <alerte> — <service> (<id agent>) »."""
    alertname = _first_label(payload, "alertname")
    prefix = f"{alertname} — {service}" if alertname else f"IA4Ops {service}"
    return f"{prefix} ({agent_incident_id})"


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _investigation_links(
    payload: dict[str, Any], *, resolved_at: str | None
) -> list[tuple[str, str]]:
    """Liens d'investigation (jamais bloquants) : logs du service dans Grafana Explore."""
    if not settings.grafana_base_url:
        return []
    alerts = payload.get("alerts")
    starts = [
        parsed
        for alert in (alerts if isinstance(alerts, list) else [])
        if isinstance(alert, dict) and (parsed := _parse_time(alert.get("startsAt"))) is not None
    ]
    namespace = _first_label(payload, "namespace")
    if not starts or not namespace:
        return []
    return [
        (
            "Logs du service dans Grafana",
            grafana_logs_url(
                settings.grafana_base_url,
                namespace=namespace,
                service=_service_from_payload(payload),
                start=min(starts),
                end=_parse_time(resolved_at),
            ),
        )
    ]
