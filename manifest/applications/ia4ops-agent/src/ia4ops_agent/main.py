"""
Point d'entrée de l'application FastAPI IA4Ops.

Lifespan :
  - Construit le graphe LangGraph une seule fois au démarrage
  - Initialise le store incidents (dict en mémoire) et le cache de déduplication
  - Nettoie les ressources à l'arrêt

Usage :
  uv run uvicorn ia4ops_agent.main:app --reload
  uv run uvicorn ia4ops_agent.main:app --host 0.0.0.0 --port 8000
"""

import logging
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ia4ops_agent.api.routes import router
from ia4ops_agent.config import settings
from ia4ops_agent.graph.builder import build_graph
from ia4ops_agent.llm.interface import FakeLLMClient
from ia4ops_agent.providers.factory import Providers

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan FastAPI — initialise et nettoie les ressources partagées.

    Ressources initialisées sur app.state :
    - graph             : graphe LangGraph compilé
    - incident_store    : dict {incident_id → IncidentEntry} en mémoire
    - dedup_cache       : OrderedDict {dedup_key → incident_id} (FIFO eviction)
    - dedup_cache_max_size : taille max du cache (depuis config)
    """
    logger.info("Démarrage de %s v%s", settings.app_name, settings.app_version)

    # --- Sélection des providers ---
    providers = Providers.from_env()
    logger.info("Providers initialisés (mode=%s)", settings.llm_provider)

    # --- Sélection du client LLM ---
    llm_client = FakeLLMClient()
    if settings.llm_provider == "gemini":
        if not settings.google_cloud_project:
            raise RuntimeError(
                "LLM_PROVIDER=gemini mais GOOGLE_CLOUD_PROJECT n'est pas défini dans .env"
            )
        from ia4ops_agent.llm.client import GeminiVertexClient
        llm_client = GeminiVertexClient(
            model_name=settings.vertex_model,
            project=settings.google_cloud_project,
            location=settings.effective_location,
        )
        logger.info(
            "LLM client : GeminiVertexClient (model=%s project=%s location=%s)",
            settings.vertex_model,
            settings.google_cloud_project,
            settings.effective_location,
        )
    else:
        logger.info("LLM client : FakeLLMClient (mode mock)")

    # --- Construire le graphe ---
    graph = build_graph(
        providers=providers,
        llm_client=llm_client,
        audit_dir=settings.audit_dir,
    )
    logger.info("Graphe LangGraph compilé.")

    # --- Initialiser l'état applicatif ---
    app.state.graph = graph
    app.state.incident_store: dict = {}
    app.state.dedup_cache: OrderedDict = OrderedDict()
    app.state.dedup_cache_max_size: int = settings.dedup_cache_max_size

    logger.info("Application prête. Écoute sur %s:%s", settings.host, settings.port)

    yield  # ← l'application est en service ici

    # --- Nettoyage à l'arrêt ---
    logger.info("Arrêt de l'application. %d incidents en mémoire.", len(app.state.incident_store))
    app.state.incident_store.clear()
    app.state.dedup_cache.clear()


# ---------------------------------------------------------------------------
# Création de l'application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="IA4Ops Agent",
    description=(
        "Agent IA de diagnostic automatisé d'incidents d'exploitation (SRE / AIOps). "
        "Reçoit les alertes Alertmanager, diagnostique via LangGraph + LLM, "
        "et produit un rapport structuré en lecture seule."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(router)


# ---------------------------------------------------------------------------
# Entrypoint CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Démarrage via `uv run ia4ops-agent` ou `python -m ia4ops_agent.main`."""
    import uvicorn

    uvicorn.run(
        "ia4ops_agent.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
