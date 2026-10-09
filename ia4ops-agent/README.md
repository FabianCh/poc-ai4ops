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
POST /webhooks/alertmanager  (Alertmanager webhook v4)
        ↓
[Validation Pydantic + déduplication fingerprint + startsAt]
        ↓
[Réponse 200 immédiate]
        ↓ (arrière-plan)
[Workflow LangGraph]
   ├── collect_metrics  (Prometheus : spanmetrics + conteneur)
   ├── collect_traces   (Jaeger : traces en erreur)
   ├── collect_logs     (Loki : error/warn, erreurs en INFO, logs des traces en erreur)
   ├── collect_cluster  (Kubernetes API)
   ├── build_context
   ├── diagnose         (Gemini Flash / FakeLLM)
   ├── validate         (guardrails déterministes)
   └── finalize         (rapport + audit trail)
        ↓
GET /api/v1/incidents/{incident_id}
```

Voir `docs/architecture.md` pour le diagramme complet.

### Sources du contexte de diagnostic

Toutes les sources passent par le proxy Grafana (mêmes identifiants, aucun droit Kubernetes).
Chaque source est non bloquante : en cas d'échec, elle passe `unavailable` et figure dans
`known_missing`. Le contexte transmis à Gemini est borné.

| Source | Contenu retenu |
|---|---|
| Alerte | nom, service, sévérité, `startsAt`, taille du groupe, annotations `summary`/`description`/`runbook_url` (≤ 300 car.) |
| Prometheus | taux d'erreur, p95, débit (spanmetrics) ; mémoire (ratio par pod, octets), CPU (cœurs), redémarrages et OOMKilled sur 10 min |
| Jaeger | nombre de traces en erreur, top 5 spans en erreur (service, opération, message tronqué à 200 car., codes de statut), chaîne de services, ≤ 3 identifiants de trace |
| Loki | lignes error/warn du service, lignes dont le contenu évoque une panne (même en INFO), lignes error/warn des traces en erreur (tous services) ; top 5 motifs |
| Kubernetes | non disponible (provider réel hors périmètre) |

Les annotations, messages de traces et logs sont des données non fiables : le prompt système
interdit de suivre toute instruction qui s'y trouve, et seuls des champs d'une liste blanche sont
copiés depuis Jaeger.

## Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock` ou `gemini` |
| `DATA_PROVIDER` | `mock` | `mock` ou `real` pour métriques et logs ; le provider Kubernetes réel reste incomplet |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Chemin vers le service account JSON GCP |
| `GOOGLE_CLOUD_PROJECT` | — | ID du projet GCP |
| `VERTEX_AI_LOCATION` | `europe-west1` | Région Vertex AI |
| `GRAFANA_BASE_URL` | — | URL Grafana (proxy Prometheus/Loki) |
| `GRAFANA_USERNAME` | `admin` | Utilisateur Grafana |
| `GRAFANA_PASSWORD` | — | Mot de passe Grafana |
| `KEEP_API_BASE_URL` | — | URL racine de l'API Keep ; le Deployment utilise le service interne sans préfixe `/v2` |
| `KEEP_API_KEY` | — | Clé API Keep, à conserver hors du dépôt |
| `LOG_LEVEL` | `INFO` | Niveau de log |
| `AUDIT_DIR` | `audit_logs` | Répertoire de l'audit trail |

Lorsque `KEEP_API_BASE_URL` et `KEEP_API_KEY` sont configurés, l'agent publie la pré-analyse
après le diagnostic, réutilise l'incident Keep déjà lié aux fingerprints et associe les nouvelles
alertes d'un groupe enrichi. Une notification `resolved` ajoute une activité de résolution sans
clore automatiquement l'incident Keep. Les notifications résolues répétées sont dédupliquées côté
agent en mémoire ; après redémarrage, l'état d'idempotence local est perdu. La publication Keep
est best-effort : un échec est tracé et ne bloque ni l'acquittement Alertmanager ni le rapport
local. L'association des alertes traite le `202 Accepted` comme un acquittement ; le corps de
réponse de cet endpoint n'est pas requis par l'agent. Les tests unitaires utilisent un transport
HTTP simulé ; l'intégration réelle doit être validée dans le cluster.
Le diagnostic est publié comme trois activités HTML distinctes : résumé (tableau service, sévérité,
état), hypothèse avec raisonnement, preuves et lien vers les logs du service dans Grafana
(`GRAFANA_BASE_URL`), puis limites et vérifications suggérées. Format imposé par le rendu de Keep
0.54.3 (`integrations/keep_html.py`) : une activité n'est rendue en HTML (listes, tableaux, liens)
que si elle commence par `<p>`, sinon retours à la ligne et tabulations sont réduits à des espaces ;
Markdown n'est pas interprété. Tout texte venant du LLM, des logs ou des labels est échappé ; seules
les balises `p`, `strong`, `em`, `ul`, `ol`, `li`, `table` et `a` (http/https) sont émises. Keep affiche
les activités du plus récent au plus ancien : elles sont postées dans l'ordre inverse (limites,
hypothèse, résumé) pour s'afficher dans le sens de lecture. L'incident est nommé
`<alerte> — <service> (<id agent>)` ; le service des alertes de conteneur (CPU, mémoire, OOM) est
déduit des labels `container` puis `pod`. Si Gemini renvoie une réponse invalide, l'agent réinjecte
les erreurs de validation dans sa tentative suivante. Si aucune réponse ne passe la validation, Keep
reçoit une activité unique indiquant clairement l'échec plutôt qu'un résumé ou une hypothèse vide.

## Image Docker

Construite par la pipeline [`.github/workflows/ia4ops-agent.yml`](../.github/workflows/ia4ops-agent.yml)
à chaque modification de `ia4ops-agent/**` sur `main` (tests puis build), et publiée sur GitHub
Container Registry :

```
ghcr.io/fabianch/poc-ai4ops/ia4ops-agent:latest       # dernière version de main
ghcr.io/fabianch/poc-ai4ops/ia4ops-agent:sha-<commit>  # version figée
```

Build et exécution en local :

```bash
docker build -t ia4ops-agent .
docker run --rm -p 8000:8000 ia4ops-agent                      # LLM_PROVIDER=mock
docker run --rm -p 8000:8000 --env-file .env ia4ops-agent      # configuration via .env
```

L'image (Python 3.14 slim, utilisateur non-root `10001`) écoute sur le port `8000`, expose
`/health` (utilisé par le `HEALTHCHECK`) et écrit l'audit trail dans `/app/audit_logs`
(`AUDIT_DIR`). Aucun secret n'est embarqué (`.env` et credentials exclus par `.dockerignore`) :
les fournir à l'exécution (variables d'environnement, secret Kubernetes monté).

## Déploiement sur le cluster

Manifests GitOps : [`manifest/applications/ia4ops-agent/`](../manifest/applications/ia4ops-agent/),
déployés par Flux dans le namespace `ia4ops` :

- `Deployment` 1 réplica ; le manifeste de test configure `LLM_PROVIDER=gemini` et
  `DATA_PROVIDER=real` (le comportement Gemini + providers réels via webhook reste à valider),
  non-root,
  système de fichiers en lecture seule, sans token d'API Kubernetes ; audit trail sur un PVC de 1 Gi ;
- `Service` ClusterIP `ia4ops-agent.ia4ops.svc:8000`, sans exposition publique ;
- `NetworkPolicy` : tout trafic entrant refusé, sauf depuis les pods Alertmanager du namespace
  `monitoring` (seule source prévue par le cadrage) ;
- Alertmanager route les alertes du namespace `otel-demo` vers
  `POST /webhooks/alertmanager` (`send_resolved: true`), configuré dans
  `manifest/base/kube-prometheus-stack/kube-prometheus-stack-helmrelease.yaml`.

Version déployée : tag `newTag` de `manifest/applications/ia4ops-agent/kustomization.yaml`
(`sha-<commit>` produit par la CI). Après chaque changement de code agent, attendre l'image de CI
puis référencer son tag avant le rollout. Le changement de configuration LLM ne suffit pas à
embarquer un correctif Keep qui n'est pas encore dans une image publiée.

### Secrets du cluster et rotation des identifiants

Les identifiants utilisés par l'agent sont actuellement fournis par des Kubernetes Secrets
créés hors Git ; ils ne sont ni gérés ni synchronisés automatiquement par Flux depuis Grafana
ou Keep. Le secret Grafana `grafana-credentials` est dans le namespace `ia4ops` et alimente
`GRAFANA_USERNAME`/`GRAFANA_PASSWORD`. Le secret `model-garden-credentials` y fournit le
compte de service Vertex AI. Le secret Keep `ia4ops-agent-keep` fournit la clé API de l'agent. Le client s'en sert pour publier
les pré-analyses et les activités de résolution ; la clé reste hors du dépôt Git.

Un redémarrage de cluster ne fait pas nécessairement tourner les identifiants. En revanche,
si Grafana ou Keep recrée/renouvelle ses identifiants (par exemple après une réinitialisation
ou une rotation), mettre à jour manuellement le Kubernetes Secret correspondant dans le
namespace `ia4ops`. Les variables d'environnement d'un conteneur ne sont pas actualisées dans
un pod déjà démarré : après la mise à jour du Secret, redémarrer le Deployment pour charger
les nouvelles valeurs, puis vérifier le rollout et les logs :

```bash
kubectl -n ia4ops rollout restart deployment/ia4ops-agent
kubectl -n ia4ops rollout status deployment/ia4ops-agent --timeout=180s
kubectl -n ia4ops logs deployment/ia4ops-agent --since=10m
```

Ne jamais inscrire les valeurs des secrets dans les manifests versionnés, les commandes
conservées dans l'historique du shell ou les logs. Après une rotation, vérifier également
l'accès à la datasource/service concerné depuis les événements du workflow.

```bash
kubectl -n ia4ops logs deploy/ia4ops-agent -f                  # webhooks reçus, graphes exécutés
kubectl -n ia4ops port-forward svc/ia4ops-agent 8000           # puis http://localhost:8000/docs
curl http://localhost:8000/api/v1/incidents/<incident_id>
```

### Traces de diagnostic dans Grafana / Loki

L'agent émet des événements JSON Lines sur stdout pour qu'Alloy les collecte avec les logs du pod.
Les événements partagent le même `incident_id` et couvrent la réception du webhook, les
observations Prometheus/Loki/Kubernetes, le contexte transmis au LLM, le diagnostic structuré
et la finalisation. La trace ne contient pas le webhook complet ni le prompt brut. Les extraits
de logs sont limités à 10 entrées de 500 caractères ; les champs identifiés comme secrets et
les chaînes de type mot de passe ou bearer token sont expurgés.

Dans Grafana Explore, sélectionner la datasource Loki et rechercher un incident :

```logql
{namespace="ia4ops"} | json | incident_id="inc-..."
```

Pour n'afficher que la réponse structurée du modèle :

```logql
{namespace="ia4ops"} | json | event="diagnosis_generated"
```

La disponibilité de ces événements dans Loki dépend de la collecte Alloy et de la rétention
Loki configurée sur la plateforme. Leur présence en cluster doit être vérifiée après déploiement.

## Raccordement plateforme

Pour connecter l'agent au cluster GCP de Fabian :

1. Récupérer le mot de passe Grafana : `kubectl get secret -n monitoring kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d`
2. Remplir `GRAFANA_BASE_URL`, `GRAFANA_USER`, `GRAFANA_PASSWORD` dans `.env`
3. Basculer `LLM_PROVIDER=gemini` et fournir `GOOGLE_APPLICATION_CREDENTIALS`
4. Garder `DATA_PROVIDER=mock` pour utiliser Gemini avec les données simulées. Les providers
   Prometheus et Loki sont sélectionnables indépendamment avec `DATA_PROVIDER=real` après
   configuration de Grafana ; le provider Kubernetes réel reste incomplet.

Voir `providers/real/README.md` pour le détail des variables et des endpoints attendus.
