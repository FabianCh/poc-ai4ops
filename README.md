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
        │  │   ├─ cert-manager + ClusterIssuers Let's Encrypt      │  │
        │  │   └─ applications (ex : demo/whoami)                  │  │
        │  └───────────────────────────────────────────────────────┘  │
        │  VPC dédié · firewall 80/443 public · 22/6443 IAP/admin      │
        └──────────────────────────────────────────────────────────────┘
```

Les applications sont exposées via un `Ingress` Traefik. Sans nom de domaine,
on utilise le DNS wildcard [sslip.io](https://sslip.io) :
`<app>.<IP_PUBLIQUE>.sslip.io` résout vers la VM, et cert-manager obtient un
certificat Let's Encrypt automatiquement.

## Structure du repo

| Chemin | Contenu |
| --- | --- |
| [`infra/gcp-k3s/`](infra/gcp-k3s/) | Terraform : réseau, firewall, IP statique, VM + bootstrap k3s / cert-manager |
| [`apps/demo-whoami/`](apps/demo-whoami/) | Application de démo exposée sur Internet |
| [`scripts/`](scripts/) | Récupération du kubeconfig, déploiement de la démo |
| `Makefile` | Raccourcis (`make help`) |

## Démarrage rapide

Prérequis : `terraform` >= 1.5, `gcloud` authentifié (`gcloud auth login` et
`gcloud auth application-default login`), `kubectl`, un projet GCP avec facturation.

```bash
cp infra/gcp-k3s/terraform.tfvars.example infra/gcp-k3s/terraform.tfvars
# éditer project_id (et admin_source_ranges = ["<votre IP>/32"])

make init
make apply          # ~1 min pour la VM, puis ~3-5 min de bootstrap k3s
make logs           # suivre l'installation (Ctrl+C quand "Bootstrap terminé")

make kubeconfig     # écrit .kube/config (utilisé automatiquement par make)
export KUBECONFIG=$PWD/.kube/config
kubectl get nodes

make demo           # → https://whoami.<IP>.sslip.io
```

Sans `admin_source_ranges` : `make kubeconfig-iap` puis `make tunnel` dans un
terminal séparé (l'API est alors joignable sur `https://127.0.0.1:6443`).

Nettoyage : `make destroy`.

Détails et options : [`infra/gcp-k3s/README.md`](infra/gcp-k3s/README.md).

## Feuille de route

- [x] Initialisation du repo
- [x] Plateforme : VM GCP + k3s + exposition Internet (Traefik, TLS Let's Encrypt)
- [ ] Observabilité : Prometheus / Alertmanager, logs, événements Kubernetes
- [ ] Applications cibles et scénarios d'incidents reproductibles (chaos)
- [ ] Agent de diagnostic (LLM + outils K8s en lecture seule)
- [ ] Remédiation automatique avec garde-fous (dry-run, approbation, audit)
