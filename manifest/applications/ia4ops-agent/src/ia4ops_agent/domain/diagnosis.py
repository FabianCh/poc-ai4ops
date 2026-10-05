"""
Modèles de domaine pour le diagnostic d'incident.

Ces modèles représentent la sortie structurée attendue du LLM, validée par Pydantic.
Référence : ia4ops-scenario1-reference.md section 12.

Règle fondamentale du scénario 1 : action_executed est TOUJOURS False.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Evidence(BaseModel):
    """
    Une observation concrète utilisée comme preuve dans le diagnostic.
    Doit être traçable jusqu'aux données d'entrée collectées.
    """

    source: Literal["alert", "metrics", "logs", "kubernetes", "changes"]
    reference: str = Field(
        ...,
        description="Identifiant ou clé permettant de retrouver l'observation dans le contexte.",
        min_length=1,
    )
    observation: str = Field(
        ...,
        description="Description factuelle de l'observation.",
        min_length=1,
        max_length=500,
    )


class Hypothesis(BaseModel):
    """
    Une hypothèse de cause racine, appuyée par des preuves référencées.
    """

    title: str = Field(..., min_length=1, max_length=200)
    likelihood: Literal["low", "medium", "high"]
    reasoning: str = Field(
        ...,
        description="Raisonnement explicatif fondé uniquement sur les observations fournies.",
        min_length=1,
        max_length=1000,
    )
    evidence_refs: list[str] = Field(
        ...,
        description="Liste des 'reference' d'Evidence utilisées pour cette hypothèse.",
        min_length=1,
    )


class DiagnosticOutput(BaseModel):
    """
    Sortie structurée complète du diagnostic LLM.

    Invariant scénario 1 : action_executed == False (vérifié par validateur).
    Toutes les hypothèses doivent référencer des preuves présentes dans evidence.
    """

    incident_id: str
    summary: str = Field(..., min_length=1, max_length=500)
    affected_service: str
    severity_assessment: Literal["low", "medium", "high", "critical", "unknown"]
    primary_hypothesis: Hypothesis
    alternative_hypotheses: list[Hypothesis] = Field(default_factory=list)
    evidence: list[Evidence] = Field(..., min_length=1)
    missing_information: list[str] = Field(default_factory=list)
    recommended_next_checks: list[str] = Field(default_factory=list)
    remediation_suggestions: list[str] = Field(default_factory=list)
    # Scénario 1 : doit toujours être False — jamais modifiable par le LLM
    action_executed: bool = False

    @model_validator(mode="after")
    def action_executed_must_be_false(self) -> "DiagnosticOutput":
        """Invariant de sécurité : aucune action ne peut être marquée exécutée."""
        if self.action_executed is not False:
            raise ValueError(
                "action_executed doit être False dans le scénario 1 (read-only)."
            )
        return self

    @model_validator(mode="after")
    def evidence_refs_must_exist(self) -> "DiagnosticOutput":
        """Chaque evidence_ref doit pointer vers une Evidence présente."""
        known_refs = {e.reference for e in self.evidence}
        all_refs = list(self.primary_hypothesis.evidence_refs)
        for h in self.alternative_hypotheses:
            all_refs.extend(h.evidence_refs)

        missing = [r for r in all_refs if r not in known_refs]
        if missing:
            raise ValueError(
                f"evidence_refs inconnues dans les hypothèses : {missing}. "
                f"Références disponibles : {sorted(known_refs)}"
            )
        return self


class DiagnosticFailure(BaseModel):
    """
    Rapport produit en cas d'échec persistant du LLM ou de validation.
    Permet de ne jamais masquer une erreur.
    """

    incident_id: str
    failure_reason: str
    attempts: int = 0
    last_error: str | None = None
    action_executed: bool = False
