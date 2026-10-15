# Providers réels Prometheus et Loki

Les providers interrogent les datasources par le proxy Grafana :

- Prometheus : `/api/datasources/proxy/uid/prometheus/api/v1/query`
- Loki : `/api/datasources/proxy/uid/loki/loki/api/v1/query_range`

Configuration requise :

```dotenv
DATA_PROVIDER=real
GRAFANA_BASE_URL=https://grafana.<IP>.sslip.io
GRAFANA_USERNAME=admin
GRAFANA_PASSWORD=<secret hors du dépôt>
```

Le mot de passe ne doit pas être commité. En cluster, il doit être fourni par un Secret
Kubernetes ; vérifier que la NetworkPolicy/egress permet au pod de joindre Grafana avant de
sélectionner `DATA_PROVIDER=real`.

## Prometheus

`PrometheusProvider` utilise le label observé `service_name` et les métriques spanmetrics
confirmées pour `product-catalog` :

- `traces_span_metrics_calls_total`, filtrée sur `span_kind="SPAN_KIND_SERVER"` et
  `status_code="STATUS_CODE_ERROR"` pour calculer le taux d'erreur ;
- `traces_span_metrics_calls_total` pour calculer le débit de requêtes ;
- `traces_span_metrics_duration_milliseconds_bucket` pour calculer le p95 en millisecondes.

Les requêtes spanmetrics utilisent la fenêtre passée à `get_service_metrics` (15 minutes par défaut).
La règle d'alerte utilise une fenêtre de 5 minutes ; le provider ne prétend donc pas reproduire
exactement son seuil temporel.

Les métriques de **conteneur** (cAdvisor + kube-state-metrics, le conteneur porte le nom du
service) reprennent la granularité des règles `otel-demo.containers` :

- `memory_ratio` : usage / limite mémoire calculé **pod par pod** (`on(namespace, pod, container)`),
  puis pire pod du service ; `memory_working_set_mb` et `memory_limit_mb` en valeurs brutes ;
- `cpu_cores` : cœurs consommés (fenêtre 5 min). `cpu_ratio` n'est renseigné que s'il existe une
  limite CPU, ce qui n'est pas le cas dans l'OTel Demo ;
- `restarts_10m` et `oom_killed` (redémarrage sur 10 min **et** dernière terminaison `OOMKilled`,
  comme `OtelDemoContainerOOMKilled`).

Les deux familles sont indépendantes : une requête en échec n'annule pas les autres et figure dans
`failed` (reprise dans `missing_information`). Statut : `success` si les deux familles sont
complètes, `partial` si une famille ou une requête manque (ex. `load-generator`, sans spanmetrics),
`MetricsUnavailableError` seulement si aucune métrique n'est obtenue.

## Loki

`LokiProvider` recherche les logs sur la fenêtre demandée avec les labels observés
`service_name`, `k8s_namespace_name` et `detected_level`. Il conserve les niveaux ERROR,
FATAL, CRITICAL et WARN/WARNING. Les lignes sont normalisées en événements (`event_id`,
`timestamp`, `level`, `message`, `service`) et plafonnées au `limit` demandé.

Le sélecteur Loki utilise `k8s_namespace_name="otel-demo"` ; le label `namespace` ne
correspondait à aucun stream dans l'instance inspectée. `service_namespace` existe aussi, mais
sa valeur observée est `opentelemetry-demo`, différente du namespace Kubernetes. L'absence de
logs d'erreur concordants retourne une liste vide et ne fait pas échouer la requête.

Les streams inspectés après l'incident étaient des logs INFO ; l'observation de l'utilisateur
n'a pas montré d'évolution de Loki pendant l'injection. Il reste à vérifier si les erreurs de
cette panne sont émises dans un autre service ou une autre source.

## Limites

- Les valeurs de `service_name` doivent correspondre aux noms reçus dans les alertes. Pour
  `product-catalog`, cette correspondance a été confirmée dans Prometheus et Loki.
- La sélection Prometheus ne filtre pas sur le namespace, car la règle spanmetrics de la
  plateforme utilise `service_name` sans matcher namespace.
- Le `KubernetesProvider` n'est pas implémenté et signale la source comme indisponible.
  `DATA_PROVIDER=real` utilise donc Prometheus et Loki réels sans injecter de données
  Kubernetes simulées.
