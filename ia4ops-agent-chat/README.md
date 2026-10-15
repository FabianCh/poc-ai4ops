# IA4Ops Agent Chat — copie expérimentale

Cette application est une **copie indépendante** de `ia4ops-agent`, créée pour développer une
interface chatbot Chainlit sans modifier l'agent stable.

> **État initial** : le backend FastAPI/LangGraph a été dupliqué depuis le commit stable
> `ebc2221`. L'interface Chainlit, le webhook dédié et le déploiement isolé ne sont pas encore
> implémentés. Ce projet est distinct et ne remplace pas `ia4ops-agent`.

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

## Démarrage du backend hérité

```powershell
uv run uvicorn ia4ops_agent.main:app --reload --port 8000
```

Le LLM est mocké par défaut (`LLM_PROVIDER=mock`) ; aucune requête Vertex AI n'est effectuée.
Les providers Prometheus et Loki se configurent indépendamment via `DATA_PROVIDER=real` et les
variables `GRAFANA_*`. Le provider Kubernetes réel n'est pas implémenté.

> La commande ci-dessus démarre uniquement l'API FastAPI héritée. L'IHM Chainlit reste à créer.

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

L'API reste utile comme base fonctionnelle pour la prochaine étape, mais le workflow actuel reçoit
des alertes par webhook ; il ne fournit pas encore un endpoint de diagnostic conversationnel.

## Isolation

- Projet de distribution et commande distincts : `ia4ops-agent-chat`.
- Identité d'application et acteur d'audit distincts : `ia4ops-agent-chat`.
- Le module Python `ia4ops_agent` est conservé ; cette copie est installée et exécutée
  indépendamment de l'agent stable.
- Aucun manifest Kubernetes ni pipeline de publication dédiés n'est encore en place.
- Ne pas utiliser les manifests ou commandes de déploiement de l'agent stable pour cette copie.

## Prochaines étapes

1. Valider cette copie et son lockfile.
2. Ajouter l'interface Chainlit et définir son contrat avec le backend FastAPI.
3. Ajouter les investigations à la demande et les alertes en attente soumises à confirmation humaine.
4. Créer une image, des manifests et un namespace distincts avant tout déploiement.

Voir le cadrage complet dans [`ia4ops-chatbot-plan.md`](../../ia4ops-chatbot-plan.md).
