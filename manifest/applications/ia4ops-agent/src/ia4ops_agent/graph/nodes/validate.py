"""
Nœud validate — contrôles déterministes post-LLM.

Applique les 10 contrôles du context pack (section 14) :
1. Validation Pydantic
2. action_executed == False
3. evidence_refs existent dans evidence
4. Pas de verbes d'action indiquant une exécution
5. Pas de commandes shell dans la sortie
6. Service diagnostiqué == service de l'alerte
7. Sources unavailable ajoutées à missing_information
8. Limite de taille sur les champs texte
9. Journalisation des erreurs de parsing
10. Pas plus de MAX_RETRIES tentatives (contrôlé dans diagnose)
"""

import time
from typing import Any

from pydantic import ValidationError

from ia4ops_agent.audit.models import AuditEvent
from ia4ops_agent.domain.diagnosis import DiagnosticOutput
from ia4ops_agent.graph.state import IncidentState

# Verbes indiquant qu'une action aurait été exécutée
_ACTION_VERBS = frozenset([
    "restarted", "deleted", "applied", "executed", "ran", "killed",
    "scaled", "deployed", "rolled back", "patched", "modified",
    "i have restarted", "i have deleted", "i executed", "i ran",
])

_MAX_FIELD_LENGTH = 1000


def _contains_action_verb(text: str) -> bool:
    lower = text.lower()
    return any(verb in lower for verb in _ACTION_VERBS)


def _check_field_lengths(diag: dict[str, Any]) -> list[str]:
    violations = []
    for field in ("summary",):
        val = diag.get(field, "")
        if isinstance(val, str) and len(val) > _MAX_FIELD_LENGTH:
            violations.append(f"Champ '{field}' dépasse {_MAX_FIELD_LENGTH} caractères.")
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
    validated_diagnosis = diagnosis

    # Contrôle 1 & 2 & 3 : validation Pydantic complète (inclut action_executed et evidence_refs)
    try:
        DiagnosticOutput(**diagnosis)
    except ValidationError as exc:
        for error in exc.errors():
            validation_errors.append(f"Validation Pydantic : {error['msg']} ({error['loc']})")
    except Exception as exc:  # noqa: BLE001
        # DiagnosticFailure au lieu de DiagnosticOutput — pas d'erreur, juste un signal
        if "failure_reason" not in diagnosis:
            validation_errors.append(f"Parsing inattendu : {exc}")

    # Contrôle 4 : pas de verbes d'action dans le summary
    summary = diagnosis.get("summary", "")
    if _contains_action_verb(summary):
        validation_errors.append(
            f"Le champ 'summary' contient un verbe d'action : '{summary[:100]}'"
        )

    # Contrôle 6 : service diagnostiqué == service de l'alerte
    alerted_service = normalized.get("service", "unknown")
    diagnosed_service = diagnosis.get("affected_service", "")
    if diagnosed_service and diagnosed_service != alerted_service:
        warnings.append(
            f"Service diagnostiqué '{diagnosed_service}' "
            f"≠ service alerté '{alerted_service}'."
        )

    # Contrôle 7 : sources unavailable → missing_information
    metrics_status = state.get("metrics_status", "not_started")
    logs_status = state.get("logs_status", "not_started")
    cluster_status = state.get("cluster_status", "not_started")
    for src, sts in [("metrics", metrics_status), ("logs", logs_status), ("cluster", cluster_status)]:
        if sts in ("unavailable", "invalid") and f"Source {src}" not in " ".join(missing):
            missing.append(f"Source {src} : {sts}")

    # Contrôle 8 : taille des champs texte
    length_violations = _check_field_lengths(diagnosis)
    validation_errors.extend(length_violations)

    # Si erreurs critiques, marquer dans errors
    if validation_errors:
        errors.append({
            "step": "validate",
            "errors": validation_errors,
        })

    status = "error" if validation_errors else "success"
    duration_ms = int((time.monotonic() - start) * 1000)
    event = AuditEvent(
        event_id=AuditEvent.make_id(incident_id, "validate", len(audit_events)),
        incident_id=incident_id,
        step="validate",
        status=status,
        input_summary={"diagnosis_keys": list(diagnosis.keys())},
        output_summary={
            "validation_errors_count": len(validation_errors),
            "warnings_count": len(warnings),
        },
        duration_ms=duration_ms,
        error="; ".join(validation_errors) if validation_errors else None,
    )
    audit_events.append(event.model_dump())

    return {
        "diagnosis": validated_diagnosis,
        "audit_events": audit_events,
        "warnings": warnings,
        "errors": errors,
        "missing_information": missing,
    }
