"""
Modèles de domaine pour la réception des alertes Alertmanager v4.

Format de référence : contrat webhook Alertmanager v4 (ia4ops-webhook-contract.md).
Une notification = un groupe d'alertes. Déduplication par fingerprint + startsAt.
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class AlertLabels(BaseModel):
    """Labels portés par une alerte individuelle."""

    alertname: str
    namespace: str
    severity: str | None = None
    # Label OTel Demo — à confirmer avec Fabian (service_name vs service)
    service_name: str | None = None

    model_config = {"extra": "allow"}  # accepte les labels supplémentaires inconnus


class AlertAnnotations(BaseModel):
    """Annotations textuelles d'une alerte (humainement lisibles)."""

    summary: str | None = None
    description: str | None = None
    runbook_url: str | None = None

    model_config = {"extra": "allow"}


class AlertItem(BaseModel):
    """Une alerte individuelle dans le groupe."""

    status: str  # "firing" | "resolved" — validé au niveau webhook
    labels: AlertLabels
    annotations: AlertAnnotations = Field(default_factory=AlertAnnotations)
    startsAt: datetime
    endsAt: datetime
    generatorURL: str = ""
    fingerprint: str  # clé de déduplication stable

    @property
    def is_resolved(self) -> bool:
        """Vrai si l'alerte est résolue (endsAt != epoch zéro)."""
        # Alertmanager utilise 0001-01-01T00:00:00Z pour "non résolue"
        return self.endsAt.year > 1


class AlertmanagerWebhook(BaseModel):
    """
    Payload complet d'une notification Alertmanager v4.

    Référence : https://prometheus.io/docs/alerting/latest/configuration/#webhook_config
    """

    version: str = Field(..., pattern="^4$")
    groupKey: str
    truncatedAlerts: int = 0
    status: str  # "firing" | "resolved"
    receiver: str
    groupLabels: dict[str, str]
    commonLabels: dict[str, str]
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str = ""
    alerts: list[AlertItem]

    @model_validator(mode="after")
    def alerts_not_empty(self) -> AlertmanagerWebhook:
        if not self.alerts:
            raise ValueError("Le webhook doit contenir au moins une alerte.")
        return self

    def make_dedup_key(self) -> str:
        """
        Clé composite pour ignorer les notifications répétées du même incident.
        Combine les fingerprints triés et le startsAt minimal.
        """
        fingerprints = sorted(a.fingerprint for a in self.alerts)
        starts = min(a.startsAt for a in self.alerts).isoformat()
        return f"{'-'.join(fingerprints)}:{starts}"

    def primary_alert(self) -> AlertItem:
        """Retourne l'alerte la plus ancienne du groupe (représentante principale)."""
        return min(self.alerts, key=lambda a: a.startsAt)

    def affected_services(self) -> list[str]:
        """Retourne la liste dédupliquée des services impactés dans ce groupe."""
        return list(
            {
                a.labels.service_name
                for a in self.alerts
                if a.labels.service_name is not None
            }
        )

    def is_watchdog(self) -> bool:
        """Vrai si c'est l'alerte de heartbeat Alertmanager — à ignorer."""
        return any(a.labels.alertname == "Watchdog" for a in self.alerts)
