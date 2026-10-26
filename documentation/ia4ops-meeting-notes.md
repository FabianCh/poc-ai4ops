# IA4Ops — Notes de réunion

> **Date** : octobre 2026  
> **Participants** : Fabian Chauvin (infrastructure/plateforme), Maël Mitchel (agent IA)  
> **Statut** : compte rendu historique ; complété par la réunion du 7 octobre 2026

> **Note** : ce document est un compte rendu historique de la réunion, pas l'état courant du
> projet. Les décisions et points de suivi ont évolué depuis ; consulter `ia4ops-progress.md`
> et `ia4ops-platform-context.md` pour l'état courant.

---

## Résumé exécutif

Fabian a présenté à Maël la plateforme complète déployée sur GCP : infrastructure Terraform, cluster Kubernetes, stack d'observabilité (Grafana/Prometheus/Loki), et application de démonstration OTel. Les deux équipes ont aligné les prochaines étapes : Maël démarre l'implémentation de l'agent avec des mocks, Fabian prépare l'observabilité et le format du webhook pour permettre l'intégration.

---

## 1. Architecture de la plateforme (Fabian)

### Infrastructure

- Projet **Terraform sur GCP** : crée une VM Google Compute Engine, installe Kubernetes (K3s ou similaire), déploie la plateforme complète de manière reproductible
- Les outputs Terraform sont utilisés par les scripts de connexion et de tunnel (`make tunnel`)
- Les états Terraform ne sont pas publiés dans le dépôt principal — Maël doit solliciter Fabian si des opérations Terraform sont nécessaires

### Accès aux services

- Les endpoints publics sont documentés dans le projet Fabian
- DNS géré via **No-IP** (URL publiques associées à l'IP externe de la VM) — pas de DNS dédié
- Connexion au cluster : `make tunnel` (dépend des outputs Terraform et de la présence de Terraform dans l'environnement)
- **Cloud Shell GCP** recommandé comme moyen le plus simple d'interagir avec le cluster

### Application de démonstration

- **Mini-marketplace** : ajout d'événements au panier, achat
- Onglet dédié pour **créer des incidents** : déclarer certains services indisponibles via feature flags
- Application basée sur **OpenTelemetry Demo** (microservices : `product-catalog`, `checkout`, `frontend`, etc.)
- Namespace Kubernetes : `otel-demo`

---

## 2. Observabilité (Fabian)

### Stack déployée

| Composant | Rôle |
|---|---|
| **Prometheus** | Métriques (gauges, histogrammes, compteurs) — requêtes PromQL |
| **Loki** | Logs applicatifs — requêtes LogQL |
| **Grafana** | Agrégateur UI — tableaux de bord Kubernetes et OTel |
| **Alertmanager** | Gestion des alertes Prometheus et Loki — envoi de webhooks |
| **Traces (Jaeger/Tempo)** | Non encore opérationnel — hors périmètre scénario 1 |

### Labels et métriques

- Les métriques utilisent des **labels en paires clé-valeur** pour filtrer par service ou domaine
- Exemple : filtrer les applications indisponibles dans le périmètre paiement
- Les noms exacts des labels OTel (`service_name`, `service`, etc.) sont à confirmer avec Fabian

### État actuel

- Plusieurs tableaux de bord Grafana affichent des données, mais **certaines données sont absentes ou incorrectes**
- La partie **alerting apparaît en erreur** dans Grafana
- Fabian prévoit de **corriger la stack d'observabilité** avant la fin de la journée de réunion

### Alerting

- Alertes **Prometheus** : basées sur les métriques
- Alertes **Loki** : basées sur des patterns dans les logs
- Alertes **Grafana** : peuvent s'appuyer sur les deux sources
- Notifications via **webhook** vers l'agent de Maël

---

## 3. Agent IA et intégration (décisions communes)

### Répartition du travail

| Maël | Fabian |
|---|---|
| Récupérer le code de Fabian | Corriger l'observabilité et l'alerting |
| Ajouter structure agentique avec mocks | Fournir le format exact du webhook |
| Itérer selon les données Grafana | Configurer l'envoi du webhook depuis Alertmanager |
| Préparer Dockerfile et manifeste K8s | Donner accès aux éléments MCP |
| Transmettre les avancées au fur et à mesure | Fournir endpoints et accès |

### Format du webhook

- **Alertmanager v4** — format standard documenté
- Une notification = **un groupe d'alertes** (groupement par `namespace`)
- L'agent doit être **idempotent** : clé de déduplication = `fingerprint` + `startsAt`
- Alertmanager **réessaie** si pas de réponse 2xx rapide → traitement **asynchrone obligatoire**
- `send_resolved: true` : l'agent reçoit aussi la résolution de l'alerte
- Voir `ia4ops-webhook-contract.md` pour le schéma complet

### Intégration Grafana

- L'agent consommera directement les informations de Grafana : métriques, logs, alertes
- L'objectif est l'analyse automatisée des incidents

### Déploiement de l'agent

- **Image Docker** à construire (Dockerfile)
- **CI/CD** à prévoir
- **Manifeste Kubernetes** à ajouter dans le dépôt de Fabian (conventions GitOps Flux)
- Une fois le manifeste dans le dépôt prévu, le déploiement vers l'environnement est automatisé

---

## 4. Accès et environnements

### Comptes utilisateurs

- Fabian utilise actuellement un **compte personnel** pour le dépôt GitHub
- Maël envisage également un compte personnel
- À vérifier avec les équipes du Lab : rapatriement des accès GitHub et GCP vers les comptes professionnels

### Accès Kiro

- Maël n'a pas encore reçu d'accès à Kiro
- Action : relancer le groupe concerné

### Usage de Gemini

- Maël a signalé une **information peu claire** concernant un éventuel usage non facturé de Gemini
- Décision : **ne pas activer Gemini** tant que les conditions ne sont pas comprises
- Impact sur le plan : Task 6 (branchement LLM réel) est bloquée jusqu'à clarification

---

## 5. Follow-up tasks

| Responsable | Action | Priorité |
|---|---|---|
| **Fabian** | Réparer les problèmes de données et d'alerting dans Grafana | Haute — bloquant pour l'intégration |
| **Fabian** | Fournir le format du webhook et configurer son envoi depuis Alertmanager | Haute — bloquant pour Task 5 réelle |
| **Fabian** | Donner accès aux éléments MCP et documenter les endpoints | Haute — bloquant pour Task 8 |
| **Fabian** | Publier ou fournir les états Terraform si modification infra nécessaire | Normale |
| **Maël** | Récupérer le code de Fabian, ajouter la structure agentique avec mocks | Haute — démarrage immédiat |
| **Maël** | Préparer Dockerfile, manifeste Kubernetes, pipeline CI/CD | Normale — Task 8 |
| **Maël** | Vérifier avec le Lab le rapatriement des accès GitHub et GCP | Normale |
| **Maël** | Relancer la demande d'accès à Kiro | Normale |
| **Maël** | Clarifier les conditions d'usage de Gemini avant d'activer Task 6 | Haute — bloquant Task 6 |
| **Les deux** | Se recontacter dans l'après-midi si nécessaire | — |

---

## 6. Décisions prises lors de la réunion

1. **Mode asynchrone** : imposé par le comportement d'Alertmanager — répondre 2xx immédiatement, traiter en arrière-plan. Remplace le mode synchrone initialement prévu.
2. **Services OTel** : les fixtures de raccordement utiliseront les vrais noms OTel (`product-catalog`, `checkout`, `frontend`) ; les fixtures de développement local restent génériques.
3. **Namespace** : `otel-demo` confirmé.
4. **Cloud Shell** : accès recommandé pour interagir avec le cluster GCP.
5. **GitOps Flux** : les manifestes de l'agent suivront les conventions du dépôt de Fabian.

---

*Notes de réunion — IA4Ops — octobre 2026*

---

## Complément — réunion Fabian/Maël du 7 octobre 2026

> Notes fournies par Maël, générées par IA et à vérifier pour les formulations ambiguës.
> Ne pas y ajouter de valeurs de secrets, tokens ou credentials.

### État et décisions rapportés

- Maël a désormais accès au cluster via les autorisations fournies par Joseph ; il a réussi
  `kubectl get nodes`. L'accès technique à la session Cloud Shell est donc débloqué.
- Un Secret destiné à l'accès au modèle (Vertex AI / Model Garden) aurait été créé dans le
  cluster. Son nom, sa structure, son montage dans le Deployment et le succès d'un appel
  Vertex AI depuis le pod restent à confirmer.
- Les traces JSON de l'agent sont écrites sur stdout du conteneur ; le chemin prévu est
  `stdout → collecte Alloy → Loki → Grafana Explore`. Le test de cette chaîne en cluster
  reste à effectuer.
- Keep est retenu comme interface de démonstration et de pilotage ; l'agent fournit une
  pré-analyse et des propositions à l'opérateur. Le premier scénario reste supervisé et sans
  exécution d'action.
- Le dépôt route déjà les alertes depuis Alertmanager vers Keep et l'agent en parallèle
  (pour `otel-demo`). Le retour du diagnostic de l'agent dans l'incident Keep reste à construire.
- Pour le premier périmètre, ne pas ajouter les logs et événements Kubernetes aux données
  consommées par l'agent. Priorité aux métriques Prometheus et aux logs applicatifs Loki.
- Les fonctions avancées Keep (workflows, déduplication/corrélation personnalisée) et toute
  remédiation sont différées ; éviter un frontend dédié pour cette première démo.
- Priorité immédiate : valider le fonctionnement, la remontée des traces et une première
  démonstration avec Fabian, Brendan et Fabrice ; stabiliser l'exploitation ensuite.

### Questions/actions ouvertes

| Sujet | Action |
|---|---|
| Prometheus | Confirmer les noms réels des services et labels (`service_name`), les requêtes métriques utiles et la disponibilité CPU/mémoire |
| Loki | Confirmer le sélecteur LogQL, les labels disponibles et la façon d'identifier les logs applicatifs en erreur |
| Traces | Vérifier qu'un événement stdout de l'agent est visible dans Loki puis Grafana Explore, filtré par `incident_id` |
| Secret Vertex AI | Vérifier localement nom/namespace/référence au pod et faire un appel de test ; ne jamais afficher ou transmettre le credential |
| Keep | Choisir l'API/canal et le format pour publier la pré-analyse dans l'incident (Activity/chat ou autre) |
| Démo | Préparer un scénario firing, montrer le rapport dans Keep, puis définir comment la résolution est répercutée sans relancer un diagnostic |
| Stabilisation | Réduire les étapes manuelles de configuration et de déclenchement après la première preview |

La commande `make get-secrets` peut imprimer des identifiants d'administration dans le terminal
de l'opérateur. Les valeurs doivent rester dans cet environnement et ne pas être collées dans
le dépôt, les notes, ni une conversation avec une IA. Pour effectuer des vérifications,
partager plutôt les résultats expurgés (noms de labels, statuts HTTP, noms de ressources).

*Complément de réunion — IA4Ops — 7 octobre 2026*

### Vérification de la proposition d'architecture Keep (analyse Claude transmise après réunion)

Les éléments ci-dessous distinguent la configuration visible dans le dépôt des affirmations
sur Keep rapportées par Claude. Le dépôt ne contient pas le code source Keep ; son chart
configure actuellement la version `0.1.97`. Vérifier les API et comportements sur cette version
avant d'implémenter les appels.

**Faits vérifiés dans le dépôt**

- Alertmanager route les notifications vers Keep et, pour `otel-demo`, poursuit vers l'agent
  (`continue: true`). Keep a `group_interval: 1m` ; l'agent hérite de `5m` défini sur la route
  parente. La différence de cadence est certaine dans les manifests ; l'effet exact sur l'heure
  de réception de `resolved` reste à confirmer par des observations de notifications.
- L'agent reçoit le fingerprint et déduplique les notifications selon les fingerprints triés
  et le `startsAt` minimal. Le statut (`firing`/`resolved`) n'entre pas dans cette clé.
- L'agent n'a pas de client Keep sortant ni de logique de corrélation avec un incident Keep.
  Il ne faut donc pas présenter l'enrichissement, les commentaires ou la clôture Keep comme
  déjà opérationnels.
- La route webhook n'a pas de branche de clôture pour `resolved`. Avec la même clé composite,
  une résolution peut être supprimée comme doublon tant que l'entrée firing est en cache ;
  elle ne déclenche pas forcément un nouveau diagnostic. La correction devra gérer `resolved`
  avant ce chemin de déduplication.
- La NetworkPolicy Keep ne permet pas actuellement au pod `ia4ops-agent` d'entrer vers le
  backend. Il faudra ajouter cette autorisation pour agent → Keep. La politique de l'agent
  ne permet en entrée que le webhook Alertmanager ; un déclenchement Keep → agent nécessiterait
  aussi une règle dédiée. La politique agent ne restreint pas actuellement l'egress ; une
  restriction de sortie ciblée serait un durcissement supplémentaire, pas un prérequis actuel.
- Le script `make create-keep-secrets` prépare actuellement l'authentification Keep et la clé
  utilisée par Alertmanager. Une clé agent séparée n'est pas démontrée comme configurée.

**Pistes Claude à confirmer avant réalisation**

- Endpoints de publication (`POST /alerts/enrich`, commentaire `POST /incidents/{id}/comment`),
  leur schéma et leur compatibilité avec Keep `0.1.97`.
- Déduplication Keep par fingerprint, association automatique alerte → incident et rôle API
  `webhook` avec permissions `write:alert`/`write:incident`.
- Support et format de plusieurs clés dans `KEEP_DEFAULT_API_KEYS`, et ajout d'une clé agent
  à privilèges minimaux sans réutiliser la clé Alertmanager.
- Réception du `resolved` par Keep, son effet sur le statut de l'alerte/incident et la façon de
  retrouver l'incident à clôturer.

**Séquençage prudent proposé**

1. Premier incrément : publier une pré-analyse dans Keep en best-effort (délai court, erreurs
   visibles dans les traces, sans bloquer le diagnostic), après confirmation de l'API et du
   réseau. Pas d'action automatique.
2. Corriger le cycle `resolved` et persister/corréler le lien fingerprint ↔ incident avant de
   considérer le cycle d'incident complet.
3. Implémenter les providers de lecture Prometheus et Loki, puis valider les preuves remontées.
   L'accès aux statuts Kubernetes reste à distinguer de l'ajout des logs/événements Kubernetes,
   explicitement différés pour le premier périmètre.
4. Reporter workflows d'approbation, exécution, dry-run et rollback à une phase ultérieure,
   avec validation humaine et contrôles de sécurité explicitement définis.
