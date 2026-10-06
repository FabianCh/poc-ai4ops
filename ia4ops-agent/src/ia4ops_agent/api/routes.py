"""
Routes FastAPI de l'agent IA4Ops.

Architecture asynchrone :
  POST /webhooks/alertmanager
    → valide le payload v4
    → déduplique par make_dedup_key()
    → retourne 200 immédiatement (Alertmanager ne réessaie pas)
    → lance le graphe LangGraph en BackgroundTask

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

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ia4ops_agent.api.models import (
    AlertAccepted,
    AlertDuplicate,
    AlertWebhookRequest,
    IncidentResponse,
)
from ia4ops_agent.audit.trace_logging import emit_trace_event

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /webhooks/alertmanager — point d'entrée Alertmanager
# ---------------------------------------------------------------------------


@router.post(
    "/webhooks/alertmanager",
    response_model=AlertAccepted | AlertDuplicate,
    summary="Réception d'une notification Alertmanager v4",
    description=(
        "Accepte un payload Alertmanager v4, déduplique par fingerprint+startsAt, "
        "lance le diagnostic en arrière-plan et retourne 200 immédiatement."
    ),
    tags=["webhook"],
)
async def receive_alertmanager_webhook(
    payload: AlertWebhookRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> AlertAccepted | AlertDuplicate:
    """
    Point d'entrée principal des alertes Alertmanager.

    Alertmanager exige un 2xx rapide. Le traitement (graphe LangGraph)
    s'exécute en BackgroundTask pour ne jamais bloquer la réponse.
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

    # --- Générer l'incident_id et réserver l'entrée avant le démarrage du graphe ---
    import uuid
    incident_id = f"inc-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

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
        "status": "pending",
        "received_at": received_at,
        "report": None,
        "failure": None,
    }

    logger.info(
        "Webhook accepté. incident_id=%s service(s)=%s",
        incident_id,
        payload.affected_services(),
    )

    # --- Lancer le graphe en arrière-plan ---
    background_tasks.add_task(
        _run_graph,
        app_state=app_state,
        incident_id=incident_id,
        payload_dict=payload.model_dump(mode="json"),
    )

    return AlertAccepted(incident_id=incident_id)


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

    try:
        graph = app_state.graph
        initial_state = {
            "raw_alert": payload_dict,
            "incident_id": incident_id,  # hint pour le nœud initialize
        }

        logger.debug("Démarrage du graphe pour incident_id=%s", incident_id)
        final_state = await graph.ainvoke(initial_state)

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
            "finalized_at": finalized_at,
            "report": report,
            "failure": None,
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
            }
