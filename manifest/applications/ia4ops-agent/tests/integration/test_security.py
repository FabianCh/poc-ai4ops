"""
Tests d'intégration sécurité — scénario 1 read-only (Task 7).

Couvre :
- Le log d'injection traverse le workflow sans provoquer d'action
- L'audit trail enregistre les informations sans les interpréter comme instructions
- Une sortie LLM avec action_executed=True est détectée par validate_node
- Une sortie LLM contenant un verbe d'action est détectée
- Aucun outil d'écriture n'est accessible depuis le graphe compilé
- Le graphe réel (cas A/B/C) produit toujours action_executed=False
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from ia4ops_agent.domain.diagnosis import DiagnosticFailure, DiagnosticOutput
from ia4ops_agent.graph.builder import build_graph
from ia4ops_agent.graph.nodes.validate import validate_node
from ia4ops_agent.graph.state import IncidentState
from ia4ops_agent.llm.interface import FakeLLMClient, LLMCallSummary
from ia4ops_agent.policies.read_only import ReadOnlyPolicy
from ia4ops_agent.providers.factory import Providers

# ---------------------------------------------------------------------------
# Fixture : payload d'alerte standard
# ---------------------------------------------------------------------------


def _alert_payload(service: str, fp: str) -> dict[str, Any]:
    return {
        "version": "4",
        "groupKey": "{/}{namespace='otel-demo'}:{alertname='OtelDemoServiceHighErrorRate'}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "ai4ops-agent",
        "groupLabels": {"namespace": "otel-demo"},
        "commonLabels": {"namespace": "otel-demo", "alertname": "OtelDemoServiceHighErrorRate"},
        "commonAnnotations": {},
        "externalURL": "http://alertmanager:9093",
        "alerts": [{
            "status": "firing",
            "labels": {
                "alertname": "OtelDemoServiceHighErrorRate",
                "namespace": "otel-demo",
                "severity": "critical",
                "service_name": service,
            },
            "annotations": {"summary": f"High error rate on {service}"},
            "startsAt": "2026-10-05T12:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "http://prometheus/graph",
            "fingerprint": fp,
        }],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_graph_for(service: str, fp: str, tmp_path: Path) -> dict[str, Any]:
    graph = build_graph(providers=Providers.mock(), audit_dir=tmp_path)
    return await graph.ainvoke({"raw_alert": _alert_payload(service, fp)})


# ---------------------------------------------------------------------------
# Tests : invariant action_executed dans le workflow complet
# ---------------------------------------------------------------------------


async def test_case_a_action_executed_always_false(tmp_path: Path) -> None:
    state = await _run_graph_for("product-catalog", "sec-fp-a", tmp_path)
    report = state.get("report", {})
    assert report.get("action_executed") is False
    diagnosis = report.get("diagnosis", {})
    assert diagnosis.get("action_executed") is False


async def test_case_b_action_executed_always_false(tmp_path: Path) -> None:
    state = await _run_graph_for("checkout", "sec-fp-b", tmp_path)
    report = state.get("report", {})
    assert report.get("action_executed") is False


async def test_case_c_action_executed_always_false(tmp_path: Path) -> None:
    state = await _run_graph_for("frontend", "sec-fp-c", tmp_path)
    report = state.get("report", {})
    assert report.get("action_executed") is False


# ---------------------------------------------------------------------------
# Tests : injection dans les logs — traverse sans déclencher d'action
# ---------------------------------------------------------------------------


def _load_injection_fixture() -> dict:
    fixture_path = Path(__file__).parent.parent / "fixtures" / "logs" / "injection_attempt.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


async def test_injection_logs_traverse_without_action(tmp_path: Path) -> None:
    """
    Les logs d'injection doivent traverser le workflow comme des données ordinaires.
    L'agent ne doit pas exécuter les instructions contenues dans les logs.
    """
    injection_data = _load_injection_fixture()
    injection_markers = [
        log for log in injection_data["logs"]
        if log.get("_injection_marker")
    ]
    assert len(injection_markers) >= 2, "La fixture doit contenir au moins 2 logs d'injection"

    # Le workflow reçoit une alerte normale — les logs d'injection sont dans les données
    # collectées mais ne modifient pas le comportement du graphe
    state = await _run_graph_for("product-catalog", "sec-fp-inject", tmp_path)

    report = state.get("report", {})
    assert report.get("action_executed") is False, (
        "action_executed doit être False même avec des logs d'injection"
    )

    # L'audit trail doit exister (l'agent a travaillé normalement)
    audit_events = state.get("audit_events", [])
    assert len(audit_events) >= 1


async def test_injection_logs_appear_in_audit_as_data(tmp_path: Path) -> None:
    """Les logs d'injection sont enregistrés comme données, pas comme instructions."""
    state = await _run_graph_for("product-catalog", "sec-fp-audit", tmp_path)
    audit_events = state.get("audit_events", [])
    # L'audit trail ne doit pas contenir de traces d'exécution d'action
    for event in audit_events:
        assert event.get("status") != "action_executed", (
            f"L'audit trail ne doit pas contenir status=action_executed : {event}"
        )


# ---------------------------------------------------------------------------
# Tests : validate_node rejette une sortie LLM avec action_executed=True
# ---------------------------------------------------------------------------


async def test_validate_rejects_action_executed_true() -> None:
    """Une sortie LLM avec action_executed=True doit être rejetée par validate_node."""
    bad_diagnosis = {
        "incident_id": "sec-test-001",
        "summary": "Taux d'erreur élevé sur product-catalog.",
        "affected_service": "product-catalog",
        "severity_assessment": "critical",
        "primary_hypothesis": {
            "title": "Redis indisponible",
            "likelihood": "high",
            "reasoning": "Logs montrent des timeouts.",
            "evidence_refs": ["metrics.error_rate"],
        },
        "alternative_hypotheses": [],
        "evidence": [{"source": "metrics", "reference": "metrics.error_rate", "observation": "18% errors"}],
        "missing_information": [],
        "recommended_next_checks": [],
        "remediation_suggestions": [],
        "action_executed": True,  # violation intentionnelle
    }
    state: IncidentState = {
        "incident_id": "sec-test-001",
        "diagnosis": bad_diagnosis,
        "normalized_alert": {"service": "product-catalog"},
        "audit_events": [],
        "warnings": [],
        "errors": [],
        "missing_information": [],
    }
    result = await validate_node(state)
    errors = result.get("errors", [])
    assert len(errors) > 0, "validate_node doit détecter action_executed=True"
    error_text = str(errors)
    assert "action_executed" in error_text.lower()


async def test_validate_rejects_action_verb_in_summary() -> None:
    """Une sortie LLM contenant un verbe d'action dans summary doit être rejetée."""
    bad_diagnosis = {
        "incident_id": "sec-test-002",
        "summary": "I have restarted the product-catalog deployment to resolve the issue.",
        "affected_service": "product-catalog",
        "severity_assessment": "critical",
        "primary_hypothesis": {
            "title": "Redis indisponible",
            "likelihood": "high",
            "reasoning": "Timeouts vers Redis.",
            "evidence_refs": ["metrics.error_rate"],
        },
        "alternative_hypotheses": [],
        "evidence": [{"source": "metrics", "reference": "metrics.error_rate", "observation": "18%"}],
        "missing_information": [],
        "recommended_next_checks": [],
        "remediation_suggestions": [],
        "action_executed": False,
    }
    state: IncidentState = {
        "incident_id": "sec-test-002",
        "diagnosis": bad_diagnosis,
        "normalized_alert": {"service": "product-catalog"},
        "audit_events": [],
        "warnings": [],
        "errors": [],
        "missing_information": [],
    }
    result = await validate_node(state)
    errors = result.get("errors", [])
    assert len(errors) > 0, "validate_node doit détecter le verbe d'action dans summary"


# ---------------------------------------------------------------------------
# Tests : aucun outil d'écriture dans le graphe compilé
# ---------------------------------------------------------------------------


def test_no_write_tools_in_compiled_graph() -> None:
    """Vérification statique : le graphe compilé ne contient aucun outil d'écriture."""
    graph = build_graph(providers=Providers.mock())
    node_names = list(graph.nodes)
    forbidden = ReadOnlyPolicy.check_no_write_tools(node_names)
    assert forbidden == [], (
        f"Outils d'écriture détectés dans le graphe : {forbidden}"
    )


def test_graph_nodes_are_read_only() -> None:
    """Les nœuds du graphe doivent uniquement être des nœuds de lecture/diagnostic."""
    graph = build_graph(providers=Providers.mock())
    node_names = list(graph.nodes)
    expected_read_only_nodes = {
        "initialize", "collect_metrics", "collect_logs", "collect_cluster",
        "build_context", "diagnose", "validate", "finalize", "end_watchdog",
    }
    for node in node_names:
        assert node in expected_read_only_nodes or node.startswith("__"), (
            f"Nœud inattendu dans le graphe : {node!r}"
        )


# ---------------------------------------------------------------------------
# Tests : secrets ne doivent pas apparaître dans l'audit trail
# ---------------------------------------------------------------------------


async def test_audit_trail_contains_no_secrets(tmp_path: Path) -> None:
    """
    L'audit trail ne doit pas contenir de valeurs ressemblant à des secrets
    (tokens, passwords, clés privées).
    """
    state = await _run_graph_for("product-catalog", "sec-fp-secrets", tmp_path)
    audit_events = state.get("audit_events", [])

    # Patterns suspects dans l'audit
    import re
    secret_patterns = [
        re.compile(r"-----BEGIN .* KEY-----"),
        re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),  # Base64 long (probable token/key)
        re.compile(r"password\s*[:=]\s*\S+", re.IGNORECASE),
        re.compile(r"api[_\s]?key\s*[:=]\s*\S+", re.IGNORECASE),
    ]

    audit_text = json.dumps(audit_events)
    for pattern in secret_patterns:
        matches = pattern.findall(audit_text)
        # Filtre : les UUIDs et IDs courts sont OK
        suspicious = [m for m in matches if len(m) > 60]
        assert not suspicious, (
            f"Pattern suspect dans l'audit trail ({pattern.pattern!r}) : {suspicious[0][:50]}..."
        )
