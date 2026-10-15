"""Unit tests for Gemini response validation and repair attempts."""

from typing import Any

import pytest

from ia4ops_agent.llm import client as client_module
from ia4ops_agent.llm.client import GeminiVertexClient


def _diagnosis(*, alternative_evidence_refs: list[str]) -> dict[str, Any]:
    return {
        "incident_id": "agent-inc-1",
        "summary": "Un taux d'erreur élevé est observé.",
        "affected_service": "product-catalog",
        "severity_assessment": "critical",
        "primary_hypothesis": {
            "title": "Taux d'erreur élevé",
            "likelihood": "high",
            "reasoning": "L'alerte et les métriques indiquent des erreurs.",
            "evidence_refs": ["alert-error-rate"],
        },
        "alternative_hypotheses": [
            {
                "title": "Saturation de dépendance",
                "likelihood": "low",
                "reasoning": "Cette possibilité n'est pas confirmée.",
                "evidence_refs": alternative_evidence_refs,
            }
        ],
        "evidence": [
            {
                "source": "alert",
                "reference": "alert-error-rate",
                "observation": "L'alerte de taux d'erreur est active.",
            }
        ],
    }


async def test_validation_failure_is_included_in_the_next_model_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        _diagnosis(alternative_evidence_refs=[]),
        _diagnosis(alternative_evidence_refs=["alert-error-rate"]),
    ]
    received_messages: list[list[Any]] = []

    class FakeStructuredModel:
        def invoke(self, messages: list[Any]) -> dict[str, Any]:
            received_messages.append(list(messages))
            return responses[len(received_messages) - 1]

    class FakeModel:
        def with_structured_output(
            self,
            schema: dict[str, Any],
            *,
            method: str,
        ) -> FakeStructuredModel:
            assert schema == {}
            assert method == "json_mode"
            return FakeStructuredModel()

    async def skip_backoff(_: float) -> None:
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", skip_backoff)
    client = GeminiVertexClient.__new__(GeminiVertexClient)
    client.model_name = "test-model"
    client._project = "test-project"
    client._location = "test-location"
    client._clean_schema = {}
    client._llm = FakeModel()

    output, summary = await client.diagnose({"incident": {"id": "agent-inc-1"}})

    assert output.alternative_hypotheses[0].evidence_refs == ["alert-error-rate"]
    assert summary.total_attempts == 2
    assert len(received_messages) == 2
    repair_request = received_messages[1][-1].content
    assert "alternative_hypotheses.0.evidence_refs" in repair_request
    assert "recopie exactement une valeur de evidence.reference" in repair_request


def test_gemini_client_bounds_thinking_and_allows_long_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un contexte riche allonge le raisonnement : budget borné et timeout de 120 s."""
    captured: dict[str, Any] = {}

    class FakeChat:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(client_module, "ChatGoogleGenerativeAI", FakeChat)
    GeminiVertexClient("gemini-2.5-flash", "project", "europe-west1")

    assert captured["thinking_budget"] == 1024
    assert captured["max_output_tokens"] == 4096  # une génération qui s'emballe échoue vite
    assert captured["max_retries"] == 0
    assert captured["temperature"] == 0
    assert client_module.TIMEOUT_SECONDS == 120
