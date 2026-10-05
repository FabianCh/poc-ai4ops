"""
Configuration pytest pour les tests d'intégration.

Force LLM_PROVIDER=mock avant tout import de l'application pour que
le lifespan FastAPI utilise FakeLLMClient, indépendamment du .env réel.
Cela permet aux tests de tourner sans credentials GCP.
"""

import os

# Doit être fait AVANT tout import de ia4ops_agent
os.environ.setdefault("LLM_PROVIDER", "mock")
# Forcer explicitement même si .env a LLM_PROVIDER=gemini
os.environ["LLM_PROVIDER"] = "mock"
