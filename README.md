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

Terraform ne fait que créer la VM et installer k3s ; tout ce qui tourne dans le
cluster est déployé par **FluxCD** depuis le dossier [`manifest/`](manifest/)
(même organisation que le projet home-server). Les applications sont exposées
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
| [`bin/`](bin/) | Kubeconfig, bootstrap/upgrade Flux, chiffrement SOPS, validation des manifests |
| `Makefile` | Raccourcis (`make help`) |

## Démarrage rapide

Prérequis : `terraform` >= 1.5, `gcloud` authentifié (`gcloud auth login` et
`gcloud auth application-default login`), `kubectl`, `flux`, `sops`, un projet
GCP avec facturation, et la clé age `age.agekey` (la même que home-server).

```bash
cp infra/gcp-k3s/terraform.tfvars.example infra/gcp-k3s/terraform.tfvars
# éditer project_id (et admin_source_ranges = ["<votre IP>/32"])

make init
make apply          # ~1 min pour la VM, puis ~3-5 min de bootstrap k3s
make logs           # suivre l'installation (Ctrl+C quand "Bootstrap terminé")

make kubeconfig     # écrit .kube/config (utilisé automatiquement par make)
export KUBECONFIG=$PWD/.kube/config
kubectl get nodes

# Flux : créer une deploy key GitHub (lecture seule) puis
make flux-bootstrap FLUX_KEY=./flux-deploy-key AGE_KEY=./age.agekey
make flux-status    # cert-manager → cluster-issuers → demo-whoami
curl https://whoami.$(terraform -chdir=infra/gcp-k3s output -raw ingress_base_domain)
```

Sans `admin_source_ranges` : `make kubeconfig-iap` puis `make tunnel` dans un
terminal séparé (l'API est alors joignable sur `https://127.0.0.1:6443`).

Nettoyage : `make destroy`.

Détails : [`infra/gcp-k3s/README.md`](infra/gcp-k3s/README.md) (infra) et
[`manifest/flux-system/README.md`](manifest/flux-system/README.md) (GitOps).

## Ajouter une application

1. `manifest/applications/<app>/` : `kustomization.yaml` + un fichier par ressource
   (`<app>-namespace.yaml`, `<app>-deployment.yaml`, `<app>-ingress.yaml`...).
2. `manifest/flux-system/applications/<app>-ks.yaml` (copier `demo-whoami-ks.yaml`)
   et l'ajouter dans `manifest/flux-system/applications/kustomization.yaml`.
3. Secrets : `bin/encrypt_secret.sh manifest/applications/<app>/<app>-secret.yaml`.
4. `make lint`, commit, push sur `main` : Flux déploie (≤ 1 min).

## Feuille de route

- [x] Initialisation du repo
- [x] Plateforme : VM GCP + k3s + exposition Internet (Traefik, TLS Let's Encrypt)
- [x] GitOps : déploiement via FluxCD (`manifest/`), secrets SOPS + age
- [ ] Observabilité : Prometheus / Alertmanager, logs, événements Kubernetes
- [ ] Applications cibles et scénarios d'incidents reproductibles (chaos)
- [ ] Agent de diagnostic (LLM + outils K8s en lecture seule)
- [ ] Remédiation automatique avec garde-fous (dry-run, approbation, audit)
