"""Mise en forme HTML des activités publiées dans Keep (fonctions pures, sans I/O).

Keep n'affiche un commentaire d'incident en HTML (assaini) que s'il contient `<p>` ; sinon il le
rend en texte brut, retours à la ligne et listes réduits à des espaces (validé sur Keep 0.54.3).
Chaque commentaire commence donc par `<p>`. Balises utilisées, toutes validées en rendu réel :
p, strong, em, ul, ol, li, table/thead/tbody/tr/th/td, a[href].

Tout texte venant du LLM, des logs ou des labels est normalisé puis ÉCHAPPÉ (`_t`) : seules les
balises ci-dessous, écrites par ce module, peuvent apparaître dans le HTML produit. Les liens
sont construits par l'agent et limités à http(s).
"""

import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from html import escape
from typing import Any
from urllib.parse import quote

_SOURCE_LABELS = {
    "metrics": "métriques",
    "logs": "logs",
    "traces": "traces",
    "cluster": "Kubernetes",
}
_ELLIPSIS = "…"


def _t(value: Any, fallback: str = "", limit: int = 500) -> str:
    """Texte affichable : espaces normalisés, coupé en fin de mot avec « … », puis échappé."""
    if not isinstance(value, str):
        return escape(fallback)
    text = " ".join(value.split())
    if not text:
        return escape(fallback)
    if len(text) > limit:
        cut = text[: limit - 1]
        # coupe sur un espace s'il y en a un, sinon au caractère (mot très long)
        text = (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip(" ,;:.") + _ELLIPSIS
    return escape(text)


def _texts(value: Any, *, limit: int, item_length: int) -> list[str]:
    """Liste de textes affichables (échappés), vides ignorés, bornée."""
    if not isinstance(value, list):
        return []
    items = [_t(item, "", item_length) for item in value if isinstance(item, str)]
    return [item for item in items if item][:limit]


def _ul(items: Iterable[str]) -> str:
    rows = "".join(f"<li>{item}</li>" for item in items)
    return f"<ul>{rows}</ul>" if rows else ""


def _ol(items: Iterable[str]) -> str:
    rows = "".join(f"<li>{item}</li>" for item in items)
    return f"<ol>{rows}</ol>" if rows else ""


def link(label: str, url: str) -> str:
    """Lien HTML ; vide si l'URL n'est pas en http(s). L'URL doit être construite par l'agent."""
    if not url.startswith(("http://", "https://")):
        return ""
    return f'<a href="{escape(url, quote=True)}">{_t(label, "lien", 80)}</a>'


def source_summary(source_status: Any) -> str:
    """« logs : success, métriques : success » (ordre alphabétique des sources)."""
    if not isinstance(source_status, dict) or not source_status:
        return "indisponible"
    return ", ".join(
        f"{_SOURCE_LABELS.get(name, name)} : {status}"
        for name, status in sorted(source_status.items())
    )


def _logql_value(value: str) -> str:
    """Valeur de label LogQL entre guillemets (les labels d'alerte ne sont pas de confiance)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def grafana_logs_url(
    base_url: str,
    *,
    namespace: str,
    service: str | None,
    start: datetime,
    end: datetime | None = None,
    datasource_uid: str = "loki",
) -> str:
    """Lien Grafana Explore (Loki) sur les logs du service, de 10 min avant l'alerte à sa fin."""
    # Mêmes labels que le provider Loki de l'agent (logs OTLP : service_name, k8s_namespace_name).
    matchers = []
    if service:
        matchers.append(f'service_name="{_logql_value(service)}"')
    matchers.append(f'k8s_namespace_name="{_logql_value(namespace)}"')
    selector = "{" + ",".join(matchers) + "}"
    end_value = (
        str(int((end + timedelta(minutes=5)).timestamp() * 1000)) if end is not None else "now"
    )
    pane = {
        "datasource": datasource_uid,
        "queries": [
            {
                "refId": "A",
                "expr": selector,
                "datasource": {"type": "loki", "uid": datasource_uid},
            }
        ],
        "range": {
            "from": str(int((start - timedelta(minutes=10)).timestamp() * 1000)),
            "to": end_value,
        },
    }
    panes = json.dumps({"a": pane}, separators=(",", ":"))
    return f"{base_url.rstrip('/')}/explore?schemaVersion=1&panes={quote(panes)}&orgId=1"


def build_comments(
    *,
    agent_incident_id: str,
    diagnosis: dict[str, Any],
    source_status: Any,
    alert_status: str,
    resolved_at: str | None,
    links: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Activités à publier, DANS L'ORDRE DE LECTURE (résumé, hypothèse, limites).

    Keep affiche les activités du plus récent au plus ancien : l'appelant doit les poster en
    ordre inverse pour que l'écran se lise dans cet ordre.
    """
    sources = source_summary(source_status)
    failure_reason = diagnosis.get("failure_reason")
    if isinstance(failure_reason, str) and failure_reason.strip():
        return [_failure_comment(agent_incident_id, diagnosis, failure_reason, sources)]

    state = (
        f"{alert_status} — {resolved_at}"
        if alert_status == "resolved" and resolved_at
        else alert_status
    )
    return [
        _summary_comment(agent_incident_id, diagnosis, state),
        _hypothesis_comment(diagnosis, links or []),
        _limits_comment(agent_incident_id, diagnosis, sources),
    ]


def build_resolution_comment(resolved_at: str | None) -> str:
    when = f" le {_t(resolved_at, '', 80)}" if resolved_at else ""
    return (
        "<p><strong>IA4Ops — Alerte résolue</strong></p>"
        f"<p>Alertmanager indique que ce groupe d'alertes est résolu{when}.</p>"
    )


def _failure_comment(
    agent_incident_id: str, diagnosis: dict[str, Any], failure_reason: str, sources: str
) -> str:
    attempts = diagnosis.get("attempts")
    attempt_text = (
        f"{attempts} tentative(s)"
        if isinstance(attempts, int) and not isinstance(attempts, bool)
        else "plusieurs tentatives"
    )
    agent_id = _t(agent_incident_id, "", 80)
    return (
        f"<p><strong>IA4Ops — Diagnostic indisponible</strong> ({agent_id})</p>"
        f"<p>Le modèle n'a pas produit de diagnostic valide après {attempt_text}.</p>"
        f"<p><strong>Détail</strong> : {_t(failure_reason, 'Erreur non détaillée.', 500)}</p>"
        f"<p><strong>Collecte</strong> : {_t(sources, 'indisponible', 300)}</p>"
        "<p><em>Aucune hypothèse fiable n'est publiée. "
        "Aucune action de remédiation n'a été exécutée.</em></p>"
    )


def _summary_comment(agent_incident_id: str, diagnosis: dict[str, Any], state: str) -> str:
    return (
        f"<p><strong>IA4Ops — Résumé du diagnostic</strong> ({_t(agent_incident_id, '', 80)})</p>"
        "<table><thead><tr><th>Service</th><th>Sévérité estimée</th>"
        "<th>État de l'alerte</th></tr></thead>"
        f"<tbody><tr><td>{_t(diagnosis.get('affected_service'), 'inconnu', 200)}</td>"
        f"<td>{_t(diagnosis.get('severity_assessment'), 'inconnue', 40)}</td>"
        f"<td>{_t(state, 'inconnu', 120)}</td></tr></tbody></table>"
        f"<p>{_t(diagnosis.get('summary'), 'Aucun résumé disponible.', 500)}</p>"
    )


def _hypothesis_comment(diagnosis: dict[str, Any], links: list[tuple[str, str]]) -> str:
    hypothesis = diagnosis.get("primary_hypothesis")
    if not isinstance(hypothesis, dict):
        hypothesis = {}
    evidence = diagnosis.get("evidence")
    evidence_items = [
        f"<strong>{_t(item.get('source'), 'observation', 40)}</strong> : "
        f"{_t(item.get('observation'), '', 400)}"
        for item in (evidence[:8] if isinstance(evidence, list) else [])
        if isinstance(item, dict) and _t(item.get("observation"), "", 400)
    ]
    section = (
        "<p><strong>IA4Ops — Hypothèse principale</strong> : "
        f"{_t(hypothesis.get('title'), 'Non déterminée', 200)} "
        f"(confiance : <em>{_t(hypothesis.get('likelihood'), 'inconnue', 20)}</em>)</p>"
    )
    reasoning = _t(hypothesis.get("reasoning"), "", 1000)
    if reasoning:
        section += f"<p>{reasoning}</p>"
    if evidence_items:
        section += "<p><strong>Éléments observés</strong></p>" + _ul(evidence_items)
    rendered_links = [html for label, url in links if (html := link(label, url))]
    if rendered_links:
        section += "<p>" + " · ".join(rendered_links) + "</p>"
    return section


def _limits_comment(agent_incident_id: str, diagnosis: dict[str, Any], sources: str) -> str:
    missing = _texts(diagnosis.get("missing_information"), limit=5, item_length=300)
    checks = _texts(diagnosis.get("recommended_next_checks"), limit=5, item_length=300)
    section = (
        "<p><strong>IA4Ops — Limites et prochaines étapes</strong> "
        f"({_t(agent_incident_id, '', 80)})</p>"
        f"<p><strong>Collecte</strong> : {_t(sources, 'indisponible', 300)}</p>"
    )
    if missing:
        section += "<p><strong>Informations manquantes</strong></p>" + _ul(missing)
    if checks:
        section += "<p><strong>Vérifications suggérées</strong></p>" + _ol(checks)
    return section + "<p><em>Aucune action de remédiation n'a été exécutée.</em></p>"
