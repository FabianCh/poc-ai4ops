"""
Test live Vertex AI — OPT-IN uniquement.

Ce test effectue un vrai appel réseau vers Vertex AI.
Il est ignoré par défaut et n'est jamais exécuté dans la suite standard.

Pour l'exécuter manuellement :
    uv run pytest tests/live/test_vertex_gemini.py -v -s

Prérequis :
    - LLM_PROVIDER=gemini dans .env
    - GOOGLE_APPLICATION_CREDENTIALS pointant vers un service account valide
    - GOOGLE_CLOUD_PROJECT et VERTEX_AI_LOCATION définis
    - Le modèle LLM_MODEL accessible depuis le projet/région
"""

import os

import pytest
from dotenv import load_dotenv

# Charger le .env AVANT d'évaluer les conditions de skip
load_dotenv()

# Ignorer ce test si les variables requises ne sont pas présentes
# ou si LLM_PROVIDER != gemini
_REQUIRED_VARS = [
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
]

_missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
_not_gemini = os.environ.get("LLM_PROVIDER", "mock") != "gemini"

pytestmark = pytest.mark.skipif(
    bool(_missing) or _not_gemini,
    reason=(
        f"Test live ignoré. LLM_PROVIDER={'gemini' if not _not_gemini else os.environ.get('LLM_PROVIDER', 'mock')} "
        f"Variables manquantes : {_missing or 'aucune'}"
    ),
)

# Contexte d'incident minimal pour le test live
_TEST_CONTEXT = {
    "incident": {
        "id": "live-test-001",
        "alert_name": "OtelDemoServiceHighErrorRate",
        "service": "product-catalog",
        "namespace": "otel-demo",
        "severity": "critical",
        "started_at": "2026-10-05T12:00:00Z",
    },
    "observations": {
        "metrics": {
            "error_rate": 0.18,
            "latency_p95_ms": 4200,
            "cpu_ratio": 0.42,
            "window_minutes": 15,
        },
        "logs": {
            "error_count": 31,
            "top_patterns": [
                {"pattern": "timeout connecting to redis:6379", "count": 31}
            ],
            "sample_event_ids": ["log-001"],
        },
        "kubernetes": {
            "desired_replicas": 2,
            "ready_replicas": 2,
            "restart_count": 0,
            "recent_events": [],
        },
    },
    "source_status": {
        "metrics": "success",
        "logs": "success",
        "cluster": "success",
    },
}


async def test_vertex_gemini_live_call() -> None:
    """
    Appel live unique vers Vertex AI — valide la chaîne complète :
    credentials → API → structured output → DiagnosticOutput Pydantic.
    """
    from dotenv import load_dotenv
    load_dotenv()

    from ia4ops_agent.config import settings
    from ia4ops_agent.domain.diagnosis import DiagnosticOutput
    from ia4ops_agent.llm.client import GeminiVertexClient

    model = settings.vertex_model
    project = settings.google_cloud_project
    location = settings.vertex_ai_location

    print(f"\n  Modèle  : {model}")
    print(f"  Projet  : {project}")
    print(f"  Région  : {location}")
    print("  Appel en cours...")

    try:
        client = GeminiVertexClient(
            model_name=model,
            project=project,
            location=location,
        )
        output, summary = await client.diagnose(_TEST_CONTEXT)

    except Exception as exc:
        print(f"\n  ÉCHEC — type     : {type(exc).__name__}")
        print(f"          modèle   : {model}")
        print(f"          région   : {location}")
        print(f"          projet   : {project}")
        print(f"          message  : {str(exc)[:300]}")
        raise

    # Vérifications
    assert isinstance(output, DiagnosticOutput), "La sortie doit être un DiagnosticOutput"
    assert output.action_executed is False, "action_executed doit être False"
    assert output.affected_service, "affected_service ne doit pas être vide"
    assert output.severity_assessment, "severity_assessment ne doit pas être vide"
    assert len(output.evidence) >= 1, "Au moins une preuve doit être présente"

    print(f"\n  OK — attempts={summary.total_attempts} duration={summary.total_duration_ms}ms")
    print(f"  Service   : {output.affected_service}")
    print(f"  Sévérité  : {output.severity_assessment}")
    print(f"  Hypothèse : {output.primary_hypothesis.title}")
    print(f"  Summary   : {output.summary[:120]}...")
    print(f"  Preuves   : {len(output.evidence)}")
    print(f"  Action    : {output.action_executed}")
