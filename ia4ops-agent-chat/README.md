# IA4Ops Agent Chat — copie expérimentale

Cette application est une **copie indépendante** de `ia4ops-agent`, créée pour développer une
interface chatbot Chainlit sans modifier l'agent stable.

Pour toute évolution visuelle de l'interface, suivre le
[guide de direction artistique IA4Ops](../GUIDE-DIRECTION-ARTISTIQUE-IHM.md).

> **État** : interface Chainlit, investigation manuelle et parcours d'approbation Alertmanager
> implémentés ; validation navigateur, authentification et déploiement isolé restent à faire.
> Ce projet ne remplace pas `ia4ops-agent`.

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

### Identité visuelle

L'interface reprend la palette du guide IA4Ops/Wavestone, avec un thème clair par défaut, un thème
sombre compatible, une typographie Aptos avec repli système et des styles clavier visibles. Le thème
et les ajustements CSS sont propres à cette copie (`public/theme.json` et `public/custom.css`).
Les logos Wavestone officiels fournis sont utilisés pour le logo de l'application et son avatar W,
avec une variante blanche en thème sombre (`public/logo_light.svg`, `public/logo_dark.svg` et
`public/wavestone_W_logo_color.svg`). En thème sombre, le fond est bleu nuit plus profond, le vert de
la palette met en évidence les titres et le bouton d'envoi, et la zone de saisie conserve une surface
distincte sans encadrement au focus (dans les deux thèmes). Les alertes en attente ont un en-tête
d'avertissement et un panneau visuel dédié rappelant qu'aucune investigation ne démarre avant décision
de l'opérateur.

### Demander une investigation

Si `REQUEST_INTERPRETER_PROVIDER=gemini`, décrire l'investigation en langage naturel :

```text
Pourquoi checkout génère des erreurs depuis une demi-heure ?
```

L'interpréteur Gemini via Vertex AI extrait le service, la période et la question dans une réponse
JSON contrainte. L'application valide ensuite les valeurs et demande une confirmation explicite
avant de lancer l'investigation. Un service inconnu ou ambigu déclenche une demande de précision ;
aucune collecte ne commence à ce stade. Les services proposés sont limités au catalogue OTel Demo.

```text
Demande comprise — confirmation requise
Service : checkout · Fenêtre : 30 minutes
Question : Pourquoi checkout génère-t-il des erreurs ?
[Confirmer et investiguer] [Annuler]
```

La fenêtre par défaut est de 15 minutes et la limite est de 1 à 60 minutes. L'interpréteur n'a aucun
outil et ne peut pas appeler les providers ni démarrer le graphe ; il ne remplit que les paramètres
bornés. En cas de panne ou de réponse invalide, la demande échoue explicitement sans lancer
l'investigation. L'ancienne commande reste disponible :

```text
/investigate product-catalog 15 | Pourquoi le taux d'erreur augmente ?
```

Le paramètre `REQUEST_INTERPRETER_PROVIDER` est indépendant de `LLM_PROVIDER` : sa valeur par
défaut `disabled` évite tout appel LLM additionnel. Pour activer l'interprétation naturelle,
configurer `REQUEST_INTERPRETER_PROVIDER=gemini` et renseigner les variables Vertex AI/GCP. Le
diagnostic reste en mock si `LLM_PROVIDER=mock`. L'API `POST /api/v1/investigations/interpret`
ne fait qu'interpréter ; seul `POST /api/v1/investigations`, appelé après confirmation opérateur,
démarre le graphe.

`LLM_PROVIDER=mock` est le défaut pour le **diagnostic** et n'appelle pas Vertex AI. Si
`REQUEST_INTERPRETER_PROVIDER=gemini`, Vertex AI est appelé uniquement pour interpréter chaque
message naturel avant la confirmation ; le diagnostic demeure mock. Le diagnostic FakeLLM est
préconfiguré et ne reflète pas nécessairement les données de la collecte ; l'IHM avertit
l'opérateur et affiche séparément les observations issues des providers. `DATA_PROVIDER=mock`
(défaut) produit aussi des observations synthétiques. `DATA_PROVIDER=real` active Prometheus/Loki
via Grafana (`GRAFANA_*`) sans activer Gemini pour le diagnostic. Les providers Kubernetes réels
ne sont pas implémentés.

### Alertes Alertmanager

Le webhook de cette copie valide et déduplique les notifications. Une alerte `firing` est ajoutée
à la file d'attente ; le webhook ne démarre pas le diagnostic. Les chats Chainlit actifs vérifient
la file périodiquement et affichent des boutons **Investiguer** et **Ignorer**. Une nouvelle session
affiche aussi les alertes encore en attente. L'approbation démarre le même graphe en lecture seule ;
une alerte ignorée ne lance aucune collecte. Une alerte `resolved` reçue avant décision est clôturée
sans diagnostic.

Les routes de décision ne peuvent être utilisées qu'une fois : si un autre opérateur a déjà décidé,
l'API répond `409 Conflict`. Les alertes et la déduplication sont actuellement en mémoire et sont
perdues au redémarrage du processus ; cette version ne doit donc pas encore servir de file d'alertes
durable.

```text
POST /webhooks/alertmanager
        ↓
Validation + déduplication → alerte en attente
        ↓
GET /api/v1/alerts/pending → notification Chainlit
        ↓
POST /api/v1/alerts/{incident_id}/decision
        ├── investigate → graphe LangGraph → rapport
        └── ignore      → clôture sans diagnostic
```

L'interface n'a pas encore de contrôle d'accès : utiliser uniquement en local ou dans un réseau de
test protégé. Ne pas l'exposer publiquement avant l'ajout et la validation de l'authentification.

## Tests et lint

```powershell
uv run pytest
uv run ruff check .
```

Les tests live sont exclus par défaut ; ils ne doivent pas être lancés automatiquement.

## Parcours de l'agent stable

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

L'agent stable continue de déclencher son diagnostic Alertmanager sans approbation. Le webhook et
les décisions de cette copie sont distincts et ne modifient pas le comportement de l'agent stable.

## Isolation

- Projet de distribution et commande distincts : `ia4ops-agent-chat`.
- Identité d'application et acteur d'audit distincts : `ia4ops-agent-chat`.
- Le module Python `ia4ops_agent` est conservé ; cette copie est installée et exécutée
  indépendamment de l'agent stable.
- Aucun manifest Kubernetes ni pipeline de publication dédiés n'est encore en place.
- Ne pas utiliser les manifests ou commandes de déploiement de l'agent stable pour cette copie.

## Prochaines étapes

1. Valider le chat, le polling et les actions d'approbation dans un navigateur, d'abord avec mocks.
2. Décider et intégrer l'authentification avant toute exposition de l'interface.
3. Ajouter la persistance durable de la file et valider le comportement multi-opérateurs.
4. Créer une image, des manifests et un namespace distincts avant tout déploiement.

Voir le cadrage complet dans [`ia4ops-chatbot-plan.md`](../../ia4ops-chatbot-plan.md).
