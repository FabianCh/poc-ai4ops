"""
Tests unitaires — ReadOnlyPolicy (Task 7).

Couvre :
- action_executed != False → violation
- Verbes d'action dans summary → violation
- Verbes d'action dans primary_hypothesis.reasoning → violation
- Commandes shell exécutées → violation
- Sortie LLM saine → passed
- Outils d'écriture dans le graphe → violation
- check_no_write_tools() static method
- DiagnosticFailure (pas de Pydantic) → policy quand même appliquée
"""

import pytest

from ia4ops_agent.policies.read_only import PolicyViolation, ReadOnlyPolicy


@pytest.fixture
def policy() -> ReadOnlyPolicy:
    return ReadOnlyPolicy()


# ---------------------------------------------------------------------------
# Helpers : diagnostics de test
# ---------------------------------------------------------------------------

def _valid_diagnosis(incident_id: str = "test-001") -> dict:
    """Diagnostic minimal valide — doit passer toutes les vérifications."""
    return {
        "incident_id": incident_id,
        "summary": "Taux d'erreur élevé sur product-catalog dû à des timeouts Redis.",
        "affected_service": "product-catalog",
        "severity_assessment": "critical",
        "primary_hypothesis": {
            "title": "Redis indisponible",
            "likelihood": "high",
            "reasoning": "Les logs montrent des timeouts vers redis:6379.",
            "evidence_refs": ["metrics.error_rate"],
        },
        "alternative_hypotheses": [],
        "evidence": [
            {
                "source": "metrics",
                "reference": "metrics.error_rate",
                "observation": "Taux d'erreur à 18%.",
            }
        ],
        "missing_information": [],
        "recommended_next_checks": ["Vérifier la disponibilité de Redis."],
        "remediation_suggestions": ["Redémarrer Redis si indisponible (non exécuté)."],
        "action_executed": False,
    }


# ---------------------------------------------------------------------------
# Contrôle 1 : action_executed
# ---------------------------------------------------------------------------


def test_action_executed_false_passes(policy: ReadOnlyPolicy) -> None:
    result = policy.check(_valid_diagnosis())
    assert result.passed
    assert not result.errors


def test_action_executed_true_violates(policy: ReadOnlyPolicy) -> None:
    diag = _valid_diagnosis()
    diag["action_executed"] = True
    result = policy.check(diag)
    assert not result.passed
    rules = [v.rule for v in result.errors]
    assert "action_executed_must_be_false" in rules


def test_action_executed_none_violates(policy: ReadOnlyPolicy) -> None:
    diag = _valid_diagnosis()
    diag["action_executed"] = None
    result = policy.check(diag)
    assert not result.passed


# ---------------------------------------------------------------------------
# Contrôle 2 : verbes d'action dans le texte
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_summary", [
    "I have restarted the product-catalog deployment.",
    "I deleted the failing pod to resolve the issue.",
    "I executed the remediation script successfully.",
    "I ran the kubectl rollout restart command.",
    "The pod has been restarted successfully.",
    "Successfully restarted the service.",
    "I already applied the patch.",
])
def test_action_verb_in_summary_violates(policy: ReadOnlyPolicy, bad_summary: str) -> None:
    diag = _valid_diagnosis()
    diag["summary"] = bad_summary
    result = policy.check(diag)
    assert not result.passed, f"Devrait détecter une violation dans : {bad_summary!r}"
    rules = [v.rule for v in result.errors]
    assert "action_verb_detected" in rules


def test_action_verb_in_reasoning_violates(policy: ReadOnlyPolicy) -> None:
    diag = _valid_diagnosis()
    diag["primary_hypothesis"]["reasoning"] = (
        "I have restarted the Redis service to resolve the connectivity issue."
    )
    result = policy.check(diag)
    assert not result.passed
    rules = [v.rule for v in result.errors]
    assert "action_verb_detected" in rules


def test_mention_without_execution_passes(policy: ReadOnlyPolicy) -> None:
    """Mentionner une commande comme recommandation (non exécutée) doit passer."""
    diag = _valid_diagnosis()
    diag["recommended_next_checks"] = [
        "Vérifier Redis avec : redis-cli ping",
        "Inspecter les pods : kubectl get pods -n otel-demo",
    ]
    diag["remediation_suggestions"] = [
        "Redémarrer Redis si indisponible (non exécuté).",
        "Augmenter la limite mémoire dans le Deployment (non exécuté).",
    ]
    result = policy.check(diag)
    assert result.passed, f"Violations inattendues : {result.violations}"


# ---------------------------------------------------------------------------
# Contrôle 3 : outils d'écriture dans le graphe
# ---------------------------------------------------------------------------


def test_no_write_tools_passes(policy: ReadOnlyPolicy) -> None:
    result = policy.check(
        _valid_diagnosis(),
        graph_tool_names=["initialize", "collect_metrics", "collect_logs", "diagnose"],
    )
    assert result.passed


def test_write_tool_in_graph_violates(policy: ReadOnlyPolicy) -> None:
    result = policy.check(
        _valid_diagnosis(),
        graph_tool_names=["initialize", "collect_metrics", "restart_pod"],
    )
    assert not result.passed
    rules = [v.rule for v in result.errors]
    assert "write_tool_registered" in rules


def test_multiple_write_tools_single_violation(policy: ReadOnlyPolicy) -> None:
    result = policy.check(
        _valid_diagnosis(),
        graph_tool_names=["restart_pod", "delete_pod", "scale_deployment"],
    )
    rules = [v.rule for v in result.errors]
    # Une violation couvre tous les outils interdits
    assert rules.count("write_tool_registered") == 1


# ---------------------------------------------------------------------------
# check_no_write_tools static
# ---------------------------------------------------------------------------


def test_check_no_write_tools_clean() -> None:
    found = ReadOnlyPolicy.check_no_write_tools(
        ["initialize", "collect_metrics", "build_context", "diagnose", "finalize"]
    )
    assert found == []


def test_check_no_write_tools_finds_forbidden() -> None:
    found = ReadOnlyPolicy.check_no_write_tools(["collect_metrics", "kubectl_apply"])
    assert "kubectl_apply" in found


# ---------------------------------------------------------------------------
# Cas sain complet
# ---------------------------------------------------------------------------


def test_valid_diagnosis_passes_all_checks(policy: ReadOnlyPolicy) -> None:
    result = policy.check(
        _valid_diagnosis(),
        graph_tool_names=["initialize", "collect_metrics", "collect_traces", "collect_logs",
                          "collect_cluster", "build_context", "diagnose",
                          "validate", "finalize"],
    )
    assert result.passed
    assert result.violations == []
    assert result.to_audit_summary()["passed"] is True


# ---------------------------------------------------------------------------
# DiagnosticFailure (pas de validation Pydantic — policy quand même)
# ---------------------------------------------------------------------------


def test_diagnostic_failure_with_action_executed_true_violates(policy: ReadOnlyPolicy) -> None:
    failure = {
        "incident_id": "test-001",
        "failure_reason": "LLM timeout",
        "attempts": 3,
        "action_executed": True,  # ne doit jamais être True
    }
    result = policy.check(failure)
    assert not result.passed
    rules = [v.rule for v in result.errors]
    assert "action_executed_must_be_false" in rules


def test_diagnostic_failure_clean_passes(policy: ReadOnlyPolicy) -> None:
    failure = {
        "incident_id": "test-001",
        "failure_reason": "LLM timeout",
        "attempts": 3,
        "action_executed": False,
    }
    result = policy.check(failure)
    assert result.passed


# ---------------------------------------------------------------------------
# PolicyResult helpers
# ---------------------------------------------------------------------------


def test_policy_result_audit_summary_structure(policy: ReadOnlyPolicy) -> None:
    diag = _valid_diagnosis()
    diag["action_executed"] = True
    result = policy.check(diag)
    summary = result.to_audit_summary()
    assert "passed" in summary
    assert "violation_count" in summary
    assert "violations" in summary
    assert isinstance(summary["violations"], list)
