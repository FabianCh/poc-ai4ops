# poc-ai4ops

POC d'**AIOps agentique** : un agent IA capable de détecter, diagnostiquer et
**remédier automatiquement des incidents** sur une plateforme Kubernetes.

## Objectif

1. Disposer d'une plateforme cible simple et reproductible (k3s sur une VM GCP)
   hébergeant des applications exposées sur Internet.
2. Y injecter des incidents (crash loop, OOM, mauvaise config, saturation...).
3. Laisser un agent observer les signaux (événements K8s, métriques, logs),
   poser un diagnostic et appliquer une remédiation, avec garde-fous
   (dry-run, validation humaine, journal d'actions).

## Architecture actuelle

```
                Internet
                   │  HTTP/HTTPS (80/443)      kubectl (6443, IP admin ou tunnel IAP)
                   ▼                                   │
        ┌──────────────────────── GCP ─────────────────┼─────────────┐
        │  IP publique statique  ◄─────────────────────┘             │
        │          │                                                 │
        │  ┌───────▼──────── VM Compute Engine (Ubuntu 24.04) ─────┐  │
        │  │  k3s (single node)                                    │  │
        │  │   ├─ ServiceLB ─► Traefik (Ingress Controller)        │  │
        │  │   ├─ FluxCD ◄── GitOps : manifest/ (branche main)     │  │
        │  │   ├─ cert-manager + ClusterIssuers Let's Encrypt      │  │
        │  │   ├─ monitoring : Prometheus, Alertmanager, Grafana,  │  │
        │  │   │              Loki + Alloy (logs et événements)    │  │
        │  │   └─ applications : demo-whoami, OpenTelemetry Demo   │  │
        │  └───────────────────────────────────────────────────────┘  │
        │  VPC dédié · firewall 80/443 public · 22/6443 IAP/admin      │
        └──────────────────────────────────────────────────────────────┘
```

Un seul `terraform apply` suffit : la VM installe k3s puis **FluxCD**, qui
déploie tout le contenu du cluster depuis le dossier [`manifest/`](manifest/)
de la branche `main` (même organisation que le projet home-server). Le repo est
public, Flux le lit en HTTPS sans aucun secret. Les applications sont exposées
via un `Ingress` Traefik. Sans nom de domaine,
on utilise le DNS wildcard [sslip.io](https://sslip.io) :
`<app>.<IP_PUBLIQUE>.sslip.io` résout vers la VM, et cert-manager obtient un
certificat Let's Encrypt automatiquement.

## Structure du repo

| Chemin | Contenu |
| --- | --- |
| [`infra/gcp-k3s/`](infra/gcp-k3s/) | Terraform : réseau, firewall, IP statique, VM + bootstrap k3s |
| [`manifest/flux-system/`](manifest/flux-system/) | Bootstrap FluxCD et Kustomizations Flux (`base/`, `applications/`) |
| [`manifest/base/`](manifest/base/) | Socle : cert-manager, ClusterIssuers Let's Encrypt, observabilité (kube-prometheus-stack, Loki, Alloy) |
| [`manifest/applications/`](manifest/applications/) | Applications : `demo-whoami`, `otel-demo` (OpenTelemetry Demo) |
| [`bin/`](bin/) | Kubeconfig, upgrade Flux, validation des manifests |
| `Makefile` | Raccourcis (`make help`) |

## Tester le POC

### Prérequis

- `terraform` >= 1.5
- `gcloud` authentifié : `gcloud auth login` **et** `gcloud auth application-default login`
- un projet GCP avec la facturation activée et les APIs Compute Engine et IAP activées :
  `gcloud services enable compute.googleapis.com iap.googleapis.com --project <PROJECT_ID>`
- optionnel : `kubectl` et `flux` pour inspecter le cluster

### 1. Configurer

```bash
cp infra/gcp-k3s/terraform.tfvars.example infra/gcp-k3s/terraform.tfvars
# renseigner project_id
# optionnel : admin_source_ranges = ["<votre IP>/32"]  (curl -s https://ifconfig.me)
#             pour joindre l'API Kubernetes sans tunnel IAP
```

### 2. Déployer

```bash
make init
make plan           # vérifier les ressources créées
make apply
make logs           # suivre le bootstrap de la VM (~3-5 min),
                    # attendre "=== Bootstrap terminé ===" puis Ctrl+C
```

### 3. Vérifier l'application de démo

Flux déploie cert-manager, les ClusterIssuers puis `demo-whoami` quelques
minutes après le bootstrap :

```bash
curl "$(terraform -chdir=infra/gcp-k3s output -raw demo_url)"
```

Le certificat Let's Encrypt peut mettre 1 à 2 minutes à être émis : en
attendant, `http://` ou `curl -k` fonctionnent.

### 4. Inspecter le cluster (optionnel)

```bash
make kubeconfig     # si admin_source_ranges est renseigné
# sinon : make kubeconfig-iap, puis `make tunnel` dans un autre terminal
export KUBECONFIG=$PWD/.kube/config

kubectl get nodes
make flux-status    # cert-manager → cluster-issuers → demo-whoami : Ready
kubectl -n demo-whoami get pods,ingress,certificate
```

### 5. Observabilité

Namespace `monitoring`, déployé par Flux après cert-manager :

| Composant | Rôle |
| --- | --- |
| Prometheus + Alertmanager (kube-prometheus-stack) | Métriques du cluster, règles d'alerte par défaut, rétention 7 jours |
| Grafana | Dashboards Kubernetes, datasources Prometheus et Loki |
| Loki | Stockage des logs, rétention 7 jours |
| Alloy | Collecte des logs de tous les pods et des événements Kubernetes vers Loki |

```bash
terraform -chdir=infra/gcp-k3s output -raw grafana_url    # https://grafana.<IP>.sslip.io
# Utilisateur : admin, mot de passe généré aléatoirement à l'installation :
kubectl -n monitoring get secret kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo

# Prometheus et Alertmanager ne sont pas exposés (pas d'authentification) :
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090    # http://localhost:9090
kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093  # http://localhost:9093
```

Dans Grafana > Explore > Loki :
- `{namespace="demo-whoami"}` : logs de l'application de démo ;
- `{job="kubernetes-events"}` : événements Kubernetes (BackOff, OOMKilled…).

### 6. OpenTelemetry Demo

L'[OpenTelemetry Demo](https://opentelemetry.io/docs/demo/) (Astronomy Shop)
est déployée dans le namespace `otel-demo` : une quinzaine de microservices
instrumentés en OpenTelemetry, un générateur de charge permanent (Locust) et des
feature flags pour **injecter des pannes**. Sa télémétrie alimente la stack du
cluster :

| Signal | Destination | Où le voir |
| --- | --- | --- |
| Traces | Jaeger (fourni par la démo) | `/jaeger/ui` ou Grafana > Explore > Jaeger |
| Métriques | Prometheus (récepteur OTLP) | Grafana > Explore > Prometheus, ex : `sum by (service_name) (rate(traces_span_metrics_calls_total[5m]))` |
| Logs | Loki (OTLP) | Grafana > Explore > Loki, ex : `{service_name="cart"}` |

```bash
terraform -chdir=infra/gcp-k3s output -raw otel_demo_url    # https://otel-demo.<IP>.sslip.io
```

| URL | Contenu |
| --- | --- |
| `/` | Boutique |
| `/feature` | Feature flags flagd : injection de pannes |
| `/jaeger/ui` | Traces |
| `/loadgen` | Générateur de charge Locust |
| `/grafana` | Redirection vers le Grafana du cluster (`grafana.<IP>.sslip.io`) |

Les dashboards de la démo (Demo, APM, Spanmetrics, Exemplars, OpenTelemetry
Collector…) sont importés dans le Grafana du cluster, dossier
**OpenTelemetry Demo**. Les panneaux de logs de ces dashboards restent vides :
ils interrogent OpenSearch, remplacé ici par Loki (utiliser Explore > Loki).

Exemples de pannes activables dans `/feature` : `productCatalogFailure`,
`cartFailure`, `paymentFailure`, `adHighCpu`, `adManualGc`,
`recommendationCacheFailure` (fuite mémoire), `kafkaQueueProblems`,
`imageSlowLoad`. Ces pannes
serviront de scénarios d'incidents pour l'agent.

> L'URL est publique : n'importe qui la connaissant peut activer une panne.

### 7. Tester le GitOps

1. Passer `replicas: 2` à `3` dans
   `manifest/applications/demo-whoami/demo-whoami-deployment.yaml`.
2. Commit + push sur `main`.
3. `make flux-reconcile` (ou attendre ~1 min), puis
   `kubectl -n demo-whoami get pods` : 3 pods.

### 8. Nettoyer

```bash
make destroy
```

### Dépannage

| Symptôme | Diagnostic |
| --- | --- |
| Le bootstrap ne se termine pas | `make ssh` puis `sudo cat /var/log/k3s-bootstrap.log` |
| Flux ne synchronise pas | `kubectl -n flux-system get gitrepository,kustomization` |
| Stack monitoring absente | `flux get helmreleases -n monitoring` ; `kubectl -n monitoring get pods` |
| Pas de certificat HTTPS | `kubectl -n demo-whoami describe certificate` ; en cas de rate limit Let's Encrypt sur sslip.io, passer l'annotation de l'Ingress à `letsencrypt-staging` |

> **Coût** : la VM `e2-standard-4` tourne en continu. Pour réduire la
> facture : `spot = true` dans `terraform.tfvars`, ou `make destroy` après
> chaque session de test.

Détails : [`infra/gcp-k3s/README.md`](infra/gcp-k3s/README.md) (infra) et
[`manifest/flux-system/README.md`](manifest/flux-system/README.md) (GitOps).

## Ajouter une application

1. `manifest/applications/<app>/` : `kustomization.yaml` + un fichier par ressource
   (`<app>-namespace.yaml`, `<app>-deployment.yaml`, `<app>-ingress.yaml`...).
2. `manifest/flux-system/applications/<app>-ks.yaml` (copier `demo-whoami-ks.yaml`)
   et l'ajouter dans `manifest/flux-system/applications/kustomization.yaml`.
3. `make lint`, commit, push sur `main` : Flux déploie (≤ 1 min).

> Le repo étant public, ne jamais y committer de secret : seule la clé GCP
> (credentials `gcloud`, jamais dans le repo) est sensible dans ce POC.

## Feuille de route

- [x] Initialisation du repo
- [x] Plateforme : VM GCP + k3s + exposition Internet (Traefik, TLS Let's Encrypt)
- [x] GitOps : déploiement via FluxCD (`manifest/`), installé automatiquement
- [x] Observabilité : Prometheus / Alertmanager / Grafana, Loki (logs + événements Kubernetes)
- [x] Application cible : OpenTelemetry Demo, avec pannes injectables par feature flags
- [ ] Scénarios d'incidents reproductibles (catalogue, déclenchement automatisé)
- [ ] Agent de diagnostic (LLM + outils K8s en lecture seule)
- [ ] Remédiation automatique avec garde-fous (dry-run, approbation, audit)
