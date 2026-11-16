# IA4Ops — Stack d'observabilité : contenu disponible et pistes d'enrichissement de l'agent

> **Statut** : relevé effectué le 16 novembre 2026 ; pistes **à prioriser** (aucune n'est implémentée).
> **Dernière mise à jour** : 16 novembre 2026.
> **Méthode** : interrogation en **lecture seule** de Prometheus, Loki, Jaeger et Alertmanager via le proxy
> de datasources de Grafana (les mêmes appels que ceux de l'agent). Aucune écriture, aucun changement de
> configuration. Les chiffres sont des ordres de grandeur du jour (ils varient avec la charge et les flags).
> **Limite** : relevé depuis le cluster en marche, pas depuis le dépôt ; quand le dépôt et le cluster divergent,
> vérifier dans `manifest/` (le code et les manifests font foi).

Documents liés : [`ia4ops-platform-context.md`](ia4ops-platform-context.md) (plateforme et observabilité),
[`ia4ops-cadrage.md`](ia4ops-cadrage.md) (agent N0), [`ia4ops-progress.md`](ia4ops-progress.md) (journal).

## 1. Ce que contient la stack

| Source | Contenu relevé | Rétention |
| --- | --- | --- |
| **Prometheus** (`prometheus`) | ~3 200 métriques : nœud (`node_*`), conteneurs cAdvisor (`container_*`, dont `container_oom_events_total` et le throttling CPU), kube-state-metrics (~200 familles : pods, deployments, replicasets, jobs, quotas, volumes), spanmetrics OTel (`traces_span_metrics_*`, 18 services), métriques HTTP/RPC, Kafka (~110), PostgreSQL, Redis/Valkey, runtimes JVM, .NET et Python, évaluations de flags (`feature_flag_evaluation_*`) | 7 jours, 9 Go max |
| **Alertes** | 141 règles, dont celles du projet : `OtelDemoServiceHighErrorRate`, `…HighLatency`, `…FrontendNoTraffic`, `…KafkaConsumerLag`, `OtelDemoContainerHighCpu`, `…MemoryNearLimit`, `…OOMKilled`, `NodeCPUHighUsage`, `NodeSystemSaturation` | – |
| **Loki** | Logs de pods d'`otel-demo` via Alloy (`job=kubernetes-pods`, ~60 000 lignes par heure) ; logs OTLP de la démo (`service_name`, `k8s_*`, niveau `INFO`/`error`) ; **événements Kubernetes** (`job=kubernetes-events`, dont les événements Flux) ; 42 `service_name` | 7 jours |
| **Jaeger** (datasource `webstore-traces`) | 19 services ; traces en erreur filtrables par tag `error=true` | **en mémoire** (`MEMORY_MAX_TRACES`) : perdues au redémarrage |

Constats utiles :

- Les événements Kubernetes sont **déjà dans Loki** (les événements Flux représentent l'essentiel : environ 1 900 par jour
  dans `flux-system`, une vingtaine dans `otel-demo`). Les événements `Warning` observés sur 24 h sont des `Unhealthy` de sondes.
- Près de 60 % des logs d'`otel-demo` ont un niveau `unknown` ; la recherche d'erreurs doit donc s'appuyer sur le contenu.
- Deux chemins de logs coexistent (pods via Alloy, labels `namespace`/`pod`/`container` ; OTLP, labels `k8s_*`) ;
  `service_name` est présent sur les deux et sert de clé commune.

## 2. Ce que les agents consomment aujourd'hui

| Source | Utilisation | Où |
| --- | --- | --- |
| Prometheus | spanmetrics (erreurs, débit, latence p95) et métriques de conteneur (ratio mémoire pod par pod, CPU, redémarrages, OOM) | `ia4ops-agent/src/ia4ops_agent/providers/real/prometheus.py` |
| Jaeger | traces en erreur (liste blanche de champs, chaîne de services, 3 identifiants de trace) | `providers/real/jaeger.py` |
| Loki | logs de pods par niveau, par contenu et par `trace_id` | `providers/real/loki.py` |
| API Kubernetes | pods, réplicas, raisons d'attente/terminaison, événements `Warning` (lecture seule, `otel-demo`) | `providers/real/kubernetes.py` |

La source de preuve `changes` existe dans le schéma du diagnostic (`Evidence.source`) mais **aucun provider ne l'alimente**.

## 3. Pistes d'enrichissement

Légende de l'effort : **S** = requête ou petit provider, sans nouveau droit ; **M** = nouveau provider ou nœud du graphe ;
**C** = changement de configuration de la plateforme (manifests, Flux).

### 3.1 Disponible dans la stack mais non exploité

| # | Piste | Valeur pour l'agent | Effort |
| --- | --- | --- | --- |
| 1 | **Changements récents** : réconciliations et mises à jour Flux (événements dans Loki), nouveaux ReplicaSets (`kube_replicaset_created`), génération des deployments | Répondre à « qu'est-ce qui a changé juste avant l'incident ? » ; alimente enfin la source `changes` | M |
| 2 | **Événements Kubernetes historiques** (Loki, 7 jours) en complément de l'API (environ 1 h) | Incidents plus anciens que la fenêtre de l'API, redémarrages passés | S |
| 3 | **Dépendances** : Kafka (lag, débit), PostgreSQL (connexions, verrous), Valkey/Redis, pools `db_client_*` | Distinguer une panne locale d'une cause en aval, aujourd'hui visible uniquement par les traces | S |
| 4 | **Saturation** : `container_cpu_cfs_throttled_*`, état et pression du nœud (`node_*`, `kube_node_status_condition`) | Expliquer lenteurs et erreurs par un CPU bridé ou un nœud saturé (alertes de nœud déjà actives en cas de `adHighCpu`) | S |
| 5 | **Flags évalués** : `feature_flag_evaluation_*` | Repérer un flag actif ou en erreur (utile hors périmètre des scénarios à flag, écartés par le cadrage N0) | S |

### 3.2 Absent de la stack (changement de configuration)

| # | Piste | Valeur pour l'agent | Effort |
| --- | --- | --- | --- |
| 6 | **Métriques Flux** (`gotk_*`) : aucune n'est collectée | Observer suspension, dérive et échecs de réconciliation ; **prérequis du scénario N0 proposé** (suspension Flux puis suppression d'une ressource) | C |
| 7 | **Labels de pods** : `kube_pod_labels` est vide (labels non autorisés dans kube-state-metrics) | Relier proprement pod, application et version | C |
| 8 | **Trafic d'entrée et serveur de flags** : aucune métrique Traefik ni flagd | Voir l'état du point d'entrée et des évaluations de flags | C |
| 9 | **HPA** : aucune métrique | Sans objet tant qu'il n'y a pas d'autoscaling | – |

### 3.3 Qualité des données

| # | Constat | Piste | Effort |
| --- | --- | --- | --- |
| 10 | ~60 % des logs d'`otel-demo` en niveau `unknown` | Extraire le niveau dans Alloy (parsing) pour filtrer sur un vrai niveau | C |
| 11 | Deux chemins de logs aux labels différents | Documenter la correspondance ou normaliser les labels ; `service_name` reste la clé commune | C |
| 12 | Jaeger en mémoire : traces perdues au redémarrage et au-delà d'un plafond | Stockage persistant (Badger) si l'on veut diagnostiquer des incidents de plus de quelques minutes | C |
| 13 | Deux datasources Prometheus (`prometheus` et `webstore-metrics`) | Clarifier leur rôle respectif avant de s'appuyer sur la seconde | – |
| 14 | Pas de runbooks ni d'inventaire des services (rôle, responsable) | Renseigner `runbook_url` dans les règles du projet et fournir une courte fiche par service | M |

## 4. Ordre recommandé

1. **Piste 1 (+ 2)** : un provider « changes » alimenté par Loki (événements Flux et Kubernetes) et par les ReplicaSets
   de kube-state-metrics. Aucun nouveau droit, la source `changes` est déjà prévue dans le schéma.
2. **Pistes 3, 4 et 5** : de simples requêtes Prometheus ajoutées au provider de métriques, avec les mêmes garde-fous
   (bornes de taille, résultats partiels, contenu externe non fiable).
3. **Pistes 6 et 7** : petites modifications de configuration (collecte Flux, labels de kube-state-metrics),
   à planifier avec le scénario N0 si celui-ci retient la suspension de Flux.
4. **Pistes 10, 12 et 14** : qualité des données, selon le temps disponible.

Toute piste qui ajoute une source doit : rester **non bloquante** (statut `unavailable` et ligne dans `missing_information`),
borner la taille du contexte, traiter son contenu comme **non fiable** (règle 5 du prompt) et ne demander aucun droit d'écriture.

## 5. Points non vérifiés

- Rôle exact de la datasource `webstore-metrics` (piste 13).
- Présence d'un `runbook_url` dans les règles d'alerte du projet (piste 14).
- Plafond réel de traces conservées par Jaeger (`MEMORY_MAX_TRACES`) et durée effective de conservation (piste 12).
- Cause des alertes `NodeCPUHighUsage` et `NodeSystemSaturation` au moment du relevé : probablement le flag `adHighCpu`, non confirmé.
