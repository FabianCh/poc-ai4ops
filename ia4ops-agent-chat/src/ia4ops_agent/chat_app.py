"""Interface Chainlit montée sur l'application FastAPI."""

import asyncio
import re
import time
from typing import Any
from uuid import uuid4

import chainlit as cl
import httpx
from pydantic import ValidationError

from ia4ops_agent.api.models import InvestigationInterpretation, InvestigationRequest
from ia4ops_agent.config import settings

_SERVICE_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$")
_DEFAULT_QUESTION = "Analyser les signaux disponibles et proposer les prochaines vérifications."
_POLL_INTERVAL_SECONDS = 1
_POLL_TIMEOUT_SECONDS = 180
_ALERT_POLL_INTERVAL_SECONDS = 3
_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def parse_investigation_message(message: str) -> InvestigationRequest:
    """Parse la commande bornée `/investigate service [minutes] | question`."""
    command, separator, question = message.partition("|")
    parts = command.split()
    if len(parts) not in (2, 3) or parts[0] != "/investigate":
        raise ValueError(
            "Format attendu : `/investigate <service> [minutes] | <question>` "
            "(fenêtre de 15 minutes par défaut)."
        )

    service = parts[1]
    if not _SERVICE_PATTERN.fullmatch(service):
        raise ValueError(
            "Le nom du service ne peut contenir que lettres, chiffres, `.`, `_` et `-`."
        )

    try:
        window_minutes = int(parts[2]) if len(parts) == 3 else 15
    except ValueError as exc:
        raise ValueError("La fenêtre doit être un nombre entier de minutes.") from exc

    try:
        return InvestigationRequest(
            service=service,
            window_minutes=window_minutes,
            question=question.strip() if separator else _DEFAULT_QUESTION,
        )
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ValueError(errors) from exc


def format_report(report: dict[str, Any], llm_provider: str, data_provider: str) -> str:
    """Présente séparément les observations collectées et le diagnostic généré."""
    context = report.get("context", {})
    observations = context.get("observations", {})
    metrics = observations.get("metrics") or {}
    logs = observations.get("logs") or {}
    diagnosis = report.get("diagnosis") or {}
    lines = [
        f"## Investigation `{report.get('incident_id', 'inconnu')}`",
        f"**Sources** : {report.get('source_status', {})}",
        "",
        "### Observations collectées",
    ]

    if metrics:
        error_rate = metrics.get("error_rate")
        error_rate_text = (
            f"{error_rate * 100:.1f} %" if isinstance(error_rate, (int, float)) else "n/d"
        )
        lines.append(
            f"- Métriques ({metrics.get('window_minutes', 'n/d')} min) : "
            f"taux d'erreur {error_rate_text}, "
            f"latence p95 {metrics.get('latency_p95_ms', 'n/d')} ms, "
            f"CPU {metrics.get('cpu_ratio', 'n/d')}, mémoire {metrics.get('memory_ratio', 'n/d')}."
        )
    else:
        lines.append("- Aucune observation de métriques disponible.")

    if logs:
        lines.append(
            f"- Logs Loki : {logs.get('error_count', 0)} erreur(s) agrégée(s) "
            f"sur {report.get('window_minutes', logs.get('window_minutes', 'n/d'))} min."
        )
        for pattern in logs.get("top_patterns", []):
            lines.append(
                f"  - `{pattern.get('level') or 'niveau inconnu'}` × {pattern.get('count', 0)} : "
                f"{pattern.get('pattern', '')}"
            )
    else:
        lines.append("- Aucun log d'erreur exploitable n'a été agrégé.")

    missing = report.get("missing_information", [])
    if missing:
        lines.extend(["", "### Limites et données manquantes"])
        lines.extend(f"- {item}" for item in missing)

    if data_provider == "mock":
        lines.extend(
            [
                "",
                "> **Mode démonstration — providers mockés** : les observations affichées "
                "sont synthétiques et ne proviennent pas de Grafana.",
            ]
        )

    if llm_provider == "mock":
        lines.extend(
            [
                "",
                "> **Mode démonstration — LLM mock** : le diagnostic ci-dessous est préconfiguré "
                "et ne doit pas être considéré comme une conclusion issue de ces observations.",
            ]
        )
        if data_provider == "real":
            lines.append(
                "> Les métriques et agrégats Loki affichés ci-dessus correspondent aux collectes "
                "réelles de ce run."
            )

    lines.extend(
        [
            "",
            "### Diagnostic",
            diagnosis.get("summary", "Aucun résumé de diagnostic."),
            "",
            f"**Sévérité estimée** : {diagnosis.get('severity_assessment', 'inconnue')}",
            "",
            "### Éléments de preuve du diagnostic",
        ]
    )
    evidence = diagnosis.get("evidence", [])
    if evidence:
        lines.extend(
            f"- `{item.get('reference', 'sans référence')}` — {item.get('observation', '')}"
            for item in evidence
        )
    else:
        lines.append("- Aucun élément de preuve fourni.")

    next_checks = diagnosis.get("recommended_next_checks", [])
    if next_checks:
        lines.extend(["", "### Prochaines vérifications suggérées"])
        lines.extend(f"- {item}" for item in next_checks)

    remediations = diagnosis.get("remediation_suggestions", [])
    if remediations:
        lines.extend(["", "### Pistes de remédiation (non exécutées)"])
        lines.extend(f"- {item}" for item in remediations)

    lines.extend(["", "**Aucune action n'a été exécutée.**"])
    return "\n".join(lines)


def format_investigation_confirmation(investigation: InvestigationRequest) -> str:
    """Summarize interpreted parameters before requesting explicit operator approval."""
    return (
        "### Demande comprise — confirmation requise\n\n"
        f"- **Service** : `{investigation.service}`\n"
        f"- **Fenêtre** : {investigation.window_minutes} minutes\n"
        f"- **Question** : {investigation.question}\n\n"
        "Aucune collecte ni aucun diagnostic ne démarre avant votre confirmation."
    )


def format_investigation_progress(
    service: str,
    current_step: str,
    spinner_frame: str = _SPINNER_FRAMES[0],
) -> str:
    """Render the active graph step with an animated indicator."""
    return (
        f"Investigation de `{service}` en cours…\n\n"
        f"{spinner_frame} **{current_step or 'Préparation de l’investigation'}**"
    )


def format_pending_alert(alert: dict[str, Any]) -> str:
    """Présente le résumé Alertmanager avant toute collecte ou analyse."""
    services = ", ".join(alert.get("affected_services") or [alert.get("service", "unknown")])
    lines = [
        "## ⚠️ Alerte à traiter — décision opérateur requise",
        "",
        "> **NOUVELLE ALERTE — EN ATTENTE DE VOTRE DÉCISION**  \n"
        "> Alertmanager a transmis cet événement. Aucune collecte ni aucun diagnostic ne démarre "
        "sans votre choix.",
        "",
        "### Détails de l'alerte",
        f"- **Alerte** : `{alert.get('alert_name', 'unknown')}`",
        f"- **Service(s)** : {services}",
        f"- **Namespace** : `{alert.get('namespace', 'unknown')}`",
        f"- **Sévérité** : `{alert.get('severity', 'unknown')}`",
        f"- **Début** : {alert.get('starts_at', 'inconnu')}",
        f"- **Alertes groupées** : {alert.get('alerts_count', 1)}",
    ]
    if alert.get("summary"):
        lines.append(f"- **Résumé** : {alert['summary']}")
    if alert.get("description"):
        lines.append(f"- **Détails** : {alert['description']}")
    lines.extend(
        [
            "",
            "Choisissez une action ci-dessous : lancer une investigation en lecture seule ou "
            "ignorer cette alerte.",
        ]
    )
    return "\n".join(lines)


async def _fetch_pending_alerts() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{settings.port}", timeout=5
    ) as client:
        response = await client.get("/api/v1/alerts/pending")
        response.raise_for_status()
        return response.json()


async def _notify_pending_alerts() -> None:
    notified_ids = cl.user_session.get("notified_alert_ids", set())
    try:
        alerts = await _fetch_pending_alerts()
    except httpx.HTTPError as exc:
        if not cl.user_session.get("alert_poll_error_reported", False):
            await cl.Message(
                content=f"Impossible de vérifier les alertes en attente : {exc}"
            ).send()
            cl.user_session.set("alert_poll_error_reported", True)
        return

    cl.user_session.set("alert_poll_error_reported", False)
    for alert in alerts:
        incident_id = alert["incident_id"]
        if incident_id in notified_ids:
            continue
        actions = [
            cl.Action(
                name="investigate_alert",
                payload={
                    "incident_id": incident_id,
                    "service": alert.get("service"),
                },
                label="Investiguer",
                icon="search",
            ),
            cl.Action(
                name="ignore_alert",
                payload={"incident_id": incident_id},
                label="Ignorer",
                icon="x",
            ),
        ]
        await cl.Message(content=format_pending_alert(alert), actions=actions).send()
        notified_ids.add(incident_id)
    cl.user_session.set("notified_alert_ids", notified_ids)


async def _poll_alerts_until_chat_ends() -> None:
    while True:
        await asyncio.sleep(_ALERT_POLL_INTERVAL_SECONDS)
        await _notify_pending_alerts()


async def _track_investigation(
    incident_id: str,
    service: str,
    progress: cl.Message,
) -> None:
    """Update one Chainlit message until the graph completes or fails."""
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{settings.port}", timeout=15
    ) as client:
        spinner_index = 0
        while time.monotonic() < deadline:
            response = await client.get(f"/api/v1/incidents/{incident_id}")
            if response.status_code != 200:
                progress.content = (
                    f"Impossible de consulter l'investigation `{incident_id}` : "
                    f"{_response_detail(response)}"
                )
                await progress.update()
                return
            incident = response.json()
            if incident["status"] in {"completed", "completed_with_errors"}:
                progress.content = format_report(
                    incident.get("report") or {},
                    settings.llm_provider,
                    settings.data_provider,
                )
                await progress.update()
                return
            if incident["status"] in {"failed", "ignored", "resolved"}:
                progress.content = (
                    f"Investigation `{incident_id}` terminée avec l'état "
                    f"`{incident['status']}` : "
                    f"{incident.get('failure') or 'aucun rapport disponible'}"
                )
                await progress.update()
                return

            progress.content = format_investigation_progress(
                service,
                incident.get("progress") or "",
                _SPINNER_FRAMES[spinner_index],
            )
            await progress.update()
            spinner_index = (spinner_index + 1) % len(_SPINNER_FRAMES)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    progress.content = (
        f"L'investigation `{incident_id}` est toujours en cours. "
        f"Consultez son état via `GET /api/v1/incidents/{incident_id}`."
    )
    await progress.update()


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("notified_alert_ids", set())
    cl.user_session.set("pending_interpretation_message", None)
    interpreter_mode = (
        "désactivé ; la commande structurée reste disponible"
        if settings.request_interpreter_provider == "disabled"
        else f"Vertex AI ({settings.request_interpreter_model})"
    )
    llm_mode = (
        "**LLM mock** : le diagnostic est préconfiguré et démonstratif."
        if settings.llm_provider == "mock"
        else f"LLM configuré : `{settings.llm_provider}`."
    )
    data_mode = (
        "**Providers de données mockés** : les observations sont synthétiques."
        if settings.data_provider == "mock"
        else "**Providers de données réels** : métriques/logs via Grafana."
    )
    await cl.Message(
        content=(
            "# IA4Ops\n"
            "### Assistant d'investigation SRE\n\n"
            "Analysez les signaux d'un service et obtenez un diagnostic argumenté, "
            "en **lecture seule**.\n\n"
            "---\n\n"
            "#### Lancer une investigation\n"
            "Décrivez votre demande en langage naturel, par exemple :\n\n"
            "> Pourquoi checkout génère des erreurs depuis une demi-heure ?\n\n"
            "Je vous présenterai le service et la période compris, puis vous pourrez confirmer "
            "ou annuler. La commande `/investigate <service> [minutes] | <question>` reste "
            "disponible. Fenêtre : **1 à 60 minutes** · Namespace : `otel-demo`.\n\n"
            "---\n\n"
            "#### Comment ça fonctionne\n"
            "- Les alertes entrantes attendent votre décision : **Investiguer** ou **Ignorer**.\n"
            "- Les observations, le diagnostic et ses limites sont présentés séparément.\n"
            "- Les pistes de remédiation sont des suggestions ; "
            "**aucune action n'est exécutée**.\n\n"
            f"**Mode IA** · {llm_mode}\n\n"
            f"**Interprétation du langage naturel** · {interpreter_mode}\n\n"
            f"**Sources** · {data_mode}"
        )
    ).send()
    await _notify_pending_alerts()
    task = asyncio.create_task(_poll_alerts_until_chat_ends())
    cl.user_session.set("alert_poll_task", task)


@cl.on_chat_end
async def on_chat_end() -> None:
    task = cl.user_session.get("alert_poll_task")
    if task is not None:
        task.cancel()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    base_url = f"http://127.0.0.1:{settings.port}"
    if message.content.strip().startswith("/investigate"):
        cl.user_session.set("pending_interpretation_message", None)
        try:
            investigation = parse_investigation_message(message.content)
        except ValueError as exc:
            await cl.Message(content=f"Demande non valide : {exc}").send()
            return
        await _offer_investigation_confirmation(investigation)
        return

    previous_message = cl.user_session.get("pending_interpretation_message")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=25) as client:
            response = await client.post(
                "/api/v1/investigations/interpret",
                json={
                    "message": message.content,
                    "previous_message": previous_message,
                },
            )
            if response.status_code != 200:
                await cl.Message(
                    content=f"Impossible d'interpréter la demande : {_response_detail(response)}"
                ).send()
                return
            raw_interpretation = response.json()
    except httpx.RequestError as exc:
        await cl.Message(content=f"API IA4Ops injoignable sur `{base_url}` : {exc}").send()
        return

    try:
        interpretation = InvestigationInterpretation.model_validate(raw_interpretation)
    except ValidationError as exc:
        await cl.Message(
            content=f"Réponse d'interprétation invalide ; aucune investigation lancée : {exc}"
        ).send()
        return

    if interpretation.status == "needs_clarification":
        context = (
            f"{previous_message}\nPrécision de l'opérateur : {message.content}"
            if previous_message
            else message.content
        )
        if len(context) > 2000:
            cl.user_session.set("pending_interpretation_message", None)
            await cl.Message(
                content="Le contexte est trop long. Reformulez votre demande en un seul message."
            ).send()
            return
        cl.user_session.set("pending_interpretation_message", context)
        await cl.Message(
            content=(
                f"{interpretation.clarification_question}\n\n"
                "Aucune investigation n'a été lancée. Vous pouvez préciser votre demande."
            )
        ).send()
        return

    cl.user_session.set("pending_interpretation_message", None)
    try:
        investigation = InvestigationRequest(
            service=interpretation.service,
            window_minutes=interpretation.window_minutes,
            question=interpretation.question,
        )
    except ValidationError as exc:
        await cl.Message(
            content=f"Paramètres interprétés invalides ; aucune investigation lancée : {exc}"
        ).send()
        return
    await _offer_investigation_confirmation(investigation)


async def _offer_investigation_confirmation(investigation: InvestigationRequest) -> None:
    confirmation_id = uuid4().hex
    cl.user_session.set(
        "pending_investigation_confirmation",
        {
            "confirmation_id": confirmation_id,
            "investigation": investigation.model_dump(),
        },
    )
    actions = [
        cl.Action(
            name="confirm_investigation",
            payload={"confirmation_id": confirmation_id},
            label="Confirmer et investiguer",
            icon="search",
        ),
        cl.Action(
            name="cancel_investigation",
            payload={"confirmation_id": confirmation_id},
            label="Annuler",
            icon="x",
        ),
    ]
    await cl.Message(
        content=format_investigation_confirmation(investigation),
        actions=actions,
    ).send()


@cl.action_callback("confirm_investigation")
async def confirm_investigation(action: cl.Action) -> None:
    pending = cl.user_session.get("pending_investigation_confirmation")
    confirmation_id = action.payload.get("confirmation_id")
    if (
        not isinstance(pending, dict)
        or not isinstance(confirmation_id, str)
        or pending.get("confirmation_id") != confirmation_id
    ):
        await action.remove()
        await cl.Message(
            content="Cette confirmation est expirée ou a déjà été utilisée."
        ).send()
        return
    cl.user_session.set("pending_investigation_confirmation", None)

    try:
        investigation = InvestigationRequest.model_validate(pending.get("investigation"))
    except ValidationError as exc:
        await cl.Message(
            content=f"Confirmation invalide ; aucune investigation lancée : {exc}"
        ).send()
        await action.remove()
        return

    await action.remove()
    progress = cl.Message(
        content=format_investigation_progress(investigation.service, "")
    )
    await progress.send()
    base_url = f"http://127.0.0.1:{settings.port}"
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
            accepted_response = await client.post(
                "/api/v1/investigations",
                json=investigation.model_dump(),
            )
            if accepted_response.status_code != 202:
                progress.content = (
                    "Impossible de démarrer l'investigation : "
                    f"{_response_detail(accepted_response)}"
                )
                await progress.update()
                return

            incident_id = accepted_response.json()["incident_id"]
        await _track_investigation(incident_id, investigation.service, progress)
    except httpx.RequestError as exc:
        progress.content = f"API IA4Ops injoignable sur `{base_url}` : {exc}"
        await progress.update()


@cl.action_callback("cancel_investigation")
async def cancel_investigation(action: cl.Action) -> None:
    pending = cl.user_session.get("pending_investigation_confirmation")
    confirmation_id = action.payload.get("confirmation_id")
    if (
        not isinstance(pending, dict)
        or not isinstance(confirmation_id, str)
        or pending.get("confirmation_id") != confirmation_id
    ):
        await action.remove()
        await cl.Message(
            content="Cette confirmation est expirée ou a déjà été utilisée."
        ).send()
        return
    cl.user_session.set("pending_investigation_confirmation", None)
    await action.remove()
    await cl.Message(content="Investigation annulée ; aucune collecte n'a été lancée.").send()


@cl.action_callback("investigate_alert")
async def investigate_alert(action: cl.Action) -> None:
    incident_id = action.payload.get("incident_id")
    service = action.payload.get("service")
    if not isinstance(incident_id, str):
        await cl.Message(content="Action invalide : identifiant d'alerte manquant.").send()
        return
    if not isinstance(service, str) or not service:
        service = "service concerné par l'alerte"

    progress: cl.Message | None = None
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{settings.port}", timeout=15
        ) as client:
            response = await client.post(
                f"/api/v1/alerts/{incident_id}/decision",
                json={"action": "investigate"},
            )
            if response.status_code != 200:
                await cl.Message(
                    content=(
                        f"Décision refusée pour `{incident_id}` : "
                        f"{_response_detail(response)}"
                    )
                ).send()
                if response.status_code == 409:
                    await action.remove()
                return
        await action.remove()
        progress = cl.Message(content=format_investigation_progress(service, ""))
        await progress.send()
        await _track_investigation(incident_id, service, progress)
    except httpx.RequestError as exc:
        if progress is None:
            await cl.Message(content=f"API IA4Ops injoignable : {exc}").send()
        else:
            progress.content = f"API IA4Ops injoignable : {exc}"
            await progress.update()


@cl.action_callback("ignore_alert")
async def ignore_alert(action: cl.Action) -> None:
    incident_id = action.payload.get("incident_id")
    if not isinstance(incident_id, str):
        await cl.Message(content="Action invalide : identifiant d'alerte manquant.").send()
        return

    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{settings.port}", timeout=15
        ) as client:
            response = await client.post(
                f"/api/v1/alerts/{incident_id}/decision",
                json={"action": "ignore"},
            )
            if response.status_code != 200:
                await cl.Message(
                    content=(
                        f"Décision refusée pour `{incident_id}` : "
                        f"{_response_detail(response)}"
                    )
                ).send()
                if response.status_code == 409:
                    await action.remove()
                return
            await action.remove()
            await cl.Message(
                content=f"Alerte `{incident_id}` ignorée. Aucun diagnostic n'a été lancé."
            ).send()
    except httpx.RequestError as exc:
        await cl.Message(content=f"API IA4Ops injoignable : {exc}").send()


def _response_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:500]}"
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return f"HTTP {response.status_code}: {detail}"
