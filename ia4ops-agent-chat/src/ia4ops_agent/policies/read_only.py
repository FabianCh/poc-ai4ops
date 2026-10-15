"""
ReadOnlyPolicy — guardrails du scénario 1.

Trois niveaux de protection :
  1. action_executed : invariant dur — toujours False
  2. Verbes d'action dans le texte LLM : détection de phrases indiquant
     qu'une action aurait été exécutée ("I restarted...", "deleted", etc.)
  3. Commandes shell : détection de patterns kubectl, curl, bash, rm, etc.
     dans les champs textuels de la sortie

Ces contrôles s'appliquent APRÈS la validation Pydantic — ils ne remplacent
pas les invariants du modèle de domaine, ils les complètent.

Principe : le code contrôle les contrats et les autorisations,
           le LLM diagnostique seulement.
"""

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Patterns de détection
# ---------------------------------------------------------------------------

# Verbes/phrases indiquant qu'une action a été exécutée par le LLM.
# Priorité aux formes passées et aux formulations à la première personne.
_ACTION_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bi (have |already )?(restarted|deleted|applied|executed|ran|killed|scaled|deployed|patched|modified|rolled back)\b",
        r"\b(restarting|deleting|applying|executing|killing|scaling|deploying|patching)\b",
        r"\baction[_\s]?executed\s*[:=]\s*true\b",
        r"\bi (ran|run) (the |a )?(command|script|kubectl|curl)\b",
        r"\bthe (pod|service|deployment|container) (has been|was) (restarted|deleted|scaled|rolled back)\b",
        r"\bsuccessfully (restarted|deleted|applied|executed|deployed)\b",
        r"\bexecuted?\s+(the\s+)?(remediation|command|action|fix|restart|rollback)\b",
    ]
]

# Patterns de commandes shell interdites dans la sortie LLM.
# Le LLM peut MENTIONNER une commande à titre informatif, mais pas l'avoir exécutée.
# Ce contrôle détecte les formulations qui suggèrent une exécution réelle.
_SHELL_EXEC_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bi (ran|executed|ran the|executed the)\s+`[^`]+`",
        r"\bkubectl\s+(delete|apply|patch|scale|rollout restart|exec)\b.*\bexecuted\b",
        r"\bcurl\s+.*\bexecuted\b",
        r"\brm\s+-rf?\b.*\bexecuted\b",
    ]
]

# Noms de tools qui ne doivent JAMAIS être enregistrés dans le graphe LangGraph.
# Utilisés par l'assertion statique dans check_no_write_tools().
_FORBIDDEN_TOOL_NAMES: frozenset[str] = frozenset({
    "restart_pod", "delete_pod", "scale_deployment", "apply_manifest",
    "exec_command", "run_command", "kubectl_apply", "kubectl_delete",
    "patch_config", "rollout_restart", "write_file", "send_request",
    "create_resource", "modify_resource", "update_config",
})


# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------

@dataclass
class PolicyViolation:
    """Une violation de la read-only policy."""
    rule: str
    detail: str
    severity: str = "error"   # "error" bloque, "warning" est journalisé


@dataclass
class PolicyResult:
    """Résultat complet de l'évaluation de la policy."""
    passed: bool
    violations: list[PolicyViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[PolicyViolation]:
        return [v for v in self.violations if v.severity == "error"]

    def to_audit_summary(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violation_count": len(self.violations),
            "violations": [
                {"rule": v.rule, "detail": v.detail[:200], "severity": v.severity}
                for v in self.violations
            ],
        }


# ---------------------------------------------------------------------------
# Policy principale
# ---------------------------------------------------------------------------

class ReadOnlyPolicy:
    """
    Évalue la sortie du LLM et détecte toute violation du mode lecture seule.

    Usage :
        policy = ReadOnlyPolicy()
        result = policy.check(diagnosis_dict, graph_tools=list(graph.nodes))
        if not result.passed:
            # Rejeter ou marquer la sortie
    """

    def check(
        self,
        diagnosis: dict[str, Any],
        graph_tool_names: list[str] | None = None,
    ) -> PolicyResult:
        """
        Évalue la sortie du LLM sur les trois niveaux de protection.

        Args:
            diagnosis      : dict sérialisé du DiagnosticOutput (ou DiagnosticFailure)
            graph_tool_names : liste des noms de nœuds/tools enregistrés dans le graphe

        Returns:
            PolicyResult avec passed=True si aucune violation bloquante.
        """
        violations: list[PolicyViolation] = []
        policy_warnings: list[str] = []

        # --- Niveau 1 : invariant action_executed ---
        if diagnosis.get("action_executed") is not False:
            violations.append(PolicyViolation(
                rule="action_executed_must_be_false",
                detail=(
                    f"action_executed={diagnosis.get('action_executed')!r} — "
                    "toute valeur autre que False est interdite dans le scénario 1."
                ),
                severity="error",
            ))

        # --- Niveau 2 : verbes d'action dans les champs textuels ---
        text_fields = {
            "summary": diagnosis.get("summary", ""),
        }
        # Parcourir aussi reasoning de primary_hypothesis
        primary = diagnosis.get("primary_hypothesis") or {}
        if isinstance(primary, dict):
            text_fields["primary_hypothesis.reasoning"] = primary.get("reasoning", "")

        # Parcourir remediation_suggestions
        for i, sug in enumerate(diagnosis.get("remediation_suggestions") or []):
            text_fields[f"remediation_suggestions[{i}]"] = str(sug)

        for field_name, text in text_fields.items():
            for pattern in _ACTION_PATTERNS:
                if pattern.search(text):
                    violations.append(PolicyViolation(
                        rule="action_verb_detected",
                        detail=(
                            f"Champ '{field_name}' contient un pattern d'action exécutée "
                            f"(pattern: {pattern.pattern!r}) : «{text[:150]}»"
                        ),
                        severity="error",
                    ))
                    break  # Une violation par champ suffit

            # Shell exec dans les mêmes champs
            for pattern in _SHELL_EXEC_PATTERNS:
                if pattern.search(text):
                    violations.append(PolicyViolation(
                        rule="shell_command_executed",
                        detail=(
                            f"Champ '{field_name}' contient un pattern de commande shell "
                            f"exécutée : «{text[:150]}»"
                        ),
                        severity="error",
                    ))
                    break

        # --- Niveau 3 : outils d'écriture dans le graphe ---
        if graph_tool_names:
            forbidden_found = [
                t for t in graph_tool_names
                if t.lower() in _FORBIDDEN_TOOL_NAMES
            ]
            if forbidden_found:
                violations.append(PolicyViolation(
                    rule="write_tool_registered",
                    detail=(
                        f"Outil(s) d'écriture détecté(s) dans le graphe : {forbidden_found}. "
                        "Aucun outil d'écriture ne doit être enregistré dans le scénario 1."
                    ),
                    severity="error",
                ))

        passed = all(v.severity != "error" for v in violations)
        return PolicyResult(passed=passed, violations=violations, warnings=policy_warnings)

    @staticmethod
    def check_no_write_tools(tool_names: list[str]) -> list[str]:
        """
        Vérifie statiquement qu'aucun outil d'écriture n'est dans la liste.
        Retourne la liste des outils interdits trouvés (vide = OK).
        """
        return [t for t in tool_names if t.lower() in _FORBIDDEN_TOOL_NAMES]
