"""
Assemblage et compilation du graphe LangGraph.

Le graphe est construit à partir des nœuds via des factories qui injectent
les dépendances (providers, LLMClient, AuditWriter). Le workflow ne connaît
jamais les implémentations concrètes.

Flux nominal :
  START → initialize → collect_metrics → collect_traces → collect_logs → collect_cluster
        → build_context → diagnose → validate → finalize → END

Branche Watchdog :
  initialize → end_watchdog → END
"""

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from ia4ops_agent.audit.writer import AuditWriter
from ia4ops_agent.graph.nodes.build_context import build_context_node
from ia4ops_agent.graph.nodes.collect_cluster import make_collect_cluster_node
from ia4ops_agent.graph.nodes.collect_logs import make_collect_logs_node
from ia4ops_agent.graph.nodes.collect_metrics import make_collect_metrics_node
from ia4ops_agent.graph.nodes.collect_traces import make_collect_traces_node
from ia4ops_agent.graph.nodes.diagnose import make_diagnose_node
from ia4ops_agent.graph.nodes.finalize import make_finalize_node
from ia4ops_agent.graph.nodes.initialize import initialize_node
from ia4ops_agent.graph.nodes.validate import validate_node
from ia4ops_agent.graph.routing import (
    route_after_collect_cluster,
    route_after_collect_logs,
    route_after_collect_metrics,
    route_after_collect_traces,
    route_after_initialize,
    route_after_validate,
)
from ia4ops_agent.graph.state import IncidentState
from ia4ops_agent.llm.interface import FakeLLMClient, LLMClient
from ia4ops_agent.providers.factory import Providers


def build_graph(
    providers: Providers | None = None,
    llm_client: LLMClient | None = None,
    audit_dir: Path | None = None,
):
    """
    Construit et compile le graphe LangGraph.

    Args:
        providers: Providers à utiliser (mock par défaut si None).
        llm_client: Client LLM à utiliser (FakeLLMClient par défaut si None).
        audit_dir: Répertoire de l'audit trail (défaut : ./audit_logs).

    Returns:
        Graphe LangGraph compilé prêt à être invoqué.
    """
    if providers is None:
        providers = Providers.mock()
    if llm_client is None:
        llm_client = FakeLLMClient()

    writer = AuditWriter(audit_dir=audit_dir)

    # Instancier les nœuds avec leurs dépendances
    collect_metrics = make_collect_metrics_node(providers.metrics)
    collect_traces = make_collect_traces_node(providers.traces)
    collect_logs = make_collect_logs_node(providers.logs)
    collect_cluster = make_collect_cluster_node(providers.cluster)
    diagnose = make_diagnose_node(llm_client)
    finalize = make_finalize_node(writer)

    # Construire le graphe
    graph = StateGraph(IncidentState)

    # Ajouter les nœuds
    graph.add_node("initialize", initialize_node)
    graph.add_node("collect_metrics", collect_metrics)
    graph.add_node("collect_traces", collect_traces)
    graph.add_node("collect_logs", collect_logs)
    graph.add_node("collect_cluster", collect_cluster)
    graph.add_node("build_context", build_context_node)
    graph.add_node("diagnose", diagnose)
    graph.add_node("validate", validate_node)
    graph.add_node("finalize", finalize)

    # Nœud terminal Watchdog (no-op — le graphe s'arrête)
    graph.add_node("end_watchdog", lambda state: {"warnings": ["Alerte Watchdog ignorée."]})

    # Arêtes fixes
    graph.add_edge(START, "initialize")
    graph.add_edge("build_context", "diagnose")
    graph.add_edge("diagnose", "validate")
    graph.add_edge("finalize", END)
    graph.add_edge("end_watchdog", END)

    # Arêtes conditionnelles
    graph.add_conditional_edges(
        "initialize",
        route_after_initialize,
        {"collect_metrics": "collect_metrics", "end_watchdog": "end_watchdog"},
    )
    graph.add_conditional_edges(
        "collect_metrics",
        route_after_collect_metrics,
        {"collect_traces": "collect_traces"},
    )
    graph.add_conditional_edges(
        "collect_traces",
        route_after_collect_traces,
        {"collect_logs": "collect_logs"},
    )
    graph.add_conditional_edges(
        "collect_logs",
        route_after_collect_logs,
        {"collect_cluster": "collect_cluster"},
    )
    graph.add_conditional_edges(
        "collect_cluster",
        route_after_collect_cluster,
        {"build_context": "build_context"},
    )
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {"finalize": "finalize"},
    )

    return graph.compile()
