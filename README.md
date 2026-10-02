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
        │  │   └─ applications (ex : demo-whoami)                  │  │
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
| [`manifest/base/`](manifest/base/) | Socle : cert-manager, ClusterIssuers Let's Encrypt |
| [`manifest/applications/`](manifest/applications/) | Applications (ex : `demo-whoami` exposée sur Internet) |
| [`bin/`](bin/) | Kubeconfig, upgrade Flux, validation des manifests |
| `Makefile` | Raccourcis (`make help`) |

## Démarrage rapide

Prérequis : `terraform` >= 1.5, `gcloud` authentifié (`gcloud auth login` et
`gcloud auth application-default login`), un projet GCP avec facturation.
Optionnel : `kubectl` et `flux` pour inspecter le cluster.

```bash
cp infra/gcp-k3s/terraform.tfvars.example infra/gcp-k3s/terraform.tfvars
# éditer project_id

make init
make apply          # VM ~1 min, puis k3s + Flux + cert-manager + démo en ~5 min
make logs           # (optionnel) suivre le bootstrap de la VM

curl "$(terraform -chdir=infra/gcp-k3s output -raw demo_url)"
```

Accès au cluster (optionnel) :

```bash
make kubeconfig     # nécessite admin_source_ranges = ["<votre IP>/32"]
# ou : make kubeconfig-iap puis `make tunnel` dans un autre terminal
export KUBECONFIG=$PWD/.kube/config
make flux-status
```

Nettoyage : `make destroy`.

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
- [ ] Observabilité : Prometheus / Alertmanager, logs, événements Kubernetes
- [ ] Applications cibles et scénarios d'incidents reproductibles (chaos)
- [ ] Agent de diagnostic (LLM + outils K8s en lecture seule)
- [ ] Remédiation automatique avec garde-fous (dry-run, approbation, audit)
