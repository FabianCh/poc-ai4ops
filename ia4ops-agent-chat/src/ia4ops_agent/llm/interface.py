"""
Interface LLMClient et implémentation FakeLLMClient déterministe.

Le workflow dépend uniquement du Protocol LLMClient — jamais de Gemini directement.
FakeLLMClient retourne des DiagnosticOutput valides codés en dur par cas,
permettant de tester le graphe complet sans appel réseau.

Dispatch par service (cohérent avec les mocks providers) :
  "product-catalog" → cas A (dépendance timeout)
  "checkout"        → cas B (pod instable)
  "frontend"        → cas C (données insuffisantes)
  autre             → réponse générique valide
"""

from typing import Any, Protocol, runtime_checkable

from ia4ops_agent.domain.diagnosis import DiagnosticOutput, Evidence, Hypothesis
from ia4ops_agent.llm.models import LLMCallSummary


@runtime_checkable
class LLMClient(Protocol):
    """
    Interface abstraite pour le client LLM.
    Implémentations : FakeLLMClient (tests), GeminiVertexClient (Task 6).
    """

    async def diagnose(
        self,
        incident_context: dict[str, Any],
    ) -> tuple[DiagnosticOutput, LLMCallSummary]:
        """
        Produit un diagnostic structuré à partir du contexte d'incident.

        Retourne :
          - DiagnosticOutput validé par Pydantic
          - LLMCallSummary pour l'audit trail

        Lève DiagnosisError en cas d'échec persistant.
        """
        ...


class DiagnosisError(Exception):
    """Levée quand le LLM échoue à produire un diagnostic valide après tous les retries."""

    def __init__(self, reason: str, attempts: int = 0) -> None:
        self.reason = reason
        self.attempts = attempts
        super().__init__(f"Diagnostic échoué après {attempts} tentative(s) : {reason}")


# ---------------------------------------------------------------------------
# Réponses pré-construites pour FakeLLMClient
# ---------------------------------------------------------------------------

def _make_case_a_output(incident_id: str) -> DiagnosticOutput:
    """Cas A : dépendance Redis indisponible — timeout répétés."""
    ev1 = Evidence(
        source="metrics",
        reference="metrics.error_rate",
        observation="Taux d'erreur à 18% sur les 15 dernières minutes (seuil : 5%).",
    )
    ev2 = Evidence(
        source="metrics",
        reference="metrics.latency_p95_ms",
        observation="Latence p95 à 4200ms — 4x supérieure à la normale.",
    )
    ev3 = Evidence(
        source="logs",
        reference="logs.pattern.timeout_redis",
        observation="31 occurrences de 'timeout connecting to redis:6379' en 15 min.",
    )
    ev4 = Evidence(
        source="kubernetes",
        reference="cluster.workload_stable",
        observation="Workload stable : 2/2 pods ready, 0 redémarrage.",
    )
    return DiagnosticOutput(
        incident_id=incident_id,
        summary=(
            "Taux d'erreur élevé sur product-catalog causé par des timeouts répétés "
            "vers la dépendance Redis. Le workload Kubernetes est stable, ce qui oriente "
            "vers une défaillance de la dépendance aval plutôt qu'une instabilité applicative."
        ),
        affected_service="product-catalog",
        severity_assessment="critical",
        primary_hypothesis=Hypothesis(
            title="Dépendance Redis indisponible ou dégradée",
            likelihood="high",
            reasoning=(
                "Les logs montrent 31 timeouts vers redis:6379 en 15 minutes. "
                "La latence p95 (4200ms) est cohérente avec des tentatives de reconnexion "
                "répétées. Le workload Kubernetes étant stable, la cause est vraisemblablement "
                "externe au service."
            ),
            evidence_refs=["metrics.error_rate", "metrics.latency_p95_ms", "logs.pattern.timeout_redis"],
        ),
        alternative_hypotheses=[
            Hypothesis(
                title="Saturation du pool de connexions Redis",
                likelihood="medium",
                reasoning="Un pool de connexions saturé peut produire les mêmes symptômes.",
                evidence_refs=["metrics.error_rate", "logs.pattern.timeout_redis"],
            )
        ],
        evidence=[ev1, ev2, ev3, ev4],
        missing_information=["État du service Redis (métriques Redis non disponibles)"],
        recommended_next_checks=[
            "Vérifier la disponibilité de Redis via `redis-cli ping`",
            "Inspecter les métriques Redis : mémoire, connexions actives, latence",
        ],
        remediation_suggestions=[
            "Redémarrer le service Redis si indisponible (non exécuté)",
            "Augmenter le timeout Redis si saturation confirmée (non exécuté)",
        ],
        action_executed=False,
    )


def _make_case_b_output(incident_id: str) -> DiagnosticOutput:
    """Cas B : pod en CrashLoopBackOff suite à OOMKilled."""
    ev1 = Evidence(
        source="metrics",
        reference="metrics.error_rate",
        observation="Taux d'erreur à 31% sur les 15 dernières minutes.",
    )
    ev2 = Evidence(
        source="kubernetes",
        reference="cluster.pod_not_ready",
        observation="1/2 pods ready. Pod checkout-7d4f9b-xk2pq en CrashLoopBackOff, 7 redémarrages.",
    )
    ev3 = Evidence(
        source="logs",
        reference="logs.oom_killed",
        observation="Container terminated with exit code 137 (OOMKilled) — 2 occurrences.",
    )
    ev4 = Evidence(
        source="kubernetes",
        reference="cluster.event_backoff",
        observation="Événement Warning BackOff : 'Back-off restarting failed container'.",
    )
    return DiagnosticOutput(
        incident_id=incident_id,
        summary=(
            "Pod checkout en CrashLoopBackOff suite à des kills OOM répétés. "
            "Le container dépasse sa limite mémoire configurée, ce qui provoque "
            "des redémarrages en boucle et une disponibilité dégradée (1/2 pods)."
        ),
        affected_service="checkout",
        severity_assessment="critical",
        primary_hypothesis=Hypothesis(
            title="Container OOMKilled — limite mémoire dépassée",
            likelihood="high",
            reasoning=(
                "Les logs confirment exit code 137 (OOMKilled) à deux reprises. "
                "L'événement Kubernetes BackOff confirme le CrashLoopBackOff. "
                "Avec memory_ratio à 0.72, le container approche sa limite."
            ),
            evidence_refs=["logs.oom_killed", "cluster.pod_not_ready", "cluster.event_backoff"],
        ),
        alternative_hypotheses=[
            Hypothesis(
                title="Fuite mémoire applicative",
                likelihood="medium",
                reasoning="Une fuite mémoire progressive peut expliquer les OOM répétés.",
                evidence_refs=["metrics.error_rate", "cluster.pod_not_ready"],
            )
        ],
        evidence=[ev1, ev2, ev3, ev4],
        missing_information=["Profil mémoire avant le premier OOM", "Version du container"],
        recommended_next_checks=[
            "Inspecter les métriques mémoire historiques du pod",
            "Vérifier la limite mémoire configurée dans le Deployment",
        ],
        remediation_suggestions=[
            "Augmenter la limite mémoire dans le Deployment (non exécuté)",
            "Analyser le heap dump si disponible (non exécuté)",
        ],
        action_executed=False,
    )


def _make_case_c_output(incident_id: str) -> DiagnosticOutput:
    """Cas C : données insuffisantes — conclusion prudente."""
    ev1 = Evidence(
        source="alert",
        reference="alert.name",
        observation="Alerte OtelDemoServiceHighErrorRate firing sur frontend.",
    )
    ev2 = Evidence(
        source="metrics",
        reference="metrics.error_rate",
        observation="Taux d'erreur à 9% sur les 15 dernières minutes (seuil : 5%).",
    )
    return DiagnosticOutput(
        incident_id=incident_id,
        summary=(
            "Taux d'erreur élevé détecté sur frontend. Diagnostic incomplet : "
            "les logs Loki sont indisponibles et l'état Kubernetes est partiel. "
            "Impossible de déterminer la cause racine avec les données disponibles."
        ),
        affected_service="frontend",
        severity_assessment="unknown",
        primary_hypothesis=Hypothesis(
            title="Cause racine indéterminée — données insuffisantes",
            likelihood="low",
            reasoning=(
                "Seules les métriques sont disponibles (error_rate 9%). "
                "Sans les logs, impossible d'identifier le pattern d'erreur. "
                "Sans l'état Kubernetes complet, impossible d'écarter une instabilité pod."
            ),
            evidence_refs=["metrics.error_rate", "alert.name"],
        ),
        evidence=[ev1, ev2],
        missing_information=[
            "Logs Loki indisponibles (source : unavailable)",
            "État Kubernetes partiel — replicas et pod statuses non récupérés",
        ],
        recommended_next_checks=[
            "Vérifier la disponibilité de Loki et relancer la collecte de logs",
            "Inspecter manuellement les pods frontend : `kubectl get pods -n otel-demo`",
            "Relancer le diagnostic une fois les sources disponibles",
        ],
        remediation_suggestions=[],
        action_executed=False,
    )


def _make_default_output(incident_id: str, service: str) -> DiagnosticOutput:
    """Réponse générique pour les services non mappés."""
    ev = Evidence(
        source="alert",
        reference="alert.name",
        observation=f"Alerte reçue pour le service {service}.",
    )
    return DiagnosticOutput(
        incident_id=incident_id,
        summary=f"Diagnostic générique pour {service} — aucun scénario mock spécifique.",
        affected_service=service,
        severity_assessment="unknown",
        primary_hypothesis=Hypothesis(
            title="Cause indéterminée",
            likelihood="low",
            reasoning="Aucune donnée suffisante pour formuler une hypothèse précise.",
            evidence_refs=["alert.name"],
        ),
        evidence=[ev],
        missing_information=["Données métriques et logs nécessaires"],
        action_executed=False,
    )


# ---------------------------------------------------------------------------
# FakeLLMClient
# ---------------------------------------------------------------------------

class FakeLLMClient:
    """
    Client LLM déterministe pour les tests.
    Retourne un DiagnosticOutput valide pré-construit selon le service affecté.
    Ne fait aucun appel réseau.
    """

    async def diagnose(
        self,
        incident_context: dict[str, Any],
    ) -> tuple[DiagnosticOutput, LLMCallSummary]:
        import time
        start = time.monotonic()

        incident_id = incident_context.get("incident", {}).get("id", "unknown")
        service = incident_context.get("incident", {}).get("service", "unknown")

        dispatch: dict[str, Any] = {
            "product-catalog": _make_case_a_output,
            "checkout": _make_case_b_output,
            "frontend": _make_case_c_output,
        }
        factory = dispatch.get(service, _make_default_output)

        if factory is _make_default_output:
            output = _make_default_output(incident_id, service)
        else:
            output = factory(incident_id)

        duration_ms = int((time.monotonic() - start) * 1000)
        summary = LLMCallSummary(
            model_name="fake-llm-deterministic",
            prompt_version="fake-1.0.0",
            total_attempts=1,
            success=True,
            total_duration_ms=duration_ms,
        )
        return output, summary


# Vérification statique
assert isinstance(FakeLLMClient(), LLMClient)
