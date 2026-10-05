"""
État LangGraph du workflow de diagnostic d'incident.

L'état est un TypedDict sérialisable — pas d'objets techniques non-JSON.
Référence : ia4ops-scenario1-reference.md section 8.
"""

from typing import Any, Literal, TypedDict

# Statuts possibles pour chaque source de données collectée
SourceStatus = Literal["not_started", "success", "partial", "unavailable", "invalid"]


class IncidentState(TypedDict, total=False):
    """
    État partagé entre tous les nœuds du graphe LangGraph.

    Convention :
    - Les champs *_status indiquent l'état de collecte de la source correspondante.
    - Les champs *_data contiennent les données collectées (dicts JSON-sérialisables).
    - audit_events est une liste append-only — chaque nœud y ajoute ses événements.
    - warnings et errors agrègent les anomalies non bloquantes et bloquantes.
    """

    # --- Identification ---
    incident_id: str
    correlation_id: str  # lié au groupKey Alertmanager
    received_at: str  # ISO 8601

    # --- Alerte brute et normalisée ---
    raw_alert: dict[str, Any]        # payload Alertmanager v4 original (dict)
    normalized_alert: dict[str, Any] # version normalisée extraite du webhook

    # --- Collecte métriques ---
    metrics_status: SourceStatus
    metrics_data: dict[str, Any]

    # --- Collecte logs ---
    logs_status: SourceStatus
    logs_data: list[dict[str, Any]]

    # --- Collecte état cluster ---
    cluster_status: SourceStatus
    cluster_data: dict[str, Any]

    # --- Contexte d'incident (entrée du LLM) ---
    incident_context: dict[str, Any]

    # --- Sortie du diagnostic ---
    diagnosis: dict[str, Any]        # DiagnosticOutput sérialisé
    report: dict[str, Any]           # rapport final

    # --- Métadonnées de qualité ---
    missing_information: list[str]   # sources ou données absentes
    warnings: list[str]              # anomalies non bloquantes
    errors: list[dict[str, Any]]     # erreurs structurées par nœud

    # --- Audit trail (append-only) ---
    audit_events: list[dict[str, Any]]
