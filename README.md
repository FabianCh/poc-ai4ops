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

### 5. Tester le GitOps

1. Passer `replicas: 2` à `3` dans
   `manifest/applications/demo-whoami/demo-whoami-deployment.yaml`.
2. Commit + push sur `main`.
3. `make flux-reconcile` (ou attendre ~1 min), puis
   `kubectl -n demo-whoami get pods` : 3 pods.

### 6. Nettoyer

```bash
make destroy
```

### Dépannage

| Symptôme | Diagnostic |
| --- | --- |
| Le bootstrap ne se termine pas | `make ssh` puis `sudo cat /var/log/k3s-bootstrap.log` |
| Flux ne synchronise pas | `kubectl -n flux-system get gitrepository,kustomization` |
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
- [ ] Observabilité : Prometheus / Alertmanager, logs, événements Kubernetes
- [ ] Applications cibles et scénarios d'incidents reproductibles (chaos)
- [ ] Agent de diagnostic (LLM + outils K8s en lecture seule)
- [ ] Remédiation automatique avec garde-fous (dry-run, approbation, audit)
