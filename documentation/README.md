# Documentation IA4Ops — base de connaissance

Ce dossier rassemble les documents de cadrage, de suivi et de référence du démonstrateur IA4Ops
(agent de diagnostic d'incidents en lecture seule). Il est destiné à servir de base de connaissance
pour les contributeurs et les assistants IA.

À ne pas confondre avec [`../docs/`](../docs/), qui contient la documentation d'exploitation de la
plateforme (endpoints, accès Cloud Shell, coûts, déploiement du chatbot).

## Index

| Document | Contenu | Quand le lire |
| --- | --- | --- |
| [ia4ops-cadrage.md](ia4ops-cadrage.md) | Cadrage de l'agent N0 dans le processus RUN : vision, périmètre, escalade, garde-fous, scénario de démo, statuts ACTÉ / PROPOSÉ / À CONFIRMER / ÉCARTÉ, écarts avec l'existant | Vision et périmètre cible ; avant tout choix de scénario ou travail de remédiation |
| [ia4ops-progress.md](ia4ops-progress.md) | Journal daté de l'avancement, validations, limites connues | Pour connaître l'état réel ; à mettre à jour à chaque étape |
| [ia4ops-agent-plan.md](ia4ops-agent-plan.md) | Plan des 8 tâches du scénario 1, décisions techniques, critères de validation | Implémentation et suivi de l'agent stable |
| [ia4ops-chatbot-plan.md](ia4ops-chatbot-plan.md) | Cadrage et étapes du chatbot Chainlit (`ia4ops-agent-chat/`) | Évolutions du chatbot |
| [ia4ops-langgraph-architecture.md](ia4ops-langgraph-architecture.md) | Parcours d'une alerte dans le graphe LangGraph | Comprendre le code de l'agent (daté du 7 octobre 2026) |
| [ia4ops-webhook-contract.md](ia4ops-webhook-contract.md) | Contrat du webhook Alertmanager v4, modèles, déduplication | Réception des alertes |
| [ia4ops-scenario1-reference.md](ia4ops-scenario1-reference.md) | Modèles Pydantic, prompt initial, contrôles post-LLM, principes d'ingénierie, fixtures | Implémentation du domaine et des garde-fous |
| [ia4ops-architecture-reference.md](ia4ops-architecture-reference.md) | Architecture cible, guardrails, requêtes PromQL/LogQL, trade-offs | Questions d'architecture (document conceptuel) |
| [ia4ops-platform-context.md](ia4ops-platform-context.md) | Plateforme GCP/k3s/Flux, observabilité, endpoints, état du raccordement | Infrastructure et dépendances |
| [ia4ops-meeting-notes.md](ia4ops-meeting-notes.md) | Notes des réunions Fabian/Maël (notes générées par IA, à confirmer) | Décisions et responsabilités |

Documents voisins dans le dépôt :

- [`../GUIDE-DIRECTION-ARTISTIQUE-IHM.md`](../GUIDE-DIRECTION-ARTISTIQUE-IHM.md) : charte visuelle de l'IHM Chainlit.
- [`../CLAUDE.md`](../CLAUDE.md) : conventions du dépôt.
- [`../ia4ops-agent/README.md`](../ia4ops-agent/README.md) et [`../ia4ops-agent-chat/README.md`](../ia4ops-agent-chat/README.md) : documentation des deux applications.

## Conventions

- Un fichier par sujet, nommé `ia4ops-<sujet>.md`, rédigé en français.
- Chaque document indique son statut et sa date de dernière mise à jour en tête de fichier.
- Les liens vers d'autres fichiers du dépôt sont relatifs à ce dossier (`../ia4ops-agent/...`).
- Le dépôt est public : aucun secret, mot de passe, clé ou contenu de Secret Kubernetes dans ces documents.
- Quand le code et un document divergent, le code fait foi : corriger le document et noter l'écart
  dans `ia4ops-progress.md`.
