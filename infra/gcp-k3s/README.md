# infra/gcp-k3s

Provisionne sur Google Cloud une VM Compute Engine exécutant un cluster
**k3s single-node**, prête à exposer des applications sur Internet.

## Ressources créées

| Ressource | Rôle |
| --- | --- |
| APIs `compute`, `iam`, `iap` | Activées sur le projet (non désactivées au destroy) |
| VPC `<name>-vpc` + sous-réseau | Réseau dédié (`10.10.0.0/24` par défaut) |
| IP externe statique `<name>-ip` | Point d'entrée unique (apps + API Kubernetes) |
| Firewall `allow-http-https` | 80/443 depuis `ingress_source_ranges` (Internet par défaut) |
| Firewall `allow-iap` | 22/6443 depuis la plage IAP de Google (`35.235.240.0/20`) |
| Firewall `allow-admin` | 22/6443 depuis `admin_source_ranges` (créée seulement si renseigné) |
| Service account `<name>-node` | Identité de la VM (logs + métriques uniquement) |
| VM `<name>` | Ubuntu 24.04, Shielded VM, OS Login, startup script k3s |

## Bootstrap de la VM

Le [startup script](templates/startup.sh.tftpl) (idempotent, rejoué à chaque boot) :

1. écrit `/etc/rancher/k3s/config.yaml` (`tls-san` et `node-external-ip` = IP publique) ;
2. installe k3s via `get.k3s.io` (canal `stable` ou version pinnée) — Traefik et
   ServiceLB sont fournis par défaut et écoutent sur 80/443 du nœud ;
3. déploie **cert-manager** via le Helm controller intégré à k3s (`HelmChart`) ;
4. crée les `ClusterIssuer` `letsencrypt-staging` et `letsencrypt-prod`
   (solveur HTTP-01 via Traefik).

Logs : `/var/log/k3s-bootstrap.log` (`make logs`).

## Variables principales

| Variable | Défaut | Description |
| --- | --- | --- |
| `project_id` | — | Projet GCP (obligatoire) |
| `region` / `zone` | `europe-west1` / `europe-west1-b` | Localisation |
| `name` | `ai4ops-k3s` | Préfixe des ressources |
| `machine_type` | `e2-standard-4` | 4 vCPU / 16 Go, marge pour l'observabilité et l'agent |
| `spot` | `false` | VM Spot (~60-90 % moins chère, préemptible) |
| `admin_source_ranges` | `[]` | IPs autorisées en direct sur 22/6443 |
| `ingress_source_ranges` | `["0.0.0.0/0"]` | IPs autorisées sur 80/443 |
| `k3s_channel` / `k3s_version` | `stable` / `""` | Version de k3s |
| `cert_manager_version` | `v1.18.2` | Version cert-manager (`""` = pas de cert-manager) |
| `acme_email` | `""` | Email de contact Let's Encrypt (optionnel) |

Voir [`variables.tf`](variables.tf) pour la liste complète.

## Exposer une application

Créer un `Ingress` de classe `traefik` sur un host résolvant vers l'IP publique :

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mon-app
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod   # optionnel : HTTPS auto
spec:
  ingressClassName: traefik
  tls:
    - hosts: [mon-app.<IP>.sslip.io]
      secretName: mon-app-tls
  rules:
    - host: mon-app.<IP>.sslip.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: mon-app
                port:
                  number: 80
```

`terraform output ingress_base_domain` donne le suffixe `<IP>.sslip.io`.
Exemple complet : [`apps/demo-whoami`](../../apps/demo-whoami/manifest.yaml).

**Domaine personnalisé** : créer un enregistrement DNS wildcard
`*.poc.example.com A <IP>` et utiliser ces hosts dans les Ingress.

> Let's Encrypt limite le nombre de certificats par domaine enregistré. En cas
> d'erreur de rate limit sur sslip.io, utiliser `letsencrypt-staging`
> (`make demo-staging`) ou un domaine personnalisé.

## State Terraform

Local par défaut (`terraform.tfstate`, ignoré par git). Pour un state partagé,
voir [`backend.tf.example`](backend.tf.example) (bucket GCS).
Après le premier `terraform init`, committer le fichier `.terraform.lock.hcl`.

## Sécurité (POC)

- API Kubernetes et SSH non exposés publiquement par défaut (IAP uniquement).
- OS Login activé : l'accès SSH est piloté par IAM.
- Service account de la VM limité à l'écriture de logs et métriques.
- Kubeconfig admin en `0600` sur la VM, récupéré via SSH dans `.kube/` (ignoré par git).
