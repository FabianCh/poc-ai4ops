"""
Modèles intermédiaires pour la communication avec le LLM.

Sépare la réponse brute du LLM (non validée) du modèle de domaine validé
(DiagnosticOutput). Permet de journaliser les erreurs de parsing sans
propager des données non vérifiées dans le workflow.
"""

from typing import Any

from pydantic import BaseModel, Field


class LLMRawResponse(BaseModel):
    """
    Réponse brute du LLM avant validation Pydantic.
    Stockée pour audit en cas d'échec de parsing.
    """

    raw_content: str | dict[str, Any] | None = None
    model_name: str
    prompt_version: str
    attempt: int = 1
    # Durée de l'appel LLM en ms
    duration_ms: int | None = None
    # Tokens consommés (si disponible via l'API)
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


class LLMParseError(BaseModel):
    """
    Erreur de parsing ou de validation de la sortie LLM.
    Journalisée dans l'audit trail, jamais propagée silencieusement.
    """

    attempt: int
    error_type: str  # "pydantic_validation" | "json_parse" | "timeout" | "api_error"
    error_message: str
    raw_response: str | None = Field(
        None,
        description="Extrait de la réponse brute (tronquée si > 500 chars).",
        max_length=500,
    )


class LLMCallSummary(BaseModel):
    """
    Résumé d'un appel LLM complet (y compris les retries).
    Enregistré dans l'AuditEvent du nœud diagnose.
    """

    model_name: str
    prompt_version: str
    total_attempts: int
    success: bool
    errors: list[LLMParseError] = Field(default_factory=list)
    total_duration_ms: int | None = None
