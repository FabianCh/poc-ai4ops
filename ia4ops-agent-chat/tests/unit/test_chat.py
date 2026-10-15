"""Tests du parsing de commande et du rendu du chatbot."""

import pytest

from ia4ops_agent.chat_app import (
    format_pending_alert,
    format_report,
    parse_investigation_message,
)


def test_parse_investigation_command_with_question_and_window() -> None:
    request = parse_investigation_message(
        "/investigate product-catalog 30 | Pourquoi la latence augmente ?"
    )

    assert request.service == "product-catalog"
    assert request.window_minutes == 30
    assert request.question == "Pourquoi la latence augmente ?"


def test_parse_investigation_command_uses_default_window_and_question() -> None:
    request = parse_investigation_message("/investigate checkout")

    assert request.window_minutes == 15
    assert request.question.startswith("Analyser les signaux disponibles")


@pytest.mark.parametrize(
    "message",
    [
        "Peux-tu investiguer checkout ?",
        "/investigate product/catalog",
        "/investigate checkout 61 | Pourquoi ?",
        "/investigate checkout 15 |   ",
    ],
)
def test_parse_investigation_command_rejects_unbounded_or_incomplete_input(
    message: str,
) -> None:
    with pytest.raises(ValueError):
        parse_investigation_message(message)


def test_mock_report_rendering_distinguishes_real_observations_from_mock_diagnosis() -> None:
    content = format_report(
        {
            "incident_id": "inc-test",
            "window_minutes": 15,
            "source_status": {"metrics": "success", "logs": "success"},
            "context": {
                "observations": {
                    "metrics": {"error_rate": 0.2, "window_minutes": 15},
                    "logs": {
                        "error_count": 3,
                        "top_patterns": [{"level": "error", "count": 3, "pattern": "timeout"}],
                    },
                }
            },
            "diagnosis": {
                "summary": "Diagnostic d'essai",
                "evidence": [{"reference": "metrics.error_rate", "observation": "20 %"}],
            },
        },
        "mock",
        "mock",
    )

    assert "3 erreur(s) agrégée(s)" in content
    assert "observations affichées sont synthétiques" in content
    assert "diagnostic ci-dessous est préconfiguré" in content
    assert "Diagnostic d'essai" in content
    assert "Aucune action n'a été exécutée" in content


def test_pending_alert_rendering_requests_operator_approval() -> None:
    content = format_pending_alert(
        {
            "alert_name": "OtelDemoServiceHighErrorRate",
            "service": "checkout",
            "affected_services": ["checkout", "payment"],
            "namespace": "otel-demo",
            "severity": "critical",
            "starts_at": "2026-10-15T12:00:00Z",
            "alerts_count": 2,
            "summary": "High error rate",
            "description": "Errors are above threshold.",
        }
    )

    assert "⚠️ Alerte à traiter" in content
    assert "NOUVELLE ALERTE — EN ATTENTE DE VOTRE DÉCISION" in content
    assert "checkout, payment" in content
    assert "2" in content
    assert "Aucune collecte ni aucun diagnostic ne démarre sans votre choix" in content
    assert "lancer une investigation en lecture seule ou ignorer" in content
