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

from pydantic import BaseModel

# Réexport du modèle de domaine — le webhook est déjà complet dans alerts.py
from ia4ops_agent.domain.alerts import AlertmanagerWebhook as AlertWebhookRequest

__all__ = ["AlertWebhookRequest", "AlertAccepted", "AlertDuplicate", "IncidentResponse"]


class AlertAccepted(BaseModel):
    """
    Réponse immédiate pour un webhook accepté (HTTP 200).
    Le traitement est asynchrone — le diagnostic n'est pas encore disponible.
    """

    incident_id: str
    status: Literal["accepted"] = "accepted"
    message: str = "Webhook reçu. Diagnostic en cours en arrière-plan."


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
    status: Literal["pending", "running", "completed", "completed_with_errors", "failed"]
    received_at: datetime | None = None
    finalized_at: datetime | None = None


class IncidentResponse(BaseModel):
    """
    Réponse complète pour GET /api/v1/incidents/{incident_id}.

    - status "pending" / "running" : diagnosis est None, poll à nouveau plus tard
    - status "completed*" : diagnosis contient le rapport complet
    - status "failed" : failure contient la raison
    """

    incident_id: str
    status: Literal["pending", "running", "completed", "completed_with_errors", "failed"]
    received_at: str | None = None
    alert_status: Literal["firing", "resolved"] | None = None
    resolved_at: str | None = None
    # Rapport final (présent quand status = completed*)
    report: dict | None = None
    # Raison d'échec (présent quand status = failed)
    failure: str | None = None
