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

Avec le dépôt cloné et `kubectl` configuré (voir plus bas), `make get-secrets` affiche d'un coup les URLs
et les mots de passe de Grafana et de Keep (`make get-grafana-password`, `make get-keep-password` pour un seul).
Les commandes manuelles ci-dessous donnent le même résultat sans `make`.

### Mot de passe Grafana

Généré aléatoirement à l'installation et stocké dans le secret Kubernetes
`monitoring/kube-prometheus-stack-grafana` (utilisateur `admin`). Lecture via SSH sur la VM :

```bash
gcloud compute ssh "$NAME" --zone "$ZONE" --tunnel-through-iap --command \
  "sudo k3s kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo"
```

> Si le mot de passe a été changé depuis l'UI Grafana, le secret n'est plus à jour : c'est alors
> le nouveau mot de passe qui fait foi.

### Keep (console d'alertes)

Les secrets de Keep ne sont pas dans Git. Une fois Flux synchronisé (`kubectl get helmrelease -n keep`),
créer les Secrets (mot de passe admin, clé JWT, clé d'API d'Alertmanager) avec `kubectl` configuré
([plus bas](#kubeconfig-accès-kubectl-depuis-cloud-shell)) :

```bash
make create-keep-secrets        # idempotent : affiche le mot de passe admin à la première création seulement
```

Sans `make` (Cloud Shell sans le dépôt cloné), cloner le dépôt puis lancer `bin/create-keep-secrets.sh`.
Relire le mot de passe ensuite :

```bash
kubectl -n keep get secret keep-backend-auth -o jsonpath='{.data.KEEP_DEFAULT_PASSWORD}' | base64 -d; echo
```

Le même script crée la clé d'API de l'**agent IA4Ops** (rôle `admin`, seul rôle de Keep cumulant
`read:alert` et `write:incident` ; il n'y a pas de rôle sur mesure) dans le Secret
`ia4ops/ia4ops-agent-keep` (`KEEP_API_KEY`), sans toucher à celle d'Alertmanager. Si Keep est déjà
installé, la clé est ajoutée à `KEEP_DEFAULT_API_KEYS` puis `keep-backend` est redémarré (Keep ne
provisionne ses clés qu'au démarrage). Aucune clé n'est affichée ; pour la lire en local :

```bash
kubectl -n ia4ops get secret ia4ops-agent-keep -o jsonpath='{.data.KEEP_API_KEY}' | base64 -d; echo
```

L'agent joint Keep sur `http://keep-backend.keep.svc:8080` (sans préfixe `/v2`, réservé à l'Ingress public).

Tant que les Secrets n'existent pas, les pods `keep-backend` et `keep-frontend` restent en
`CreateContainerConfigError` (Keep ne démarre jamais sans authentification) et les envois
d'Alertmanager vers Keep échouent, sans affecter ceux vers l'agent. Les valeurs de l'utilisateur
(`admin`) et de la clé d'API (`alertmanager`, rôle `webhook`) sont figées dans la base de Keep au
premier démarrage : pour les changer, supprimer le PVC `keep-pvc` (perte de l'historique).

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
