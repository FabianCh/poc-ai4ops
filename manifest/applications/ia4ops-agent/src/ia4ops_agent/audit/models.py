"""
Modèles pour l'audit trail du workflow de diagnostic.

Chaque nœud LangGraph produit un AuditEvent. L'ensemble forme une trace
complète et immuable de l'exécution. Référence : section 15 du context pack.

Ne jamais enregistrer : secrets, tokens, credentials, payloads complets sensibles.
Conserver : identifiants de corrélation, nœuds exécutés, statuts, durées, erreurs.
"""

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, model_serializer


class AuditEvent(BaseModel):
    """
    Événement d'audit produit par un nœud du workflow.
    Sérialisable en JSON sans perte pour l'écriture en JSON Lines.
    """

    event_id: str
    incident_id: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC",
    )
    step: str = Field(..., description="Nom du nœud LangGraph ayant produit l'événement.")
    status: str = Field(
        ...,
        description="Résultat de l'étape : success, partial, unavailable, invalid, error.",
    )
    actor: str = "ia4ops-agent"
    # Résumé non-sensible des entrées (pas de valeurs secrètes)
    input_summary: dict[str, Any] = Field(default_factory=dict)
    # Résumé non-sensible des sorties
    output_summary: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None
    error: str | None = None

    def to_json_line(self) -> str:
        """Sérialise l'événement en une ligne JSON (pour JSON Lines)."""
        return json.dumps(self.model_dump(), ensure_ascii=False)

    @classmethod
    def make_id(cls, incident_id: str, step: str, index: int) -> str:
        """Génère un event_id lisible et unique dans le contexte d'un incident."""
        return f"evt-{incident_id}-{step}-{index:03d}"
