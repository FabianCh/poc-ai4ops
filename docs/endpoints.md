# Endpoints du POC

`<IP>` désigne l'IP publique statique de la VM (`terraform -chdir=infra/gcp-k3s output -raw external_ip`
ou, depuis Cloud Shell, voir [cloudshell.md](cloudshell.md)). Les noms `*.<IP>.sslip.io` résolvent
automatiquement vers cette IP ; tous les endpoints publics sont en HTTPS (certificats Let's Encrypt).

## Endpoints publics (Internet, ports 80/443)

| URL | Service | Authentification |
| --- | --- | --- |
| `https://whoami.<IP>.sslip.io` | Application de démo `demo-whoami` (renvoie les infos de la requête) | Aucune |
| `https://grafana.<IP>.sslip.io` | Grafana : dashboards, Explore (Prometheus, Loki, Jaeger), Alerting | `admin` + mot de passe généré ([récupération](cloudshell.md#mot-de-passe-grafana)) |
| `https://keep.<IP>.sslip.io` | Keep : console d'alertes (historique, déduplication, firing/resolved) | `admin` + mot de passe généré par `make keep-secrets` ([récupération](cloudshell.md#keep-console-dalertes)) |
| `https://otel-demo.<IP>.sslip.io/` | OpenTelemetry Demo : boutique Astronomy Shop | Aucune |
| `https://otel-demo.<IP>.sslip.io/feature` | UI des feature flags flagd : **injection de pannes** | Aucune |
| `https://otel-demo.<IP>.sslip.io/jaeger/ui` | Jaeger : traces de la démo | Aucune |
| `https://otel-demo.<IP>.sslip.io/loadgen` | Locust : générateur de charge (démarrer / arrêter, nombre d'utilisateurs) | Aucune |
| `https://otel-demo.<IP>.sslip.io/grafana` | Redirection vers `https://grafana.<IP>.sslip.io` | — |
| `https://otel-demo.<IP>.sslip.io/chatbot` | Assistant IA de la démo (réponses LLM pré-enregistrées) | Aucune |
| `https://otel-demo.<IP>.sslip.io/opamp` | UI du serveur OpAMP (gestion des collectors) | Aucune |

> Tout ce qui n'a pas d'authentification est accessible à quiconque connaît l'IP, en particulier
> l'injection de pannes (`/feature`). C'est un choix assumé pour le POC.

### API utiles (automatisation, futur agent)

| Méthode / URL | Usage |
| --- | --- |
| `GET https://otel-demo.<IP>.sslip.io/feature/api/read` | Configuration complète des feature flags (JSON) |
| `POST https://otel-demo.<IP>.sslip.io/feature/api/write` | Écrit la configuration des flags. Corps : `{"data": <config complète lue via /api/read>}` |
| `POST https://otel-demo.<IP>.sslip.io/otlp-http/v1/{traces,metrics,logs}` | Récepteur OTLP/HTTP du collector (télémétrie navigateur) |
| `https://grafana.<IP>.sslip.io/api/datasources/proxy/uid/prometheus/api/v1/...` | API Prometheus via Grafana (requêtes, règles : `/rules?type=alert`) |
| `https://grafana.<IP>.sslip.io/api/datasources/proxy/uid/alertmanager/api/v2/alerts` | Alertes actives d'Alertmanager via Grafana |
| `https://grafana.<IP>.sslip.io/api/datasources/proxy/uid/loki/loki/api/v1/query_range` | API Loki via Grafana |

Les appels via Grafana utilisent le même compte (`curl -u admin:<mot de passe> ...`).

Exemple : activer la panne `productCatalogFailure` (la branche « produit ciblé » passe à `on`) :

```bash
D=https://otel-demo.<IP>.sslip.io
curl -s $D/feature/api/read > flags.json                       # sauvegarde
jq '{data: (.flags.productCatalogFailure.targeting.if[1] = "on")}' flags.json \
  | curl -s -X POST -H 'Content-Type: application/json' --data @- $D/feature/api/write
# Restaurer :
jq '{data: .}' flags.json | curl -s -X POST -H 'Content-Type: application/json' --data @- $D/feature/api/write
```

## Endpoints d'administration (non publics)

| Endpoint | Accès |
| --- | --- |
| API Kubernetes `:6443` | Tunnel IAP (`make tunnel`) ou en direct depuis `admin_source_ranges` |
| SSH `:22` | `gcloud compute ssh ... --tunnel-through-iap` (`make ssh`) |

## Services internes au cluster (port-forward)

Non exposés (pas d'authentification) : accès via `kubectl port-forward` (depuis un poste avec
kubeconfig, ou depuis Cloud Shell avec l'aperçu web, voir [cloudshell.md](cloudshell.md#accès-aux-uis-internes)).

| Service | Namespace / Service | Port | Commande |
| --- | --- | --- | --- |
| Prometheus | `monitoring/kube-prometheus-stack-prometheus` | 9090 | `kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090` |
| Alertmanager | `monitoring/kube-prometheus-stack-alertmanager` | 9093 | `kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093` |
| Loki | `monitoring/loki` | 3100 | `kubectl -n monitoring port-forward svc/loki 3100` |
| Jaeger (UI + API) | `otel-demo/jaeger` | 16686 | `kubectl -n otel-demo port-forward svc/jaeger 16686` (UI sous `/jaeger/ui`) |
| OTel Collector | `otel-demo/otel-collector` | 4317 (gRPC), 4318 (HTTP) | `kubectl -n otel-demo port-forward svc/otel-collector 4317 4318` |
| flagd | `otel-demo/flagd` | 8013 (gRPC), 8016 (OFREP) | `kubectl -n otel-demo port-forward svc/flagd 8013 8016` |
| Agent ia4ops (`/api/v1/incidents/{id}`, `/docs`) | `ia4ops/ia4ops-agent` | 8000 | `kubectl -n ia4ops port-forward svc/ia4ops-agent 8000` |
| Keep backend (API, webhook Alertmanager `/alerts/event/prometheus`) | `keep/keep-backend` | 8080 | `kubectl -n keep port-forward svc/keep-backend 8080` |

L'agent `ia4ops-agent` n'accepte en entrée que les webhooks d'Alertmanager : une NetworkPolicy
refuse tout autre trafic vers le namespace `ia4ops`, sauf depuis les pods Alertmanager du
namespace `monitoring` (port 8000). `kubectl port-forward` n'est pas soumis aux NetworkPolicies.

Le backend de Keep n'accepte les webhooks d'Alertmanager qu'avec une clé d'API (rôle `webhook`) et une
NetworkPolicy limite ses entrées à Traefik (interface publique), aux pods Alertmanager du namespace
`monitoring` et aux pods de Keep.

## Outputs Terraform

```bash
terraform -chdir=infra/gcp-k3s output
#   external_ip, ingress_base_domain, demo_url, grafana_url, otel_demo_url, ssh_command, ...
```
