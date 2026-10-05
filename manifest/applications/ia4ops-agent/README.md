# IA4Ops Agent

Agent IA de diagnostic automatisé d'incidents d'exploitation (SRE / AIOps).

Reçoit les alertes Alertmanager via webhook, orchestre un workflow LangGraph de collecte et d'analyse, et produit un rapport de diagnostic structuré — en lecture seule, sans action sur le cluster.

## Prérequis

- Python 3.14
- [uv](https://docs.astral.sh/uv/) — gestionnaire de dépendances

## Installation

```bash
# Installer les dépendances (prod + dev)
uv sync --extra dev

# Copier et remplir les variables d'environnement
cp .env.example .env
```

## Démarrage local

```bash
# Avec le provider mocké (développement)
uv run uvicorn ia4ops_agent.main:app --reload --port 8000

# Avec Gemini Flash (nécessite un service account GCP valide)
LLM_PROVIDER=gemini uv run uvicorn ia4ops_agent.main:app --reload --port 8000
```

Ou via le script d'aide :

```bash
bash scripts/run_local.sh
```

## Tests

```bash
# Tous les tests
uv run pytest

# Tests unitaires uniquement
uv run pytest tests/unit/ -v

# Tests d'intégration
uv run pytest tests/integration/ -v

# Lint
uv run ruff check .
```

## Envoyer une alerte de test

```bash
# Cas A — taux d'erreur élevé + timeout dépendance
bash scripts/send_test_alert.sh case_a

# Cas B — pod instable / redémarrages fréquents
bash scripts/send_test_alert.sh case_b

# Cas C — données insuffisantes (logs unavailable)
bash scripts/send_test_alert.sh case_c
```

## Consulter un diagnostic

```bash
curl http://localhost:8000/api/v1/incidents/<incident_id>
```

## Architecture

```
POST /api/v1/alerts  (Alertmanager webhook v4)
        ↓
[Validation Pydantic + déduplication fingerprint]
        ↓
[Réponse 200 immédiate]
        ↓ (arrière-plan)
[Workflow LangGraph]
   ├── collect_metrics  (Prometheus)
   ├── collect_logs     (Loki)
   ├── collect_cluster  (Kubernetes API)
   ├── build_context
   ├── diagnose         (Gemini Flash / FakeLLM)
   ├── validate         (guardrails déterministes)
   └── finalize         (rapport + audit trail)
        ↓
GET /api/v1/incidents/{incident_id}
```

Voir `docs/architecture.md` pour le diagramme complet.

## Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock` ou `gemini` |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Chemin vers le service account JSON GCP |
| `GOOGLE_CLOUD_PROJECT` | — | ID du projet GCP |
| `VERTEX_AI_LOCATION` | `europe-west1` | Région Vertex AI |
| `GRAFANA_BASE_URL` | — | URL Grafana (proxy Prometheus/Loki) |
| `GRAFANA_USER` | `admin` | Utilisateur Grafana |
| `GRAFANA_PASSWORD` | — | Mot de passe Grafana |
| `LOG_LEVEL` | `INFO` | Niveau de log |
| `AUDIT_LOG_DIR` | `./audit_logs` | Répertoire de l'audit trail |

## Raccordement plateforme

Pour connecter l'agent au cluster GCP de Fabian :

1. Récupérer le mot de passe Grafana : `kubectl get secret -n monitoring kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d`
2. Remplir `GRAFANA_BASE_URL`, `GRAFANA_USER`, `GRAFANA_PASSWORD` dans `.env`
3. Basculer `LLM_PROVIDER=gemini` et fournir `GOOGLE_APPLICATION_CREDENTIALS`
4. Remplacer les providers mock par les implémentations réelles dans `providers/real/`

Voir `providers/real/README.md` pour le détail des variables et des endpoints attendus.
