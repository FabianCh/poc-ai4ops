"""Interface Chainlit montée sur l'application FastAPI."""

import asyncio
import re
import time
from typing import Any

import chainlit as cl
import httpx
from pydantic import ValidationError

from ia4ops_agent.api.models import InvestigationRequest
from ia4ops_agent.config import settings

_SERVICE_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$")
_DEFAULT_QUESTION = "Analyser les signaux disponibles et proposer les prochaines vérifications."
_POLL_INTERVAL_SECONDS = 1
_POLL_TIMEOUT_SECONDS = 180


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


@cl.on_chat_start
async def on_chat_start() -> None:
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
            "# IA4Ops — investigation SRE\n\n"
            "Demandez une investigation en lecture seule avec :\n\n"
            "`/investigate <service> [minutes] | <question>`\n\n"
            "Exemple : `/investigate product-catalog 15 | Pourquoi le taux d'erreur augmente ?`\n\n"
            "Fenêtre autorisée : 1 à 60 minutes. Namespace : `otel-demo`.\n\n"
            f"{llm_mode}\n\n{data_mode}\n\n"
            "Les remédiations sont uniquement suggérées, jamais exécutées."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    try:
        investigation = parse_investigation_message(message.content)
    except ValueError as exc:
        await cl.Message(content=f"Demande non valide : {exc}").send()
        return

    progress = cl.Message(content=f"Investigation de `{investigation.service}` en cours…")
    await progress.send()
    base_url = f"http://127.0.0.1:{settings.port}"

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
            accepted_response = await client.post(
                "/api/v1/investigations",
                json=investigation.model_dump(),
            )
            if accepted_response.status_code != 202:
                detail = _response_detail(accepted_response)
                progress.content = f"Impossible de démarrer l'investigation : {detail}"
                await progress.update()
                return

            incident_id = accepted_response.json()["incident_id"]
            deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
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
                if incident["status"] == "failed":
                    progress.content = (
                        f"L'investigation `{incident_id}` a échoué : "
                        f"{incident.get('failure') or 'erreur non détaillée'}"
                    )
                    await progress.update()
                    return
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)

            progress.content = (
                f"L'investigation `{incident_id}` est toujours en cours. "
                "Consultez son état via l'API `GET /api/v1/incidents/{incident_id}`."
            )
            await progress.update()
    except httpx.RequestError as exc:
        progress.content = f"API IA4Ops injoignable sur `{base_url}` : {exc}"
        await progress.update()


def _response_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:500]}"
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return f"HTTP {response.status_code}: {detail}"
