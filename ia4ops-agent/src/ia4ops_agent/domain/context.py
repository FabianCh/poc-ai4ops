"""
Modèle du contexte d'incident transmis au LLM.

Le contexte est structuré, compact et borné — jamais des volumes bruts.
Référence : ia4ops-scenario1-reference.md section 11.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

SourceStatus = Literal["not_started", "success", "partial", "unavailable", "invalid"]


class IncidentInfo(BaseModel):
    """Informations d'identification de l'incident."""

    id: str
    alert_name: str
    service: str
    namespace: str
    severity: str
    started_at: str  # ISO 8601
    alerts_count: int | None = Field(None, description="Nombre d'alertes du groupe Alertmanager")
    # Annotations de l'alerte : texte externe donc non fiable (borné à la construction)
    summary: str | None = None
    description: str | None = None
    runbook_url: str | None = None


class MetricsObservation(BaseModel):
    """Métriques agrégées pour la fenêtre d'observation."""

    error_rate: float | None = Field(None, description="Taux d'erreur (0.0–1.0)")
    latency_p95_ms: float | None = None
    cpu_ratio: float | None = Field(None, description="Ratio CPU (cœurs utilisés / limite)")
    memory_ratio: float | None = Field(None, description="Ratio mémoire (utilisé / limite)")
    request_rate: float | None = Field(None, description="Requêtes par seconde")
    cpu_cores: float | None = Field(None, description="Cœurs CPU consommés (sans limite CPU)")
    memory_working_set_mb: float | None = None
    memory_limit_mb: float | None = None
    restarts_10m: int | None = Field(None, description="Redémarrages du conteneur sur 10 min")
    oom_killed: bool | None = Field(None, description="Redémarrage récent après un OOMKilled")
    window_minutes: int = 15
    extra: dict[str, Any] = Field(default_factory=dict)


class LogPattern(BaseModel):
    """Motif d'erreur récurrent dans les logs."""

    pattern: str
    count: int
    sample_message: str | None = None


class LogsObservation(BaseModel):
    """Résumé des logs d'erreur sur la fenêtre d'observation."""

    error_count: int = 0
    top_patterns: list[LogPattern] = Field(default_factory=list)
    # Identifiants permettant de retrouver les événements source (traçabilité)
    sample_event_ids: list[str] = Field(default_factory=list)
    window_minutes: int = 15


class KubernetesObservation(BaseModel):
    """État du workload Kubernetes au moment de l'alerte."""

    desired_replicas: int | None = None
    ready_replicas: int | None = None
    restart_count: int = 0
    recent_events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Événements Kubernetes pertinents (warning, backoff, etc.)",
    )
    pod_statuses: list[dict[str, Any]] = Field(default_factory=list)


class Observations(BaseModel):
    """Ensemble des observations collectées toutes sources confondues."""

    metrics: MetricsObservation | None = None
    logs: LogsObservation | None = None
    kubernetes: KubernetesObservation | None = None


class SourceStatuses(BaseModel):
    """Statuts de collecte par source — transmis au LLM pour qu'il sache ce qui manque."""

    metrics: SourceStatus = "not_started"
    logs: SourceStatus = "not_started"
    cluster: SourceStatus = "not_started"


class IncidentContext(BaseModel):
    """
    Contexte structuré et borné transmis au LLM pour le diagnostic.

    Ce modèle est le contrat entre la phase de collecte et la phase de diagnostic.
    Il ne doit jamais contenir de données brutes volumineuses ou de secrets.
    """

    incident: IncidentInfo
    observations: Observations
    source_status: SourceStatuses = Field(default_factory=SourceStatuses)
    # Informations manquantes identifiées avant même le diagnostic
    known_missing: list[str] = Field(default_factory=list)

    def to_llm_dict(self) -> dict[str, Any]:
        """
        Sérialise le contexte pour injection dans le prompt LLM.
        Exclut les champs None pour alléger le payload.
        """
        return self.model_dump(exclude_none=True)
