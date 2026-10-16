"""Tests du parsing de commande et du rendu du chatbot."""

import pytest

import ia4ops_agent.chat_app as chat_app
from ia4ops_agent.api.models import InvestigationRequest
from ia4ops_agent.chat_app import (
    _track_investigation,
    format_investigation_confirmation,
    format_investigation_progress,
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


def test_investigation_confirmation_shows_parameters_before_starting() -> None:
    content = format_investigation_confirmation(
        InvestigationRequest(
            service="checkout",
            window_minutes=30,
            question="Pourquoi les erreurs augmentent ?",
        )
    )

    assert "checkout" in content
    assert "30 minutes" in content
    assert "Pourquoi les erreurs augmentent ?" in content
    assert "Aucune collecte ni aucun diagnostic ne démarre avant votre confirmation" in content


def test_investigation_progress_shows_spinner_and_only_the_active_step() -> None:
    content = format_investigation_progress(
        "checkout",
        "Collecte des traces",
        "⠙",
    )

    assert "Investigation de `checkout` en cours" in content
    assert "⠙ **Collecte des traces**" in content
    assert "Étapes terminées" not in content


async def test_investigation_tracker_updates_one_message_through_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incidents = iter(
        [
            {"status": "running", "progress": "Collecte des métriques"},
            {"status": "running", "progress": "Collecte des logs"},
            {"status": "completed", "report": {"result": "ok"}},
        ]
    )

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return next(incidents)

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _: str) -> FakeResponse:
            return FakeResponse()

    class ProgressMessage:
        content = ""

        def __init__(self) -> None:
            self.updates: list[str] = []

        async def update(self) -> None:
            self.updates.append(self.content)

    async def no_sleep(_: float) -> None:
        return None

    progress = ProgressMessage()
    monkeypatch.setattr(chat_app.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(chat_app.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(chat_app, "format_report", lambda *_: "Rapport final")

    await _track_investigation("inc-test", "checkout", progress)

    assert "⠋ **Collecte des métriques**" in progress.updates[0]
    assert "⠙ **Collecte des logs**" in progress.updates[1]
    assert progress.updates[2] == "Rapport final"


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
