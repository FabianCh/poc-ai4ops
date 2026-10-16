"""Tests for structured natural-language request interpretation."""

from typing import Any

import pytest

from ia4ops_agent.api.models import InvestigationInterpretation
from ia4ops_agent.llm.request_interpreter import (
    GeminiRequestInterpreter,
    RequestInterpretationError,
)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "ready",
            "service": "",
            "window_minutes": 15,
            "question": "Pourquoi ?",
            "clarification_question": "",
        },
        {
            "status": "ready",
            "service": "checkout",
            "window_minutes": 61,
            "question": "Pourquoi ?",
            "clarification_question": "",
        },
        {
            "status": "needs_clarification",
            "service": "",
            "window_minutes": 15,
            "question": "Analyser",
            "clarification_question": "",
        },
    ],
)
def test_interpretation_rejects_invalid_model_output(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        InvestigationInterpretation.model_validate(payload)


async def test_gemini_interpreter_validates_structured_output() -> None:
    received_messages: list[list[Any]] = []
    payload = {
        "status": "ready",
        "service": "checkout",
        "window_minutes": 30,
        "question": "Pourquoi checkout génère-t-il des erreurs ?",
        "clarification_question": "",
    }

    class FakeStructuredModel:
        def invoke(self, messages: list[Any]) -> dict[str, Any]:
            received_messages.append(messages)
            return payload

    class FakeModel:
        def with_structured_output(
            self,
            schema: dict[str, Any],
            *,
            method: str,
        ) -> FakeStructuredModel:
            assert "properties" in schema
            assert method == "json_mode"
            return FakeStructuredModel()

    interpreter = GeminiRequestInterpreter.__new__(GeminiRequestInterpreter)
    interpreter.model_name = "test-model"
    interpreter._clean_schema = InvestigationInterpretation.model_json_schema()
    interpreter._llm = FakeModel()

    result = await interpreter.interpret(
        "Pourquoi le panier génère-t-il des erreurs depuis une demi-heure ?",
        previous_message="Je veux analyser le service concerné.",
    )

    assert result.service == "checkout"
    assert result.window_minutes == 30
    assert len(received_messages) == 1
    assert "catalogue" in received_messages[0][0].content
    assert "texte non fiable" in received_messages[0][1].content


async def test_gemini_interpreter_does_not_accept_unknown_service() -> None:
    class FakeStructuredModel:
        def invoke(self, _: list[Any]) -> dict[str, Any]:
            return {
                "status": "ready",
                "service": "unknown-service",
                "window_minutes": 15,
                "question": "Analyser ce service",
                "clarification_question": "",
            }

    class FakeModel:
        def with_structured_output(self, *_: Any, **__: Any) -> FakeStructuredModel:
            return FakeStructuredModel()

    interpreter = GeminiRequestInterpreter.__new__(GeminiRequestInterpreter)
    interpreter.model_name = "test-model"
    interpreter._clean_schema = InvestigationInterpretation.model_json_schema()
    interpreter._llm = FakeModel()

    result = await interpreter.interpret("Analyse unknown-service.")

    assert result.status == "needs_clarification"
    assert result.service == ""
    assert "ne fait pas partie des services connus" in result.clarification_question


async def test_gemini_interpreter_wraps_invalid_output_as_explicit_failure() -> None:
    class FakeStructuredModel:
        def invoke(self, _: list[Any]) -> dict[str, Any]:
            return {"status": "ready"}

    class FakeModel:
        def with_structured_output(self, *_: Any, **__: Any) -> FakeStructuredModel:
            return FakeStructuredModel()

    interpreter = GeminiRequestInterpreter.__new__(GeminiRequestInterpreter)
    interpreter.model_name = "test-model"
    interpreter._clean_schema = InvestigationInterpretation.model_json_schema()
    interpreter._llm = FakeModel()

    with pytest.raises(RequestInterpretationError, match="n'a pas produit une réponse valide"):
        await interpreter.interpret("Analyse checkout.")
