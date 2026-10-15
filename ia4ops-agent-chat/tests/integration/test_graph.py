"""
Tests d'intégration — graphe LangGraph de bout en bout (Task 4).

Chaque cas traverse le graphe complet avec FakeLLMClient et providers mockés.
On vérifie :
- Le graphe s'exécute sans exception
- Les nœuds attendus sont dans l'audit trail
- Le diagnostic respecte le schéma DiagnosticOutput (action_executed=False)
- Les statuts de sources sont corrects par cas
- L'audit trail est écrit sur disque
- Cas C : missing_information non vide, severity_assessment="unknown"
- Watchdog : graphe s'arrête sans diagnostic
"""

import json
from pathlib import Path
from typing import Any

import pytest

from ia4ops_agent.domain.diagnosis import DiagnosticOutput
from ia4ops_agent.graph.builder import build_graph
from ia4ops_agent.providers.factory import Providers

# ---------------------------------------------------------------------------
# Payloads de test (identiques aux fixtures JSON)
# ---------------------------------------------------------------------------

def _alert_payload(service_name: str, fingerprint: str) -> dict[str, Any]:
    return {
        "version": "4",
        "groupKey": "{/}{namespace='otel-demo'}:{alertname='OtelDemoServiceHighErrorRate'}",
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
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "OtelDemoServiceHighErrorRate",
                    "namespace": "otel-demo",
                    "severity": "critical",
                    "service_name": service_name,
                },
                "annotations": {"summary": f"High error rate on {service_name}"},
                "startsAt": "2026-10-02T18:41:26Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prometheus/graph",
                "fingerprint": fingerprint,
            }
        ],
    }


PAYLOAD_A = _alert_payload("product-catalog", "case-a-fp-001")
PAYLOAD_B = _alert_payload("checkout", "case-b-fp-001")
PAYLOAD_C = _alert_payload("frontend", "case-c-fp-001")

PAYLOAD_WATCHDOG = {
    "version": "4",
    "groupKey": "watchdog",
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "ai4ops-agent",
    "groupLabels": {},
    "commonLabels": {"alertname": "Watchdog"},
    "commonAnnotations": {},
    "externalURL": "http://alertmanager:9093",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "Watchdog", "namespace": "monitoring"},
            "annotations": {},
            "startsAt": "2026-10-02T18:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "",
            "fingerprint": "watchdog-fp-001",
        }
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_graph(payload: dict[str, Any], audit_dir: Path) -> dict[str, Any]:
    """Exécute le graphe de façon asynchrone en renvoyant l'état final."""
    graph = build_graph(providers=Providers.mock(), audit_dir=audit_dir)
    initial_state = {"raw_alert": payload}
    return await graph.ainvoke(initial_state)


async def test_trace_events_capture_collection_and_diagnosis(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Trace output is JSONL, correlated, and includes bounded evidence and the LLM result."""
    initial_incident_id = "inc-trace-test"
    graph = build_graph(providers=Providers.mock(), audit_dir=tmp_path)
    result = await graph.ainvoke(
        {
            "raw_alert": PAYLOAD_A,
            "incident_id": initial_incident_id,
        }
    )

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    event_types = {event["event"] for event in events}

    assert result["incident_id"] == initial_incident_id
    assert result["report"]["incident_id"] == initial_incident_id
    assert {
        "incident_initialized",
        "data_collected",
        "diagnostic_context_built",
        "diagnosis_generated",
        "incident_finalized",
    } <= event_types

    log_event = next(
        event
        for event in events
        if event["event"] == "data_collected" and event["source"] == "loki"
    )
    assert log_event["incident_id"] == initial_incident_id
    assert log_event["log_samples"][0]["message"].startswith("timeout connecting")

    diagnosis_event = next(event for event in events if event["event"] == "diagnosis_generated")
    assert diagnosis_event["diagnosis"]["affected_service"] == "product-catalog"
    assert diagnosis_event["diagnosis"]["action_executed"] is False


def _expected_steps(case: str) -> list[str]:
    base = ["initialize", "collect_metrics", "collect_traces", "collect_logs", "collect_cluster",
            "build_context", "diagnose", "validate", "finalize"]
    return base


# ---------------------------------------------------------------------------
# Tests Cas A — dépendance timeout
# ---------------------------------------------------------------------------

class TestCaseA:
    @pytest.fixture
    async def result(self, tmp_path: Path) -> dict[str, Any]:
        return await _run_graph(PAYLOAD_A, tmp_path)

    async def test_graph_completes_without_exception(self, result: dict[str, Any]) -> None:
        assert result is not None

    async def test_incident_id_generated(self, result: dict[str, Any]) -> None:
        assert result.get("incident_id", "").startswith("inc-")

    async def test_report_present(self, result: dict[str, Any]) -> None:
        assert "report" in result
        assert result["report"]["status"] in ("completed", "completed_with_errors")

    async def test_action_executed_false(self, result: dict[str, Any]) -> None:
        diagnosis = result["report"]["diagnosis"]
        assert diagnosis.get("action_executed") is False

    async def test_diagnosis_valid_pydantic(self, result: dict[str, Any]) -> None:
        diagnosis = result["report"]["diagnosis"]
        # Ne doit pas lever d'exception
        d = DiagnosticOutput(**diagnosis)
        assert d.action_executed is False

    async def test_metrics_status_success(self, result: dict[str, Any]) -> None:
        assert result.get("metrics_status") == "success"

    async def test_logs_status_success(self, result: dict[str, Any]) -> None:
        assert result.get("logs_status") == "success"

    async def test_cluster_status_success(self, result: dict[str, Any]) -> None:
        assert result.get("cluster_status") == "success"

    async def test_severity_critical(self, result: dict[str, Any]) -> None:
        diagnosis = result["report"]["diagnosis"]
        assert diagnosis.get("severity_assessment") == "critical"

    async def test_affected_service_correct(self, result: dict[str, Any]) -> None:
        diagnosis = result["report"]["diagnosis"]
        assert diagnosis.get("affected_service") == "product-catalog"

    async def test_audit_trail_has_all_steps(self, result: dict[str, Any]) -> None:
        steps = {e["step"] for e in result.get("audit_events", [])}
        for expected in _expected_steps("a"):
            assert expected in steps, f"Étape manquante dans l'audit : {expected}"

    async def test_audit_trail_written_to_disk(
        self, result: dict[str, Any], tmp_path: Path
    ) -> None:
        incident_id = result["incident_id"]
        audit_file = tmp_path / f"audit-{incident_id}.jsonl"
        assert audit_file.exists(), "Fichier d'audit non créé"
        lines = [line for line in audit_file.read_text().splitlines() if line.strip()]
        assert len(lines) >= 8, f"Attendu ≥8 événements d'audit, trouvé {len(lines)}"

    async def test_audit_events_are_valid_json(
        self, result: dict[str, Any], tmp_path: Path
    ) -> None:
        incident_id = result["incident_id"]
        audit_file = tmp_path / f"audit-{incident_id}.jsonl"
        for line in audit_file.read_text().splitlines():
            if line.strip():
                parsed = json.loads(line)
                assert "event_id" in parsed
                assert "step" in parsed
                assert "status" in parsed

    async def test_no_missing_information_for_nominal_case(self, result: dict[str, Any]) -> None:
        # Cas A : toutes les sources disponibles, pas de missing obligatoire
        report = result["report"]
        missing = report.get("missing_information", [])
        for m in missing:
            assert "unavailable" not in m.lower() or "redis" in m.lower()


# ---------------------------------------------------------------------------
# Tests Cas B — pod instable
# ---------------------------------------------------------------------------

class TestCaseB:
    @pytest.fixture
    async def result(self, tmp_path: Path) -> dict[str, Any]:
        return await _run_graph(PAYLOAD_B, tmp_path)

    async def test_graph_completes(self, result: dict[str, Any]) -> None:
        assert result is not None

    async def test_action_executed_false(self, result: dict[str, Any]) -> None:
        assert result["report"]["diagnosis"]["action_executed"] is False

    async def test_diagnosis_valid_pydantic(self, result: dict[str, Any]) -> None:
        DiagnosticOutput(**result["report"]["diagnosis"])

    async def test_affected_service_checkout(self, result: dict[str, Any]) -> None:
        assert result["report"]["diagnosis"]["affected_service"] == "checkout"

    async def test_all_sources_success(self, result: dict[str, Any]) -> None:
        assert result.get("metrics_status") == "success"
        assert result.get("logs_status") == "success"
        assert result.get("cluster_status") == "success"

    async def test_audit_trail_has_all_steps(self, result: dict[str, Any]) -> None:
        steps = {e["step"] for e in result.get("audit_events", [])}
        for s in _expected_steps("b"):
            assert s in steps

    async def test_audit_trail_written_to_disk(
        self, result: dict[str, Any], tmp_path: Path
    ) -> None:
        incident_id = result["incident_id"]
        assert (tmp_path / f"audit-{incident_id}.jsonl").exists()

    async def test_evidence_refs_all_exist(self, result: dict[str, Any]) -> None:
        """Vérifie la cohérence interne du diagnostic (contrôle Pydantic)."""
        diag = DiagnosticOutput(**result["report"]["diagnosis"])
        known_refs = {e.reference for e in diag.evidence}
        for ref in diag.primary_hypothesis.evidence_refs:
            assert ref in known_refs, f"evidence_ref manquante : {ref}"


# ---------------------------------------------------------------------------
# Tests Cas C — données insuffisantes
# ---------------------------------------------------------------------------

class TestCaseC:
    @pytest.fixture
    async def result(self, tmp_path: Path) -> dict[str, Any]:
        return await _run_graph(PAYLOAD_C, tmp_path)

    async def test_graph_completes_despite_unavailable_logs(self, result: dict[str, Any]) -> None:
        assert result is not None
        assert "report" in result

    async def test_logs_status_unavailable(self, result: dict[str, Any]) -> None:
        assert result.get("logs_status") == "unavailable"

    async def test_cluster_status_partial(self, result: dict[str, Any]) -> None:
        assert result.get("cluster_status") == "partial"

    async def test_metrics_status_success(self, result: dict[str, Any]) -> None:
        assert result.get("metrics_status") == "success"

    async def test_missing_information_not_empty(self, result: dict[str, Any]) -> None:
        missing = result["report"].get("missing_information", [])
        assert len(missing) > 0, "Cas C doit avoir des missing_information"

    async def test_missing_information_mentions_logs(self, result: dict[str, Any]) -> None:
        missing = " ".join(result["report"].get("missing_information", []))
        assert "log" in missing.lower() or "loki" in missing.lower()

    async def test_severity_unknown(self, result: dict[str, Any]) -> None:
        diagnosis = result["report"]["diagnosis"]
        assert diagnosis.get("severity_assessment") == "unknown"

    async def test_action_executed_false(self, result: dict[str, Any]) -> None:
        assert result["report"]["diagnosis"]["action_executed"] is False

    async def test_diagnosis_valid_pydantic(self, result: dict[str, Any]) -> None:
        DiagnosticOutput(**result["report"]["diagnosis"])

    async def test_audit_trail_has_collect_logs_unavailable(self, result: dict[str, Any]) -> None:
        logs_event = next(
            (e for e in result.get("audit_events", []) if e["step"] == "collect_logs"),
            None,
        )
        assert logs_event is not None
        assert logs_event["status"] == "unavailable"

    async def test_audit_trail_has_collect_cluster_partial(self, result: dict[str, Any]) -> None:
        cluster_event = next(
            (e for e in result.get("audit_events", []) if e["step"] == "collect_cluster"),
            None,
        )
        assert cluster_event is not None
        assert cluster_event["status"] == "partial"


# ---------------------------------------------------------------------------
# Tests Watchdog — doit être ignoré
# ---------------------------------------------------------------------------

class TestWatchdog:
    @pytest.fixture
    async def result(self, tmp_path: Path) -> dict[str, Any]:
        return await _run_graph(PAYLOAD_WATCHDOG, tmp_path)

    async def test_graph_completes(self, result: dict[str, Any]) -> None:
        assert result is not None

    async def test_no_diagnosis_produced(self, result: dict[str, Any]) -> None:
        assert "diagnosis" not in result or result.get("diagnosis") is None

    async def test_no_report_produced(self, result: dict[str, Any]) -> None:
        assert "report" not in result or result.get("report") is None

    async def test_warning_mentions_watchdog(self, result: dict[str, Any]) -> None:
        warnings = result.get("warnings", [])
        assert any("watchdog" in str(w).lower() for w in warnings)
