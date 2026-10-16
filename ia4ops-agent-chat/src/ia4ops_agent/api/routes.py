"""
Routes FastAPI de l'agent IA4Ops.

Architecture asynchrone :
  POST /webhooks/alertmanager
    → valide le payload v4
    → déduplique par make_dedup_key()
    → retourne 200 immédiatement (Alertmanager ne réessaie pas)
    → enregistre l'alerte en attente d'approbation

  POST /api/v1/investigations
    → valide une demande opérateur bornée
    → lance le même graphe avec la période et la question demandées

  GET /api/v1/alerts/pending
    → retourne les alertes qui attendent une décision humaine

  POST /api/v1/alerts/{incident_id}/decision
    → démarre le graphe après approbation ou clôture l'alerte comme ignorée

  GET /api/v1/incidents/{incident_id}
    → consulte le store en mémoire
    → retourne le rapport quand disponible, "pending" sinon

  GET /health
    → liveness probe Kubernetes

Le graphe compilé et le store incidents sont injectés via le state applicatif
(app.state), initialisés dans le lifespan de main.py.
"""

import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ia4ops_agent.api.models import (
    AlertAccepted,
    AlertDecisionRequest,
    AlertDecisionResponse,
    AlertDuplicate,
    AlertPending,
    AlertResolved,
    AlertWebhookRequest,
    IncidentResponse,
    InvestigationAccepted,
    InvestigationInterpretation,
    InvestigationInterpretationRequest,
    InvestigationRequest,
    PendingAlert,
)
from ia4ops_agent.audit.trace_logging import emit_trace_event
from ia4ops_agent.integrations.keep import KeepAPIError
from ia4ops_agent.integrations.keep_publisher import KeepPublisher
from ia4ops_agent.llm.request_interpreter import RequestInterpretationError

logger = logging.getLogger(__name__)

router = APIRouter()

_GRAPH_PROGRESS = {
    "initialize": ("Préparation de l'investigation", "collect_metrics"),
    "collect_metrics": ("Collecte des métriques", "collect_traces"),
    "collect_traces": ("Collecte des traces", "collect_logs"),
    "collect_logs": ("Collecte des logs", "collect_cluster"),
    "collect_cluster": ("Vérification de l'état du cluster", "build_context"),
    "build_context": ("Synthèse des observations", "diagnose"),
    "diagnose": ("Analyse du diagnostic", "validate"),
    "validate": ("Validation des preuves et garde-fous", "finalize"),
    "finalize": ("Finalisation du rapport", None),
    "end_watchdog": ("Fin du traitement", None),
}
_GRAPH_PROGRESS_LABELS = {node: label for node, (label, _) in _GRAPH_PROGRESS.items()}


def _record_graph_progress(store: dict, incident_id: str, completed_node: str) -> None:
    """Record completed graph steps and expose the next actual step to API clients."""
    progress = _GRAPH_PROGRESS.get(completed_node)
    entry = store.get(incident_id)
    if progress is None or entry is None:
        return

    completed_label, next_node = progress
    completed_steps = list(entry.get("completed_steps", []))
    if completed_label not in completed_steps:
        completed_steps.append(completed_label)
    entry["completed_steps"] = completed_steps
    entry["progress"] = (
        _GRAPH_PROGRESS_LABELS[next_node] if next_node is not None else completed_label
    )


@router.post(
    "/api/v1/investigations/interpret",
    response_model=InvestigationInterpretation,
    summary="Interpréter une demande sans démarrer d'investigation",
    tags=["incidents"],
)
async def interpret_investigation_request(
    payload: InvestigationInterpretationRequest,
    request: Request,
) -> InvestigationInterpretation:
    """Extract bounded parameters; the operator must confirm separately."""
    interpreter = getattr(request.app.state, "request_interpreter", None)
    if interpreter is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "L'interpréteur de langage naturel est désactivé. "
                "Configurez REQUEST_INTERPRETER_PROVIDER=gemini."
            ),
        )
    try:
        return await interpreter.interpret(payload.message, payload.previous_message)
    except RequestInterpretationError as exc:
        logger.warning("Impossible d'interpréter la demande opérateur: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# POST /webhooks/alertmanager — point d'entrée Alertmanager
# ---------------------------------------------------------------------------


@router.post(
    "/webhooks/alertmanager",
    response_model=AlertAccepted | AlertPending | AlertDuplicate | AlertResolved,
    summary="Réception d'une notification Alertmanager v4",
    description=(
        "Accepte un payload Alertmanager v4, le déduplique et attend une décision ops avant "
        "de lancer le diagnostic. Retourne 200 immédiatement."
    ),
    tags=["webhook"],
)
async def receive_alertmanager_webhook(
    payload: AlertWebhookRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> AlertAccepted | AlertPending | AlertDuplicate | AlertResolved:
    """
    Point d'entrée principal des alertes Alertmanager.

    Alertmanager exige un 2xx rapide. Le webhook ne lance jamais le graphe :
    une action explicite d'un opérateur est requise.
    """
    app_state = request.app.state

    # --- Watchdog : ignorer silencieusement ---
    if payload.is_watchdog():
        emit_trace_event(
            "webhook_ignored",
            "watchdog",
            reason="watchdog",
            alert_names=[alert.labels.alertname for alert in payload.alerts],
        )
        logger.debug("Alerte Watchdog reçue — ignorée.")
        return AlertAccepted(
            incident_id="watchdog",
            status="accepted",
            message="Alerte Watchdog ignorée.",
        )

    # --- Déduplication ---
    dedup_key = payload.make_dedup_key()
    if payload.status == "resolved":
        incident_id = app_state.dedup_cache.get(dedup_key)
        entry = app_state.incident_store.get(incident_id) if incident_id else None
        if entry is None:
            emit_trace_event(
                "webhook_resolution_unmatched",
                "unmatched",
                fingerprints=[alert.fingerprint for alert in payload.alerts],
                dedup_key=dedup_key,
            )
            logger.warning(
                "Résolution reçue sans incident firing correspondant. dedup_key=%s",
                dedup_key,
            )
            return AlertResolved(
                incident_id=None,
                status="resolved_unmatched",
                message="Résolution reçue sans incident actif correspondant.",
            )

        resolved_at = max(
            (alert.endsAt for alert in payload.alerts if alert.is_resolved),
            default=None,
        )
        entry["alert_status"] = "resolved"
        entry["resolved_at"] = resolved_at.isoformat() if resolved_at else None
        if entry.get("status") == "awaiting_approval":
            entry["status"] = "resolved"
            entry["approval_status"] = "resolved"
        emit_trace_event(
            "webhook_resolved",
            incident_id,
            fingerprints=[alert.fingerprint for alert in payload.alerts],
            resolved_at=entry["resolved_at"],
        )
        logger.info("Incident résolu par Alertmanager. incident_id=%s", incident_id)
        keep_publisher = getattr(app_state, "keep_publisher", None)
        if keep_publisher is not None:
            background_tasks.add_task(
                _publish_keep_resolution,
                publisher=keep_publisher,
                incident_id=incident_id,
                dedup_key=dedup_key,
                fingerprints=[alert.fingerprint for alert in payload.alerts],
                resolved_at=entry["resolved_at"],
            )
        return AlertResolved(
            incident_id=incident_id,
            status="resolved",
            message="Résolution associée à l'incident existant.",
        )

    if dedup_key in app_state.dedup_cache:
        incident_id = app_state.dedup_cache[dedup_key]
        emit_trace_event(
            "webhook_duplicate",
            incident_id,
            alert_status=payload.status,
            fingerprints=[alert.fingerprint for alert in payload.alerts],
            dedup_key=dedup_key,
        )
        logger.info(
            "Notification dupliquée ignorée. incident_id=%s dedup_key=%s",
            incident_id,
            dedup_key,
        )
        return AlertDuplicate(incident_id=incident_id)

    # --- Réserver l'entrée en attente sans lancer le graphe ---
    incident_id = f"inc-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"

    received_at = datetime.now(UTC).isoformat()
    app_state.dedup_cache[dedup_key] = incident_id

    emit_trace_event(
        "webhook_received",
        incident_id,
        alert_status=payload.status,
        alert_count=len(payload.alerts),
        alert_names=[alert.labels.alertname for alert in payload.alerts],
        fingerprints=[alert.fingerprint for alert in payload.alerts],
        services=payload.affected_services(),
        namespaces=sorted({alert.labels.namespace for alert in payload.alerts}),
        starts_at=[alert.startsAt.isoformat() for alert in payload.alerts],
        group_key=payload.groupKey,
    )

    # Evict oldest entries si le cache est plein
    if len(app_state.dedup_cache) > app_state.dedup_cache_max_size:
        oldest_key = next(iter(app_state.dedup_cache))
        app_state.dedup_cache.pop(oldest_key, None)

    # Initialiser l'entrée "pending" dans le store
    app_state.incident_store[incident_id] = {
        "incident_id": incident_id,
        "status": "awaiting_approval",
        "approval_status": "awaiting_approval",
        "alert_status": payload.status,
        "dedup_key": dedup_key,
        "resolved_at": None,
        "received_at": received_at,
        "report": None,
        "failure": None,
        "payload": payload.model_dump(mode="json"),
    }

    logger.info(
        "Webhook accepté. incident_id=%s service(s)=%s",
        incident_id,
        payload.affected_services(),
    )

    return AlertPending(incident_id=incident_id)


@router.get(
    "/api/v1/alerts/pending",
    response_model=list[PendingAlert],
    summary="Lister les alertes en attente de décision ops",
    tags=["alerts"],
)
async def get_pending_alerts(request: Request) -> list[PendingAlert]:
    """Retourne des résumés bornés des alertes firing non encore décidées."""
    pending: list[PendingAlert] = []
    for entry in request.app.state.incident_store.values():
        if entry.get("status") != "awaiting_approval":
            continue
        webhook = AlertWebhookRequest.model_validate(entry["payload"])
        primary = webhook.primary_alert()
        service = webhook.affected_services()[0] if webhook.affected_services() else "unknown"
        pending.append(
            PendingAlert(
                incident_id=entry["incident_id"],
                alert_name=primary.labels.alertname,
                service=service,
                affected_services=webhook.affected_services(),
                namespace=primary.labels.namespace or "unknown",
                severity=primary.labels.severity or "unknown",
                summary=primary.annotations.summary,
                description=primary.annotations.description,
                starts_at=primary.startsAt,
                received_at=entry["received_at"],
                alerts_count=len(webhook.alerts),
            )
        )
    return sorted(pending, key=lambda item: item.starts_at)


@router.post(
    "/api/v1/alerts/{incident_id}/decision",
    response_model=AlertDecisionResponse,
    summary="Décider du traitement d'une alerte",
    tags=["alerts"],
)
async def decide_alert(
    incident_id: str,
    payload: AlertDecisionRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> AlertDecisionResponse:
    """N'exécute le graphe que pour une alerte explicitement approuvée."""
    store = request.app.state.incident_store
    entry = store.get(incident_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Alerte '{incident_id}' introuvable.")
    if entry.get("status") != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Alerte non disponible pour décision (état: {entry.get('status')}).",
        )

    entry["approval_status"] = payload.action
    if payload.action == "ignore":
        entry["status"] = "ignored"
        emit_trace_event("alert_ignored", incident_id)
        return AlertDecisionResponse(
            incident_id=incident_id,
            status="ignored",
            message="Alerte ignorée ; aucun diagnostic n'a été lancé.",
        )

    entry["status"] = "pending"
    webhook = AlertWebhookRequest.model_validate(entry["payload"])
    primary = webhook.primary_alert()
    emit_trace_event(
        "alert_investigation_approved",
        incident_id,
        service=webhook.affected_services()[0] if webhook.affected_services() else "unknown",
        alert_name=primary.labels.alertname,
        window_minutes=payload.window_minutes,
    )
    background_tasks.add_task(
        _run_graph,
        app_state=request.app.state,
        incident_id=incident_id,
        payload_dict=entry["payload"],
        window_minutes=payload.window_minutes,
        investigation_question=f"Analyser les signaux liés à l'alerte {primary.labels.alertname}.",
    )
    return AlertDecisionResponse(
        incident_id=incident_id,
        status="pending",
        message="Investigation approuvée ; le diagnostic démarre.",
    )


@router.post(
    "/api/v1/investigations",
    response_model=InvestigationAccepted,
    status_code=202,
    summary="Démarrer une investigation demandée par un opérateur",
    tags=["incidents"],
)
async def start_investigation(
    payload: InvestigationRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> InvestigationAccepted:
    """Construit une alerte interne validée puis réutilise le graphe existant."""
    app_state = request.app.state
    incident_id = (
        f"inc-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    )
    now = datetime.now(UTC)
    labels = {
        "alertname": "ManualInvestigation",
        "namespace": "otel-demo",
        "severity": "info",
        "service_name": payload.service,
    }
    webhook = AlertWebhookRequest(
        version="4",
        groupKey=f"manual:{incident_id}",
        status="firing",
        receiver="ia4ops-agent-chat",
        groupLabels={"namespace": "otel-demo", "alertname": "ManualInvestigation"},
        commonLabels=labels,
        commonAnnotations={},
        alerts=[
            {
                "status": "firing",
                "labels": labels,
                "annotations": {
                    "summary": f"Investigation manuelle de {payload.service}",
                    "description": "Investigation déclenchée depuis le chatbot.",
                },
                "startsAt": now.isoformat(),
                "endsAt": "0001-01-01T00:00:00Z",
                "fingerprint": uuid4().hex,
            }
        ],
    )
    payload_dict = webhook.model_dump(mode="json")
    received_at = now.isoformat()
    app_state.incident_store[incident_id] = {
        "incident_id": incident_id,
        "status": "pending",
        "alert_status": "firing",
        "dedup_key": None,
        "resolved_at": None,
        "received_at": received_at,
        "report": None,
        "failure": None,
    }

    emit_trace_event(
        "manual_investigation_requested",
        incident_id,
        service=payload.service,
        namespace="otel-demo",
        window_minutes=payload.window_minutes,
    )
    background_tasks.add_task(
        _run_graph,
        app_state=app_state,
        incident_id=incident_id,
        payload_dict=payload_dict,
        window_minutes=payload.window_minutes,
        investigation_question=payload.question,
        publish_keep=False,
    )
    return InvestigationAccepted(incident_id=incident_id)


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id} — consultation du résultat
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/incidents/{incident_id}",
    response_model=IncidentResponse,
    summary="Consulter le résultat d'un incident diagnostiqué",
    tags=["incidents"],
)
async def get_incident(incident_id: str, request: Request) -> IncidentResponse:
    """
    Retourne le rapport de diagnostic pour un incident donné.

    Statuts possibles :
    - "pending"  : le graphe n'a pas encore démarré
    - "running"  : le graphe est en cours d'exécution
    - "completed" / "completed_with_errors" : rapport disponible dans `report`
    - "failed"   : erreur irrécupérable, détail dans `failure`
    """
    store = request.app.state.incident_store
    entry = store.get(incident_id)

    if entry is None:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' introuvable.")

    return IncidentResponse(**entry)


# ---------------------------------------------------------------------------
# GET /health — liveness probe
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    summary="Liveness probe",
    tags=["ops"],
)
async def health() -> dict:
    """Retourne 200 si l'application est vivante."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Tâche de fond : exécution du graphe LangGraph
# ---------------------------------------------------------------------------


async def _run_graph(
    app_state,
    incident_id: str,
    payload_dict: dict,
    window_minutes: int = 15,
    investigation_question: str | None = None,
    publish_keep: bool = True,
) -> None:
    """
    Exécute le graphe LangGraph en arrière-plan.

    Met à jour le store incidents à chaque transition significative :
    pending → running → completed | failed
    """
    store = app_state.incident_store

    # Marquer comme "running"
    if incident_id in store:
        store[incident_id]["status"] = "running"
        store[incident_id]["progress"] = _GRAPH_PROGRESS_LABELS["initialize"]
        store[incident_id]["completed_steps"] = []

    try:
        graph = app_state.graph
        initial_state = {
            "raw_alert": payload_dict,
            "incident_id": incident_id,  # hint pour le nœud initialize
            "window_minutes": window_minutes,
        }
        if investigation_question is not None:
            initial_state["investigation_question"] = investigation_question

        logger.debug("Démarrage du graphe pour incident_id=%s", incident_id)
        final_state = initial_state.copy()
        async for updates in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_update in updates.items():
                if isinstance(node_update, dict):
                    final_state.update(node_update)
                _record_graph_progress(store, incident_id, node_name)

        report = final_state.get("report", {})
        # Récupérer l'incident_id définitif généré par le nœud initialize
        # (il peut différer du pré-enregistré si le graphe en génère un nouveau)
        final_incident_id = final_state.get("incident_id", incident_id)

        status = report.get("status", "completed")
        finalized_at = report.get("finalized_at")

        entry = {
            "incident_id": final_incident_id,
            "status": status,
            "received_at": store.get(incident_id, {}).get("received_at"),
            "alert_status": store.get(incident_id, {}).get("alert_status"),
            "dedup_key": store.get(incident_id, {}).get("dedup_key"),
            "resolved_at": store.get(incident_id, {}).get("resolved_at"),
            "finalized_at": finalized_at,
            "report": report,
            "failure": None,
            "progress": "Rapport prêt",
            "completed_steps": store.get(incident_id, {}).get("completed_steps", []),
        }

        # Si l'incident_id a changé, migrer l'entrée dans le store
        if final_incident_id != incident_id:
            store[final_incident_id] = entry
            # Conserver l'ancienne clé pour les lookups en transit
            store[incident_id] = {**entry, "incident_id": final_incident_id}
        else:
            store[incident_id] = entry

        logger.info(
            "Graphe terminé. incident_id=%s status=%s",
            final_incident_id,
            status,
        )
        emit_trace_event(
            "incident_completed",
            final_incident_id,
            status=status,
            source_status=report.get("source_status", {}),
            action_executed=report.get("action_executed", False),
        )
        keep_publisher = getattr(app_state, "keep_publisher", None)
        if (
            publish_keep
            and keep_publisher is not None
            and status in {"completed", "completed_with_errors"}
            and isinstance(report.get("diagnosis"), dict)
        ):
            await _publish_keep_diagnosis(
                publisher=keep_publisher,
                incident_id=final_incident_id,
                payload=payload_dict,
                report=report,
                alert_status=entry["alert_status"] or "firing",
                resolved_at=entry["resolved_at"],
            )
            if entry["alert_status"] == "resolved":
                await _publish_keep_resolution(
                    publisher=keep_publisher,
                    incident_id=final_incident_id,
                    dedup_key=entry["dedup_key"],
                    fingerprints=[
                        alert["fingerprint"]
                        for alert in payload_dict.get("alerts", [])
                        if isinstance(alert, dict)
                        and isinstance(alert.get("fingerprint"), str)
                    ],
                    resolved_at=entry["resolved_at"],
                )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Erreur irrécupérable dans le graphe. incident_id=%s", incident_id)
        emit_trace_event(
            "incident_failed",
            incident_id,
            error_type=type(exc).__name__,
        )
        if incident_id in store:
            store[incident_id] = {
                **store[incident_id],
                "status": "failed",
                "failure": str(exc),
                "progress": "Échec de l'investigation",
            }


async def _publish_keep_diagnosis(
    *,
    publisher: KeepPublisher,
    incident_id: str,
    payload: dict,
    report: dict,
    alert_status: str,
    resolved_at: str | None,
) -> None:
    try:
        keep_incident_id = await publisher.publish_diagnosis(
            agent_incident_id=incident_id,
            payload=payload,
            report=report,
            alert_status=alert_status,
            resolved_at=resolved_at,
        )
        emit_trace_event(
            "keep_diagnosis_published",
            incident_id,
            keep_incident_id=keep_incident_id,
        )
        logger.info(
            "Pré-analyse publiée dans Keep. incident_id=%s keep_incident_id=%s",
            incident_id,
            keep_incident_id,
        )
    except KeepAPIError as exc:
        emit_trace_event(
            "keep_publication_failed",
            incident_id,
            operation="diagnosis",
            error_type=type(exc).__name__,
            status_code=exc.status_code,
        )
        logger.error(
            "Échec publication Keep (diagnosis). incident_id=%s error=%s",
            incident_id,
            exc,
        )


async def _publish_keep_resolution(
    *,
    publisher: KeepPublisher,
    incident_id: str,
    dedup_key: str,
    fingerprints: list[str],
    resolved_at: str | None,
) -> None:
    try:
        keep_incident_ids = await publisher.publish_resolution(
            dedup_key=dedup_key,
            fingerprints=fingerprints,
            resolved_at=resolved_at,
        )
        emit_trace_event(
            "keep_resolution_published",
            incident_id,
            keep_incident_ids=keep_incident_ids,
        )
        logger.info(
            "Résolution publiée dans Keep. incident_id=%s keep_incident_ids=%s",
            incident_id,
            keep_incident_ids,
        )
    except KeepAPIError as exc:
        emit_trace_event(
            "keep_publication_failed",
            incident_id,
            operation="resolution",
            error_type=type(exc).__name__,
            status_code=exc.status_code,
        )
        logger.error(
            "Échec publication Keep (resolution). incident_id=%s error=%s",
            incident_id,
            exc,
        )
