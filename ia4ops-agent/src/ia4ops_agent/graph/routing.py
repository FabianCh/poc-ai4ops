"""
Routage conditionnel du graphe LangGraph.

Principe : unavailable ou partial ne bloquent pas le workflow si un diagnostic
prudent reste possible. Le graphe continue toujours vers build_context,
en laissant au LLM et au nœud validate le soin d'exprimer les limites.

Cas d'arrêt anticipé :
- Alerte Watchdog → END immédiatement (pas d'incident à diagnostiquer)
"""

from ia4ops_agent.graph.state import IncidentState


def route_after_initialize(state: IncidentState) -> str:
    """
    Après initialize : ignorer les alertes Watchdog, sinon collecter.
    """
    normalized = state.get("normalized_alert", {})
    if normalized.get("is_watchdog", False):
        return "end_watchdog"
    return "collect_metrics"


def route_after_collect_metrics(state: IncidentState) -> str:
    """
    Après collect_metrics : toujours continuer vers collect_traces.
    Même si métriques unavailable/invalid, le graphe poursuit.
    """
    return "collect_traces"


def route_after_collect_traces(state: IncidentState) -> str:
    """
    Après collect_traces : toujours continuer vers collect_logs.
    Traces indisponibles : les logs sont collectés sans identifiants de trace.
    """
    return "collect_logs"


def route_after_collect_logs(state: IncidentState) -> str:
    """
    Après collect_logs : toujours continuer vers collect_cluster.
    Unavailable est géré dans l'état (missing_information).
    """
    return "collect_cluster"


def route_after_collect_cluster(state: IncidentState) -> str:
    """
    Après collect_cluster : toujours continuer vers build_context.
    Le nœud build_context gère les données manquantes proprement.
    """
    return "build_context"


def route_after_validate(state: IncidentState) -> str:
    """
    Après validate : toujours aller vers finalize.
    Les erreurs de validation sont dans l'état (errors[]), pas bloquantes.
    """
    return "finalize"
