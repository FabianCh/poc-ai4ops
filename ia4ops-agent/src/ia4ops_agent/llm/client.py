"""
GeminiVertexClient — client LLM production via Vertex AI.

Utilise ChatGoogleGenerativeAI (langchain-google-genai) avec vertexai=True
pour forcer le backend Vertex AI (pas la Gemini Developer API).
L'authentification repose sur GOOGLE_APPLICATION_CREDENTIALS (ADC).

Structured output :
  Le schéma Pydantic de DiagnosticOutput est nettoyé avant envoi car
  Vertex AI n'accepte qu'un sous-ensemble de JSON Schema.
  La validation Pydantic complète est réappliquée localement après réception.

Retries :
  - Erreurs transitoires (timeout, 429, 5xx) : jusqu'à MAX_ATTEMPTS avec backoff
  - Erreurs permanentes (404, 403, config invalide) : échec immédiat, pas de retry
"""

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import ValidationError

from ia4ops_agent.domain.diagnosis import DiagnosticOutput
from ia4ops_agent.llm.interface import DiagnosisError
from ia4ops_agent.llm.models import LLMCallSummary, LLMParseError
from ia4ops_agent.llm.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 60
BACKOFF_BASE_SECONDS = 2.0

# Mots-clés JSON Schema non supportés par Vertex AI structured output.
# Ne jamais retirer : type, properties, required, enum, items, $defs, $ref
_UNSUPPORTED_SCHEMA_FIELDS = frozenset({
    "maxLength", "minLength",
    "minItems", "maxItems",
    "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf",
    "pattern",
})

# Codes d'erreur HTTP indiquant une erreur permanente (pas de retry)
_PERMANENT_ERROR_CODES = frozenset({"404", "403", "400", "401"})


def _clean_schema_for_vertex(schema: dict) -> dict:
    """
    Retire récursivement les mots-clés non supportés par Vertex AI.
    Ne touche pas à type, properties, required, enum, items, $defs, $ref.
    La validation Pydantic complète est réappliquée localement après désérialisation.
    """
    if isinstance(schema, dict):
        return {
            k: _clean_schema_for_vertex(v)
            for k, v in schema.items()
            if k not in _UNSUPPORTED_SCHEMA_FIELDS
        }
    if isinstance(schema, list):
        return [_clean_schema_for_vertex(item) for item in schema]
    return schema


def _is_permanent_error(exc: Exception) -> bool:
    """
    Retourne True si l'erreur est permanente et ne justifie pas de retry.
    Détecte les 404, 403, 400, 401 et les erreurs de configuration.
    """
    msg = str(exc)
    # Codes HTTP permanents
    for code in _PERMANENT_ERROR_CODES:
        if f" {code} " in msg or msg.startswith(code):
            return True
    # Mots-clés d'erreurs de configuration
    permanent_keywords = [
        "was not found",
        "does not have access",
        "Permission denied",
        "PERMISSION_DENIED",
        "UNAUTHENTICATED",
        "Invalid schema",
        "Unknown field for Schema",
        "API key required",
        "invalid_grant",
    ]
    return any(kw in msg for kw in permanent_keywords)


class GeminiVertexClient:
    """
    Client LLM production — Gemini via Vertex AI (ChatGoogleGenerativeAI + vertexai=True).

    Implémente le Protocol LLMClient défini dans llm/interface.py.
    L'authentification utilise GOOGLE_APPLICATION_CREDENTIALS (ADC) — pas d'API key.
    Instancié une seule fois dans le lifespan FastAPI.
    """

    def __init__(self, model_name: str, project: str, location: str) -> None:
        self.model_name = model_name
        self._project = project
        self._location = location

        # Schéma nettoyé calculé une seule fois à l'init
        raw_schema = DiagnosticOutput.model_json_schema()
        self._clean_schema = _clean_schema_for_vertex(raw_schema)

        # vertexai=True → backend Vertex AI, pas Gemini Developer API
        # L'auth repose sur GOOGLE_APPLICATION_CREDENTIALS (ADC)
        self._llm = ChatGoogleGenerativeAI(
            model=model_name,
            vertexai=True,
            project=project,
            location=location,
            temperature=0,
            max_retries=0,  # retries gérés manuellement
        )

        logger.info(
            "GeminiVertexClient initialisé. model=%s project=%s location=%s",
            model_name, project, location,
        )

    async def diagnose(
        self,
        incident_context: dict[str, Any],
    ) -> tuple[DiagnosticOutput, LLMCallSummary]:
        """
        Produit un diagnostic structuré à partir du contexte d'incident.

        Retourne (DiagnosticOutput, LLMCallSummary) ou lève DiagnosisError.
        Les erreurs permanentes (404, 403, config) échouent immédiatement.
        Les erreurs transitoires (timeout, 429, 5xx) sont retentées jusqu'à MAX_ATTEMPTS.
        """
        errors: list[LLMParseError] = []
        total_start = time.monotonic()

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=build_user_message(incident_context)),
        ]

        structured_llm = self._llm.with_structured_output(
            self._clean_schema,
            method="json_mode",
        )

        for attempt in range(1, MAX_ATTEMPTS + 1):
            call_start = time.monotonic()

            try:
                raw_result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: structured_llm.invoke(messages),
                    ),
                    timeout=TIMEOUT_SECONDS,
                )

                duration_ms = int((time.monotonic() - call_start) * 1000)

                # Revalider avec Pydantic complet (les contraintes retirées du schéma
                # sont réappliquées ici)
                if isinstance(raw_result, dict):
                    output = DiagnosticOutput(**raw_result)
                elif isinstance(raw_result, DiagnosticOutput):
                    output = raw_result
                else:
                    raise ValueError(f"Type de réponse inattendu : {type(raw_result)}")

                # Défense en profondeur — invariant scénario 1
                if output.action_executed is not False:
                    raise ValueError("Invariant violé : action_executed != False")

                total_duration_ms = int((time.monotonic() - total_start) * 1000)
                summary = LLMCallSummary(
                    model_name=self.model_name,
                    prompt_version=PROMPT_VERSION,
                    total_attempts=attempt,
                    success=True,
                    errors=errors,
                    total_duration_ms=total_duration_ms,
                )
                logger.info(
                    "Diagnostic OK. attempt=%d duration_ms=%d service=%s severity=%s",
                    attempt, duration_ms,
                    output.affected_service, output.severity_assessment,
                )
                return output, summary

            except asyncio.TimeoutError:
                err = LLMParseError(
                    attempt=attempt,
                    error_type="timeout",
                    error_message=f"Timeout après {TIMEOUT_SECONDS}s",
                )
                errors.append(err)
                logger.warning("Timeout LLM. attempt=%d/%d", attempt, MAX_ATTEMPTS)

            except ValidationError as exc:
                err = LLMParseError(
                    attempt=attempt,
                    error_type="pydantic_validation",
                    error_message=str(exc)[:500],
                )
                errors.append(err)
                logger.warning(
                    "Validation Pydantic échouée. attempt=%d/%d : %s",
                    attempt, MAX_ATTEMPTS, str(exc)[:200],
                )
                if attempt < MAX_ATTEMPTS:
                    messages.append(
                        HumanMessage(content=_validation_correction_message(exc))
                    )

            except Exception as exc:  # noqa: BLE001
                error_msg = str(exc)[:500]

                # Erreur permanente → échec immédiat, pas de retry
                if _is_permanent_error(exc):
                    logger.error(
                        "Erreur permanente Vertex AI — pas de retry. "
                        "model=%s project=%s location=%s error_type=%s message=%s",
                        self.model_name, self._project, self._location,
                        type(exc).__name__, error_msg[:300],
                    )
                    raise DiagnosisError(
                        reason=f"Erreur permanente ({type(exc).__name__}) : {error_msg}",
                        attempts=attempt,
                    ) from exc

                # Erreur transitoire → on retente
                err = LLMParseError(
                    attempt=attempt,
                    error_type="api_error",
                    error_message=error_msg,
                )
                errors.append(err)
                logger.warning(
                    "Erreur transitoire. attempt=%d/%d type=%s : %s",
                    attempt, MAX_ATTEMPTS, type(exc).__name__, error_msg[:200],
                )

            # Backoff exponentiel avant la prochaine tentative
            if attempt < MAX_ATTEMPTS:
                backoff = BACKOFF_BASE_SECONDS ** attempt
                logger.debug("Backoff %.1fs avant tentative %d", backoff, attempt + 1)
                await asyncio.sleep(backoff)

        # Toutes les tentatives épuisées
        last_error = errors[-1].error_message if errors else "Erreur inconnue"
        logger.error(
            "Diagnostic échoué après %d tentatives. model=%s project=%s location=%s",
            MAX_ATTEMPTS, self.model_name, self._project, self._location,
        )
        raise DiagnosisError(
            reason=f"Échec après {MAX_ATTEMPTS} tentatives : {last_error}",
            attempts=MAX_ATTEMPTS,
        )


def _validation_correction_message(exc: ValidationError) -> str:
    """Ask the model to repair schema violations without echoing its raw response."""
    details = []
    for error in exc.errors(include_input=False)[:10]:
        location = ".".join(str(part) for part in error["loc"]) or "diagnostic"
        details.append(f"- {location}: {error['msg']}")
    if not details:
        details.append("- La réponse ne respecte pas le schéma de diagnostic.")

    return (
        "La réponse précédente n'a pas passé la validation. Corrige uniquement les erreurs "
        "ci-dessous et retourne un diagnostic complet conforme au schéma.\n"
        + "\n".join(details)
        + "\nChaque hypothèse doit référencer au moins une preuve existant dans evidence ; "
        "recopie exactement une valeur de evidence.reference dans evidence_refs. "
        "N'invente pas de preuve et omets toute hypothèse alternative non étayée."
    )[:2000]
