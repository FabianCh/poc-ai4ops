"""
Tests unitaires — modèles de domaine (Task 2).

Couvre :
- AlertmanagerWebhook : validation payload v4, déduplication, watchdog
- DiagnosticOutput : invariant action_executed=False, cohérence evidence_refs
- IncidentContext : sérialisation to_llm_dict
- AuditEvent : sérialisation JSON Lines
- Cas d'erreur Pydantic attendus
"""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.domain.alerts import AlertItem, AlertLabels, AlertmanagerWebhook
from ia4ops_agent.domain.context import (
    IncidentContext,
    IncidentInfo,
    LogPattern,
    LogsObservation,
    MetricsObservation,
    Observations,
    SourceStatuses,
)
from ia4ops_agent.domain.diagnosis import (
    DiagnosticFailure,
    DiagnosticOutput,
    Evidence,
    Hypothesis,
)

# ---------------------------------------------------------------------------
# Fixtures partagées
# ---------------------------------------------------------------------------

ALERT_ITEM_FIRING = {
    "status": "firing",
    "labels": {
        "alertname": "OtelDemoServiceHighErrorRate",
        "namespace": "otel-demo",
        "severity": "critical",
        "service_name": "product-catalog",
    },
    "annotations": {"summary": "High error rate on product-catalog"},
    "startsAt": "2026-10-02T18:41:26Z",
    "endsAt": "0001-01-01T00:00:00Z",
    "generatorURL": "http://prometheus/graph",
    "fingerprint": "abc123",
}

WEBHOOK_PAYLOAD = {
    "version": "4",
    "groupKey": "{}/{namespace='otel-demo'}:{alertname='OtelDemoServiceHighErrorRate'}",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "ai4ops-agent",
    "groupLabels": {"namespace": "otel-demo"},
    "commonLabels": {
        "namespace": "otel-demo",
        "alertname": "OtelDemoServiceHighErrorRate",
    },
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [ALERT_ITEM_FIRING],
}


def make_evidence(ref: str = "metrics.error_rate") -> Evidence:
    return Evidence(
        source="metrics",
        reference=ref,
        observation="Taux d'erreur à 18% sur les 15 dernières minutes.",
    )


def make_hypothesis(evidence_refs: list[str] | None = None) -> Hypothesis:
    return Hypothesis(
        title="Dépendance Redis indisponible",
        likelihood="high",
        reasoning="Les logs montrent des timeouts répétés vers Redis.",
        evidence_refs=evidence_refs or ["metrics.error_rate"],
    )


def make_diagnostic(incident_id: str = "inc-001") -> DiagnosticOutput:
    ev = make_evidence("metrics.error_rate")
    hyp = make_hypothesis(["metrics.error_rate"])
    return DiagnosticOutput(
        incident_id=incident_id,
        summary="Taux d'erreur élevé — suspicion de dépendance indisponible.",
        affected_service="product-catalog",
        severity_assessment="critical",
        primary_hypothesis=hyp,
        evidence=[ev],
        missing_information=[],
        recommended_next_checks=["Vérifier la connectivité Redis"],
        remediation_suggestions=["Redémarrer le pod Redis si applicable"],
    )


# ---------------------------------------------------------------------------
# Tests AlertmanagerWebhook
# ---------------------------------------------------------------------------


class TestAlertmanagerWebhook:
    def test_valid_payload_parses(self) -> None:
        wh = AlertmanagerWebhook(**WEBHOOK_PAYLOAD)
        assert wh.version == "4"
        assert wh.status == "firing"
        assert len(wh.alerts) == 1
        assert wh.alerts[0].labels.service_name == "product-catalog"

    def test_version_must_be_4(self) -> None:
        bad = {**WEBHOOK_PAYLOAD, "version": "3"}
        with pytest.raises(ValidationError):
            AlertmanagerWebhook(**bad)

    def test_empty_alerts_rejected(self) -> None:
        bad = {**WEBHOOK_PAYLOAD, "alerts": []}
        with pytest.raises(ValidationError, match="au moins une alerte"):
            AlertmanagerWebhook(**bad)

    def test_dedup_key_is_stable(self) -> None:
        wh = AlertmanagerWebhook(**WEBHOOK_PAYLOAD)
        key1 = wh.make_dedup_key()
        key2 = wh.make_dedup_key()
        assert key1 == key2
        assert "abc123" in key1

    def test_dedup_key_changes_with_different_fingerprint(self) -> None:
        other_alert = {**ALERT_ITEM_FIRING, "fingerprint": "xyz999"}
        payload = {**WEBHOOK_PAYLOAD, "alerts": [other_alert]}
        wh1 = AlertmanagerWebhook(**WEBHOOK_PAYLOAD)
        wh2 = AlertmanagerWebhook(**payload)
        assert wh1.make_dedup_key() != wh2.make_dedup_key()

    def test_primary_alert_returns_oldest(self) -> None:
        alert2 = {
            **ALERT_ITEM_FIRING,
            "fingerprint": "def456",
            "startsAt": "2026-10-02T18:50:00Z",
        }
        payload = {**WEBHOOK_PAYLOAD, "alerts": [ALERT_ITEM_FIRING, alert2]}
        wh = AlertmanagerWebhook(**payload)
        primary = wh.primary_alert()
        assert primary.fingerprint == "abc123"

    def test_affected_services_deduplicates(self) -> None:
        alert2 = {**ALERT_ITEM_FIRING, "fingerprint": "def456"}
        payload = {**WEBHOOK_PAYLOAD, "alerts": [ALERT_ITEM_FIRING, alert2]}
        wh = AlertmanagerWebhook(**payload)
        services = wh.affected_services()
        assert services == ["product-catalog"]

    def test_is_watchdog_true(self) -> None:
        watchdog_alert = {
            **ALERT_ITEM_FIRING,
            "labels": {**ALERT_ITEM_FIRING["labels"], "alertname": "Watchdog"},
        }
        payload = {**WEBHOOK_PAYLOAD, "alerts": [watchdog_alert]}
        wh = AlertmanagerWebhook(**payload)
        assert wh.is_watchdog() is True

    def test_is_watchdog_false(self) -> None:
        wh = AlertmanagerWebhook(**WEBHOOK_PAYLOAD)
        assert wh.is_watchdog() is False

    def test_extra_labels_accepted(self) -> None:
        """AlertLabels accepte les labels supplémentaires inconnus (extra=allow)."""
        alert = {
            **ALERT_ITEM_FIRING,
            "labels": {
                **ALERT_ITEM_FIRING["labels"],
                "custom_team": "sre",
                "region": "eu-west-1",
            },
        }
        item = AlertItem(**alert)
        assert item.labels.alertname == "OtelDemoServiceHighErrorRate"

    def test_alert_is_resolved_property(self) -> None:
        resolved_alert = {**ALERT_ITEM_FIRING, "endsAt": "2026-10-02T19:00:00Z"}
        item = AlertItem(**resolved_alert)
        assert item.is_resolved is True

    def test_alert_is_not_resolved(self) -> None:
        item = AlertItem(**ALERT_ITEM_FIRING)
        assert item.is_resolved is False


# ---------------------------------------------------------------------------
# Tests DiagnosticOutput
# ---------------------------------------------------------------------------


class TestDiagnosticOutput:
    def test_valid_diagnostic_creates(self) -> None:
        diag = make_diagnostic()
        assert diag.action_executed is False
        assert diag.incident_id == "inc-001"

    def test_action_executed_defaults_to_false(self) -> None:
        diag = make_diagnostic()
        assert diag.action_executed is False

    def test_action_executed_true_raises(self) -> None:
        ev = make_evidence()
        hyp = make_hypothesis()
        with pytest.raises(ValidationError, match="action_executed"):
            DiagnosticOutput(
                incident_id="inc-001",
                summary="Test",
                affected_service="svc",
                severity_assessment="low",
                primary_hypothesis=hyp,
                evidence=[ev],
                action_executed=True,  # doit être rejeté
            )

    def test_unknown_evidence_ref_raises(self) -> None:
        ev = make_evidence("ref-A")
        hyp = make_hypothesis(["ref-B"])  # ref-B n'existe pas dans evidence
        with pytest.raises(ValidationError, match="evidence_refs inconnues"):
            DiagnosticOutput(
                incident_id="inc-001",
                summary="Test",
                affected_service="svc",
                severity_assessment="low",
                primary_hypothesis=hyp,
                evidence=[ev],
            )

    def test_alternative_hypothesis_with_bad_ref_raises(self) -> None:
        ev = make_evidence("ref-A")
        primary = make_hypothesis(["ref-A"])
        alt = make_hypothesis(["ref-UNKNOWN"])
        with pytest.raises(ValidationError, match="evidence_refs inconnues"):
            DiagnosticOutput(
                incident_id="inc-001",
                summary="Test",
                affected_service="svc",
                severity_assessment="low",
                primary_hypothesis=primary,
                alternative_hypotheses=[alt],
                evidence=[ev],
            )

    def test_empty_evidence_raises(self) -> None:
        hyp = make_hypothesis(["ref-A"])
        with pytest.raises(ValidationError):
            DiagnosticOutput(
                incident_id="inc-001",
                summary="Test",
                affected_service="svc",
                severity_assessment="low",
                primary_hypothesis=hyp,
                evidence=[],  # interdit
            )

    def test_diagnostic_serializable_to_json(self) -> None:
        diag = make_diagnostic()
        data = diag.model_dump()
        # Doit se sérialiser en JSON sans erreur
        serialized = json.dumps(data)
        assert "action_executed" in serialized
        assert "false" in serialized.lower()

    def test_diagnostic_failure_serializable(self) -> None:
        failure = DiagnosticFailure(
            incident_id="inc-001",
            failure_reason="LLM timeout après 3 tentatives",
            attempts=3,
            last_error="ReadTimeout",
        )
        assert failure.action_executed is False
        data = json.dumps(failure.model_dump())
        assert "failure_reason" in data


# ---------------------------------------------------------------------------
# Tests IncidentContext
# ---------------------------------------------------------------------------


class TestIncidentContext:
    def test_to_llm_dict_excludes_none(self) -> None:
        ctx = IncidentContext(
            incident=IncidentInfo(
                id="inc-001",
                alert_name="HighErrorRate",
                service="product-catalog",
                namespace="otel-demo",
                severity="critical",
                started_at="2026-10-02T18:41:26Z",
            ),
            observations=Observations(
                metrics=MetricsObservation(error_rate=0.18, window_minutes=15),
            ),
            source_status=SourceStatuses(
                metrics="success",
                logs="unavailable",
                cluster="partial",
            ),
            known_missing=["logs indisponibles"],
        )
        result = ctx.to_llm_dict()
        # Les champs None ne doivent pas apparaître
        assert "logs" not in result["observations"]
        assert "kubernetes" not in result["observations"]
        # Les données présentes doivent être là
        assert result["incident"]["service"] == "product-catalog"
        assert result["source_status"]["logs"] == "unavailable"
        assert result["known_missing"] == ["logs indisponibles"]

    def test_context_fully_populated(self) -> None:
        ctx = IncidentContext(
            incident=IncidentInfo(
                id="inc-002",
                alert_name="PodCrashLoop",
                service="checkout",
                namespace="otel-demo",
                severity="critical",
                started_at="2026-10-02T19:00:00Z",
            ),
            observations=Observations(
                metrics=MetricsObservation(error_rate=0.45),
                logs=LogsObservation(
                    error_count=12,
                    top_patterns=[LogPattern(pattern="OOMKilled", count=5)],
                ),
            ),
            source_status=SourceStatuses(
                metrics="success", logs="success", cluster="success"
            ),
        )
        data = ctx.to_llm_dict()
        assert data["observations"]["logs"]["error_count"] == 12


# ---------------------------------------------------------------------------
# Tests AuditEvent
# ---------------------------------------------------------------------------


class TestAuditEvent:
    def test_audit_event_creates_with_defaults(self) -> None:
        evt = AuditEvent(
            event_id="evt-001",
            incident_id="inc-001",
            step="collect_metrics",
            status="success",
        )
        assert evt.actor == "ia4ops-agent"
        assert evt.timestamp  # auto-généré

    def test_to_json_line_is_valid_json(self) -> None:
        evt = AuditEvent(
            event_id="evt-002",
            incident_id="inc-001",
            step="collect_logs",
            status="unavailable",
            error="Loki unreachable",
            duration_ms=42,
        )
        line = evt.to_json_line()
        parsed = json.loads(line)
        assert parsed["step"] == "collect_logs"
        assert parsed["status"] == "unavailable"
        assert parsed["error"] == "Loki unreachable"
        assert parsed["duration_ms"] == 42

    def test_to_json_line_has_no_newline(self) -> None:
        evt = AuditEvent(
            event_id="evt-003",
            incident_id="inc-001",
            step="diagnose",
            status="success",
        )
        line = evt.to_json_line()
        assert "\n" not in line

    def test_make_id_format(self) -> None:
        event_id = AuditEvent.make_id("inc-001", "collect_logs", 2)
        assert event_id == "evt-inc-001-collect_logs-002"

    def test_audit_event_serializable_with_summary(self) -> None:
        evt = AuditEvent(
            event_id="evt-004",
            incident_id="inc-001",
            step="build_context",
            status="success",
            input_summary={"service": "product-catalog", "window_minutes": 15},
            output_summary={"observations_count": 3},
        )
        line = evt.to_json_line()
        parsed = json.loads(line)
        assert parsed["input_summary"]["service"] == "product-catalog"
        assert parsed["output_summary"]["observations_count"] == 3
