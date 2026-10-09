"""
Nœud validate — contrôles déterministes post-LLM.

Applique les 10 contrôles du context pack (section 14) :
1.  Validation Pydantic complète
2.  action_executed == False (via ReadOnlyPolicy)
3.  evidence_refs existent dans evidence (via Pydantic)
4.  Pas de verbes d'action dans les champs textuels (via ReadOnlyPolicy)
5.  Pas de commandes shell exécutées dans la sortie (via ReadOnlyPolicy)
6.  Service diagnostiqué == service de l'alerte
7.  Sources unavailable ajoutées à missing_information
8.  Limite de taille sur les champs texte
9.  Journalisation des erreurs de parsing et violations dans l'audit trail
10. Pas plus de MAX_RETRIES tentatives (contrôlé dans diagnose)
"""

import time
from typing import Any

from pydantic import ValidationError

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.domain.diagnosis import DiagnosticOutput
from ia4ops_agent.graph.state import IncidentState
from ia4ops_agent.policies.read_only import ReadOnlyPolicy

_MAX_FIELD_LENGTH = 1000
_policy = ReadOnlyPolicy()


def _check_field_lengths(diag: dict[str, Any]) -> list[str]:
    violations = []
    for field_name in ("summary",):
        val = diag.get(field_name, "")
        if isinstance(val, str) and len(val) > _MAX_FIELD_LENGTH:
            violations.append(
                f"Champ '{field_name}' dépasse {_MAX_FIELD_LENGTH} caractères "
                f"({len(val)} chars)."
            )
    return violations


async def validate_node(state: IncidentState) -> dict[str, Any]:
    start = time.monotonic()
    incident_id = state["incident_id"]
    diagnosis = state.get("diagnosis", {})
    normalized = state.get("normalized_alert", {})
    audit_events = list(state.get("audit_events", []))
    warnings = list(state.get("warnings", []))
    errors = list(state.get("errors", []))
    missing = list(state.get("missing_information", []))

    validation_errors: list[str] = []

    # Contrôles 1, 2, 3 : validation Pydantic complète
    # (inclut action_executed=False et cohérence evidence_refs)
    is_failure = "failure_reason" in diagnosis
    if not is_failure:
        try:
            DiagnosticOutput(**diagnosis)
        except ValidationError as exc:
            for error in exc.errors():
                validation_errors.append(
                    f"Validation Pydantic : {error['msg']} ({error['loc']})"
                )
        except Exception as exc:  # noqa: BLE001
            validation_errors.append(f"Parsing inattendu : {exc}")

    # Contrôles 2, 4, 5 : ReadOnlyPolicy
    # (action_executed, verbes d'action, commandes shell)
    policy_result = _policy.check(diagnosis)
    if not policy_result.passed:
        for violation in policy_result.errors:
            validation_errors.append(
                f"[{violation.rule}] {violation.detail}"
            )
    # Avertissements non bloquants de la policy
    for w in policy_result.warnings:
        warnings.append(w)

    # Contrôle 6 : service diagnostiqué == service de l'alerte
    alerted_service = normalized.get("service", "")
    diagnosed_service = diagnosis.get("affected_service", "")
    if alerted_service and diagnosed_service and diagnosed_service != alerted_service:
        warnings.append(
            f"Service diagnostiqué '{diagnosed_service}' "
            f"≠ service alerté '{alerted_service}'."
        )

    # Contrôle 7 : sources unavailable → missing_information
    for src in ("metrics", "logs", "traces", "cluster"):
        sts = state.get(f"{src}_status", "not_started")
        if sts in ("unavailable", "invalid"):
            marker = f"Source {src} : {sts}"
            if marker not in " ".join(missing):
                missing.append(marker)

    # Contrôle 8 : taille des champs texte
    validation_errors.extend(_check_field_lengths(diagnosis))

    # Contrôle 9 : journaliser violations dans errors
    if validation_errors:
        errors.append({
            "step": "validate",
            "errors": validation_errors,
            "policy_violations": policy_result.to_audit_summary(),
        })

    status = "error" if validation_errors else "success"
    duration_ms = int((time.monotonic() - start) * 1000)
    event = AuditEvent(
        event_id=AuditEvent.make_id(incident_id, "validate", len(audit_events)),
        incident_id=incident_id,
        step="validate",
        status=status,
        input_summary={
            "diagnosis_keys": list(diagnosis.keys()),
            "is_failure": is_failure,
        },
        output_summary={
            "validation_errors_count": len(validation_errors),
            "warnings_count": len(warnings),
            "policy_passed": policy_result.passed,
        },
        duration_ms=duration_ms,
        error="; ".join(validation_errors[:3]) if validation_errors else None,
    )
    audit_events.append(event.model_dump())

    return {
        "diagnosis": diagnosis,
        "audit_events": audit_events,
        "warnings": warnings,
        "errors": errors,
        "missing_information": missing,
    }
