"""Publish read-only IA4Ops analyses and alert lifecycle updates to Keep."""

import asyncio
from typing import Any

from ia4ops_agent.integrations.keep import (
    IncidentActivityStatus,
    IncidentSeverity,
    KeepAPIError,
    KeepClient,
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

            for comment in _diagnosis_comments(
                agent_incident_id=agent_incident_id,
                diagnosis=diagnosis,
                source_status=report.get("source_status", {}),
                alert_status=alert_status,
                resolved_at=resolved_at,
            ):
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

            timestamp = f" at {resolved_at}" if resolved_at else ""
            comment = f"Alertmanager reports this alert group as resolved{timestamp}."
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
        service = str(diagnosis.get("affected_service") or "unknown-service")
        summary = str(diagnosis.get("summary") or "IA4Ops pre-analysis")
        response = await self._client.create_incident(
            name=f"IA4Ops {service} {agent_incident_id}",
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


def _diagnosis_comments(
    *,
    agent_incident_id: str,
    diagnosis: dict[str, Any],
    source_status: Any,
    alert_status: str,
    resolved_at: str | None,
) -> list[str]:
    hypothesis = diagnosis.get("primary_hypothesis")
    if not isinstance(hypothesis, dict):
        hypothesis = {}

    service = _display_text(diagnosis.get("affected_service"), "inconnu", 200)
    severity = _display_text(diagnosis.get("severity_assessment"), "inconnue", 40)
    alert = (
        f"{alert_status} — {resolved_at}"
        if alert_status == "resolved" and resolved_at
        else alert_status
    )
    summary = _display_text(diagnosis.get("summary"), "Aucun résumé disponible.", 500)
    comments = [
        (
            f"IA4Ops — Résumé du diagnostic ({agent_incident_id})\n"
            f"Service : {service}\n"
            f"Sévérité estimée : {severity}\n"
            f"État de l'alerte : {alert}\n"
            f"Résumé : {summary}"
        )
    ]

    hypothesis_title = _display_text(hypothesis.get("title"), "Non déterminée", 200)
    likelihood = _display_text(hypothesis.get("likelihood"), "inconnue", 20)
    reasoning = _display_text(hypothesis.get("reasoning"), "", 1000)
    hypothesis_section = (
        f"IA4Ops — Hypothèse principale : {hypothesis_title} "
        f"(confiance : {likelihood})"
    )
    if reasoning:
        hypothesis_section += f"\nRaisonnement : {reasoning}"

    evidence = diagnosis.get("evidence")
    if isinstance(evidence, list) and evidence:
        evidence_lines = []
        for item in evidence[:8]:
            if not isinstance(item, dict):
                continue
            source = _display_text(item.get("source"), "observation", 40)
            observation = _display_text(item.get("observation"), "", 400)
            if observation:
                evidence_lines.append(f"- {source} : {observation}")
        if evidence_lines:
            hypothesis_section += "\nÉléments observés :\n" + "\n".join(evidence_lines)
    comments.append(hypothesis_section)

    missing = _text_list(diagnosis.get("missing_information"), limit=5, item_length=300)
    next_checks = _text_list(diagnosis.get("recommended_next_checks"), limit=5, item_length=300)
    source_labels = {
        "metrics": "métriques",
        "logs": "logs",
        "cluster": "Kubernetes",
    }
    if isinstance(source_status, dict) and source_status:
        sources = ", ".join(
            f"{source_labels.get(name, name)} : {status}"
            for name, status in sorted(source_status.items())
        )
    else:
        sources = "indisponible"
    context_lines = [
        f"IA4Ops — Limites et prochaines étapes ({agent_incident_id})",
        f"Collecte : {sources}",
    ]
    if missing:
        missing_text = "\n".join(f"- {item}" for item in missing)
        context_lines.append(f"Informations manquantes :\n{missing_text}")
    if next_checks:
        context_lines.append(
            "Vérifications suggérées :\n"
            + "\n".join(f"{index}. {item}" for index, item in enumerate(next_checks, start=1))
        )
    context_lines.append("Aucune action de remédiation n'a été exécutée.")
    comments.append("\n".join(context_lines))
    return comments


def _display_text(value: Any, fallback: str, limit: int) -> str:
    """Normalize an LLM-provided display value and keep the activity bounded."""
    if not isinstance(value, str):
        return fallback
    normalized = " ".join(value.split())
    return normalized[:limit] if normalized else fallback


def _text_list(value: Any, *, limit: int, item_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        _display_text(item, "", item_length)
        for item in value[:limit]
        if isinstance(item, str) and item.strip()
    ]
