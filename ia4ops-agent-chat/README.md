# IA4Ops Agent Chat — copie expérimentale

Cette application est une **copie indépendante** de `ia4ops-agent`, créée pour développer une
interface chatbot Chainlit sans modifier l'agent stable.

> **État** : copie indépendante créée depuis le commit stable `ebc2221`. L'interface Chainlit
> et le parcours d'investigation manuelle sont en cours ; le webhook d'alertes en attente et le
> déploiement isolé restent à faire. Ce projet ne remplace pas `ia4ops-agent`.

Le diagnostic reste en lecture seule. Pendant le développement, le LLM doit rester en mock ;
les providers de données Prometheus/Loki peuvent être configurés séparément en réel.

## Prérequis

- Python 3.14
- [uv](https://docs.astral.sh/uv/) — gestionnaire de dépendances

## Installation

```powershell
uv sync --locked --extra dev
Copy-Item .env.example .env
```

Renseigner les accès Grafana uniquement pour tester les providers réels. Ne jamais copier ni
committer de fichier `.env`, de credential ou de données d'audit de l'agent stable.

## Démarrage local

```powershell
uv run uvicorn ia4ops_agent.main:app --reload --port 8000
```

L'API est disponible sur `http://localhost:8000`, sa documentation sur `/docs` et le chatbot sur
[`/chat/`](http://localhost:8000/chat/).

### Demander une investigation

Dans le chat, saisir une commande structurée :

```text
/investigate <service> [minutes] | <question>
```

Exemple :

```text
/investigate product-catalog 15 | Pourquoi le taux d'erreur augmente ?
```

La durée est de 15 minutes par défaut et doit être comprise entre 1 et 60 minutes. Le namespace
est actuellement fixé à `otel-demo`. Le service est traité comme un identifiant, pas comme une
requête LogQL/PromQL. L'API `POST /api/v1/investigations` valide la demande, démarre le graphe en
arrière-plan et retourne un identifiant consultable via `GET /api/v1/incidents/{incident_id}`.

`LLM_PROVIDER=mock` est le défaut et n'appelle pas Vertex AI. Le diagnostic FakeLLM est préconfiguré
et ne reflète pas nécessairement les données de la collecte ; l'IHM avertit l'opérateur et affiche
séparément les observations issues des providers. `DATA_PROVIDER=mock` (défaut) produit aussi des
observations synthétiques. `DATA_PROVIDER=real` active Prometheus/Loki via Grafana (`GRAFANA_*`)
sans activer Gemini. Les providers Kubernetes réels ne sont pas implémentés.

L'interface n'a pas encore de contrôle d'accès : utiliser uniquement en local ou dans un réseau de
test protégé. Ne pas l'exposer publiquement avant l'ajout et la validation de l'authentification.

## Tests et lint

```powershell
uv run pytest
uv run ruff check .
```

Les tests live sont exclus par défaut ; ils ne doivent pas être lancés automatiquement.

## Architecture héritée

```text
POST /webhooks/alertmanager
        ↓
[Validation + déduplication]
        ↓
[Workflow LangGraph]
   ├── collecte métriques (Prometheus)
   ├── collecte logs (Loki)
   ├── collecte état cluster (provider réel indisponible)
   ├── diagnostic (FakeLLMClient par défaut)
   ├── validation déterministe
   └── rapport + audit trail
        ↓
GET /api/v1/incidents/{incident_id}
```

Le webhook Alertmanager hérité continue de déclencher son diagnostic sans approbation. Le nouveau
parcours manuel est distinct et requiert une demande explicite via l'API ou le chat.

## Isolation

- Projet de distribution et commande distincts : `ia4ops-agent-chat`.
- Identité d'application et acteur d'audit distincts : `ia4ops-agent-chat`.
- Le module Python `ia4ops_agent` est conservé ; cette copie est installée et exécutée
  indépendamment de l'agent stable.
- Aucun manifest Kubernetes ni pipeline de publication dédiés n'est encore en place.
- Ne pas utiliser les manifests ou commandes de déploiement de l'agent stable pour cette copie.

## Prochaines étapes

1. Valider l'expérience complète dans un navigateur avec les APIs Grafana réelles.
2. Ajouter le webhook de la copie et le parcours d'alertes en attente soumis à confirmation humaine.
3. Décider et intégrer l'authentification avant toute exposition de l'interface.
4. Créer une image, des manifests et un namespace distincts avant tout déploiement.

Voir le cadrage complet dans [`ia4ops-chatbot-plan.md`](../../ia4ops-chatbot-plan.md).
