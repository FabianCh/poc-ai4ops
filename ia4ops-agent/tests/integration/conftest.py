"""
Configuration pytest pour les tests d'intégration.

Force les providers LLM et de données en mode mock avant tout import de
l'application, indépendamment du .env réel.
Cela permet aux tests de tourner sans credentials GCP ni services externes.
"""

import os

# Doit être fait AVANT tout import de ia4ops_agent
os.environ.setdefault("LLM_PROVIDER", "mock")
# Forcer explicitement même si .env a LLM_PROVIDER=gemini
os.environ["LLM_PROVIDER"] = "mock"
os.environ["DATA_PROVIDER"] = "mock"
