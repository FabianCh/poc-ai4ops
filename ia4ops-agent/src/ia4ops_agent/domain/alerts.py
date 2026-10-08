"""
Modèles de domaine pour la réception des alertes Alertmanager v4.

Format de référence : contrat webhook Alertmanager v4 (ia4ops-webhook-contract.md).
Une notification = un groupe d'alertes. Déduplication par fingerprint + startsAt.
"""

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# Suffixes générés par Kubernetes sur les noms de pods : <nom>-<hash du ReplicaSet>-<id>
# (Deployment), <nom>-<id> (DaemonSet, id contenant un chiffre) et <nom>-<ordinal> (StatefulSet).
_POD_DEPLOYMENT_SUFFIX = re.compile(r"-[a-z0-9]{8,10}-[a-z0-9]{5}$")
_POD_DAEMONSET_SUFFIX = re.compile(r"-(?=[a-z]*\d)[a-z0-9]{5}$")
_POD_STATEFULSET_SUFFIX = re.compile(r"-\d+$")


def _pod_workload_name(pod: str) -> str:
    """Nom du workload déduit du nom d'un pod (sans les suffixes générés par Kubernetes)."""
    for pattern in (_POD_DEPLOYMENT_SUFFIX, _POD_STATEFULSET_SUFFIX, _POD_DAEMONSET_SUFFIX):
        stripped = pattern.sub("", pod)
        if stripped != pod and stripped:
            return stripped
    return pod


def service_from_labels(labels: Mapping[str, Any] | BaseModel) -> str | None:
    """
    Service concerné par une alerte, d'après ses labels.

    Les alertes applicatives portent `service_name` (ou `service`) ; les alertes de conteneur
    (CPU, mémoire, OOM) portent seulement `container` et `pod`. Ordre : service_name, service,
    container, puis le nom du pod sans ses suffixes.
    """
    values = labels.model_dump() if isinstance(labels, BaseModel) else labels
    for key in ("service_name", "service", "container"):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    pod = values.get("pod")
    if isinstance(pod, str) and pod.strip():
        return _pod_workload_name(pod.strip())
    return None


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

    status: Literal["firing", "resolved"]
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
    status: Literal["firing", "resolved"]
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
        services = (service_from_labels(a.labels) for a in self.alerts)
        return list(dict.fromkeys(service for service in services if service is not None))

    def is_watchdog(self) -> bool:
        """Vrai si c'est l'alerte de heartbeat Alertmanager — à ignorer."""
        return any(a.labels.alertname == "Watchdog" for a in self.alerts)
