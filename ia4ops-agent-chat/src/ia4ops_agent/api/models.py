"""
Modèles de requête/réponse de l'API FastAPI.

Séparation claire entre :
- Les modèles d'entrée webhook (validés par Pydantic, identiques au domaine)
- Les modèles de réponse HTTP (forme publique de l'API)

Note : AlertmanagerWebhook est réutilisé depuis le domaine directement.
On ne re-définit pas les modèles d'entrée — on réexporte pour la lisibilité.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Réexport du modèle de domaine — le webhook est déjà complet dans alerts.py
from ia4ops_agent.domain.alerts import AlertmanagerWebhook as AlertWebhookRequest

__all__ = [
    "AlertWebhookRequest",
    "AlertAccepted",
    "AlertDuplicate",
    "AlertPending",
    "AlertDecisionRequest",
    "AlertDecisionResponse",
    "PendingAlert",
    "IncidentResponse",
    "InvestigationAccepted",
    "InvestigationInterpretation",
    "InvestigationInterpretationRequest",
    "InvestigationRequest",
]


class AlertAccepted(BaseModel):
    """
    Réponse immédiate réservée aux notifications ignorées sans diagnostic
    (par exemple Alertmanager Watchdog).
    """

    incident_id: str
    status: Literal["accepted"] = "accepted"
    message: str = "Notification reçue."


class AlertPending(BaseModel):
    """Alerte reçue, en attente de décision explicite d'un opérateur."""

    incident_id: str
    status: Literal["awaiting_approval"] = "awaiting_approval"
    message: str = "Alerte reçue. Le diagnostic attend l'approbation d'un opérateur."


class PendingAlert(BaseModel):
    """Résumé expurgé présenté aux opérateurs dans le chatbot."""

    incident_id: str
    alert_name: str
    service: str
    affected_services: list[str]
    namespace: str
    severity: str
    summary: str | None = None
    description: str | None = None
    starts_at: datetime
    received_at: str
    alerts_count: int


class AlertDecisionRequest(BaseModel):
    """Décision explicite d'investiguer ou d'ignorer une alerte."""

    action: Literal["investigate", "ignore"]
    window_minutes: int = Field(default=15, ge=1, le=60)


class AlertDecisionResponse(BaseModel):
    """Confirmation de la décision et indication de l'état du traitement."""

    incident_id: str
    status: Literal["pending", "ignored"]
    message: str


class InvestigationRequest(BaseModel):
    """Entrée bornée d'une investigation explicitement demandée par un opérateur."""

    service: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$",
    )
    window_minutes: int = Field(default=15, ge=1, le=60)
    question: str = Field(min_length=1, max_length=500)

    @field_validator("service", "question")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Cette valeur ne peut pas être vide.")
        return value


class InvestigationInterpretationRequest(BaseModel):
    """Demande textuelle à interpréter avant toute investigation."""

    message: str = Field(min_length=1, max_length=2000)
    previous_message: str | None = Field(default=None, max_length=2000)

    @field_validator("message", "previous_message")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Cette valeur ne peut pas être vide.")
        return value


class InvestigationInterpretation(BaseModel):
    """Résultat borné de l'extraction d'une demande d'investigation."""

    status: Literal["ready", "needs_clarification"]
    service: str = Field(max_length=63)
    window_minutes: int = Field(ge=1, le=60)
    question: str = Field(max_length=500)
    clarification_question: str = Field(max_length=500)

    @field_validator("service", "question", "clarification_question")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_interpretation(self) -> InvestigationInterpretation:
        if self.status == "ready":
            if not self.service or not self.question:
                raise ValueError("Une demande prête doit préciser le service et la question.")
            if self.clarification_question:
                raise ValueError("Une demande prête ne doit pas demander de précision.")
        elif not self.clarification_question:
            raise ValueError("Une précision doit être formulée pour une demande incomplète.")
        return self


class InvestigationAccepted(BaseModel):
    """Réponse immédiate à une investigation mise en file de traitement."""

    incident_id: str
    status: Literal["accepted"] = "accepted"
    message: str = "Investigation acceptée. Le diagnostic démarre en arrière-plan."


class AlertDuplicate(BaseModel):
    """
    Réponse pour un webhook déjà connu (même fingerprint+startsAt).
    HTTP 200 — Alertmanager ne doit pas réessayer.
    """

    incident_id: str
    status: Literal["duplicate_ignored"] = "duplicate_ignored"
    message: str = "Notification déjà reçue. Traitement ignoré."


class AlertResolved(BaseModel):
    """Réponse à une notification de résolution, sans relancer le diagnostic."""

    incident_id: str | None
    status: Literal["resolved", "resolved_unmatched"]
    message: str


class IncidentStatus(BaseModel):
    """
    Résumé du statut d'un incident en cours ou terminé.
    Utilisé dans la réponse GET /api/v1/incidents/{incident_id}.
    """

    incident_id: str
    status: Literal[
        "awaiting_approval",
        "pending",
        "running",
        "completed",
        "completed_with_errors",
        "failed",
        "ignored",
        "resolved",
    ]
    received_at: datetime | None = None
    finalized_at: datetime | None = None


class IncidentResponse(BaseModel):
    """
    Réponse complète pour GET /api/v1/incidents/{incident_id}.

    - status "awaiting_approval" / "pending" / "running" : aucun rapport final
    - status "completed*" : diagnosis contient le rapport complet
    - status "failed" : failure contient la raison
    """

    incident_id: str
    status: Literal[
        "awaiting_approval",
        "pending",
        "running",
        "completed",
        "completed_with_errors",
        "failed",
        "ignored",
        "resolved",
    ]
    received_at: str | None = None
    alert_status: Literal["firing", "resolved"] | None = None
    progress: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    resolved_at: str | None = None
    # Rapport final (présent quand status = completed*)
    report: dict | None = None
    # Raison d'échec (présent quand status = failed)
    failure: str | None = None
