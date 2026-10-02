# Récupérer URLs et secrets depuis Cloud Shell

[Cloud Shell](https://shell.cloud.google.com) est déjà authentifié avec votre compte Google et
embarque `gcloud`, `kubectl` et `jq` : rien à installer. Le state Terraform étant local au poste
qui a lancé `make apply`, on retrouve tout directement via `gcloud`.

Prérequis : un rôle permettant SSH via IAP sur le projet (`Owner`, ou
`roles/compute.osAdminLogin` + `roles/iap.tunnelResourceAccessor` + `roles/compute.viewer`). Au premier
`gcloud compute ssh`, une clé SSH est générée (laisser la passphrase vide).

## 1. Variables

À adapter si `name`, `region` ou `zone` ont été changés dans `terraform.tfvars` :

```bash
export PROJECT_ID=<mon-projet-gcp>
export NAME=ai4ops-k3s REGION=europe-west1 ZONE=europe-west1-b
gcloud config set project "$PROJECT_ID"
```

## 2. URLs

```bash
IP=$(gcloud compute addresses describe "$NAME-ip" --region "$REGION" --format='value(address)')
cat <<EOF
Grafana       : https://grafana.$IP.sslip.io
OTel Demo     : https://otel-demo.$IP.sslip.io   (/feature, /jaeger/ui, /loadgen)
Demo whoami   : https://whoami.$IP.sslip.io
EOF
```

Liste complète des endpoints : [endpoints.md](endpoints.md).

## 3. Secrets

### Mot de passe Grafana

Généré aléatoirement à l'installation et stocké dans le secret Kubernetes
`monitoring/kube-prometheus-stack-grafana` (utilisateur `admin`). Lecture via SSH sur la VM :

```bash
gcloud compute ssh "$NAME" --zone "$ZONE" --tunnel-through-iap --command \
  "sudo k3s kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo"
```

> Si le mot de passe a été changé depuis l'UI Grafana, le secret n'est plus à jour : c'est alors
> le nouveau mot de passe qui fait foi.

### Kubeconfig (accès `kubectl` depuis Cloud Shell)

Le kubeconfig admin de k3s pointe sur `https://127.0.0.1:6443` : il fonctionne tel quel à
travers un tunnel IAP.

```bash
mkdir -p ~/.kube
gcloud compute ssh "$NAME" --zone "$ZONE" --tunnel-through-iap \
  --command 'sudo cat /etc/rancher/k3s/k3s.yaml' > ~/.kube/ai4ops.yaml
chmod 600 ~/.kube/ai4ops.yaml

# Tunnel IAP vers l'API Kubernetes (en arrière-plan)
gcloud compute start-iap-tunnel "$NAME" 6443 --local-host-port=localhost:6443 --zone "$ZONE" \
  > /tmp/iap-tunnel.log 2>&1 &

export KUBECONFIG=~/.kube/ai4ops.yaml
kubectl get nodes
```

Le tunnel s'arrête avec la session Cloud Shell : relancer la commande `start-iap-tunnel` à
chaque nouvelle session. Ne jamais committer ce fichier (accès admin complet au cluster).

Sans tunnel, n'importe quelle commande `kubectl` peut aussi être lancée directement sur la VM :

```bash
gcloud compute ssh "$NAME" --zone "$ZONE" --tunnel-through-iap --command 'sudo k3s kubectl get pods -A'
```

## 4. Accès aux UIs internes

Prometheus et Alertmanager ne sont pas exposés. Avec le tunnel ci-dessus, un port-forward sur
le port 8080 s'ouvre via l'**aperçu Web** de Cloud Shell (bouton « Web Preview » > « Preview on
port 8080 ») :

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 8080:9090     # Prometheus
kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 8080:9093   # Alertmanager
```

## 5. État de la plateforme

```bash
gcloud compute instances describe "$NAME" --zone "$ZONE" --format='value(status)'   # RUNNING / TERMINATED
kubectl get kustomizations -n flux-system        # état des déploiements Flux
kubectl get helmreleases -A
```

Arrêter / redémarrer la VM (voir l'impact sur les coûts dans [couts.md](couts.md)) :

```bash
gcloud compute instances stop  "$NAME" --zone "$ZONE"
gcloud compute instances start "$NAME" --zone "$ZONE"   # tout redémarre seul (k3s, Flux, applications)
```
