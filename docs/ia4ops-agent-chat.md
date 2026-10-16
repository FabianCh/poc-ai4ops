# Déploiement privé du chatbot IA4Ops

Le chatbot Chainlit est déployé dans un namespace distinct (`ia4ops-agent-chat`) sans Ingress.
L'accès depuis un poste opérateur passe par `kubectl port-forward` ; aucun endpoint public ou DNS
n'est créé.

## Profil initial

- `LLM_PROVIDER=gemini` et `REQUEST_INTERPRETER_PROVIDER=gemini` : diagnostic et interprétation
  en langage naturel via Vertex AI (`gemini-2.5-flash`).
- `DATA_PROVIDER=real` : métriques Prometheus, logs Loki et traces Jaeger via les proxies Grafana.
  Le provider Kubernetes demeure non implémenté et signalera la source indisponible.
- Le webhook Alertmanager est routé en parallèle à l'agent stable. Les alertes du namespace
  `otel-demo` restent en attente et n'exécutent aucun diagnostic avant confirmation opérateur.
- Après confirmation, les investigations manuelles et celles issues d'une alerte affichent un seul
  message de progression actualisé avec un indicateur animé et l'étape active ; le rapport final
  remplace ce message lorsque le diagnostic est terminé.
- Un webhook synthétique peut aussi être envoyé manuellement à
  `http://localhost:8000/webhooks/alertmanager` pendant que le port-forward est actif. Il sera
  traité par la même validation, déduplication et attente d'approbation que les alertes réelles.
- Les événements d'audit sont stockés sur un PVC local-path ; l'état des alertes en attente reste
  en mémoire et est perdu si le pod redémarre.
- Le Dockerfile embarque `.chainlit/config.toml` et les assets `public/` (thèmes, CSS, logos)
  dans l'image runtime. `/app/.files` et `/app/.chainlit/translations` sont montés sur des
  `emptyDir` inscriptibles : Chainlit exige leur écriture au démarrage même si l'IHM n'active pas
  l'upload de fichiers. Leur contenu temporaire disparaît au redémarrage du pod.
- Le LLM appelle Vertex AI et peut générer des coûts. Le compte de service GCP doit être autorisé
  à utiliser Vertex AI dans `wavestone-cto-ai4ops`.

Le Deployment nécessite deux Secrets créés hors Git dans le namespace `ia4ops-agent-chat` avant
son démarrage en mode réel.

1. Créer une clé JSON d'un compte de service dédié, avec le rôle minimal `roles/aiplatform.user`
   dans le projet `wavestone-cto-ai4ops`, après avoir vérifié que l'API Vertex AI est activée.
   Copier le fichier de façon sécurisée vers Cloud Shell, puis créer le Secret sans afficher ni
   committer le contenu :

   ```bash
   kubectl -n ia4ops-agent-chat create secret generic ia4ops-agent-chat-gemini \
     --from-file=credentials.json="$HOME/credentials/ia4ops-agent-chat.json"
   ```

   Le conteneur monte cette clé en lecture seule et utilise ADC via
   `GOOGLE_APPLICATION_CREDENTIALS`. Ne jamais coller son contenu dans le chat ni l'ajouter au dépôt.

2. Copier dans le namespace chatbot le Secret Grafana déjà utilisé par l'agent stable. Le pipeline
   transmet le document directement à l'API Kubernetes sans afficher les valeurs :

   ```bash
   kubectl -n ia4ops get secret grafana-credentials -o json \
     | jq 'del(.metadata.uid,.metadata.resourceVersion,.metadata.creationTimestamp,.metadata.managedFields) | .metadata.namespace="ia4ops-agent-chat"' \
     | kubectl apply -f -
   ```

3. Vérifier que les deux Secrets sont présents sans afficher leur contenu :

   ```bash
   kubectl -n ia4ops-agent-chat get secret ia4ops-agent-chat-gemini grafana-credentials
   ```

La NetworkPolicy autorise DNS et HTTPS sortant (TCP 443) vers Vertex AI et Grafana. Les NetworkPolicy
Kubernetes standard ne pouvant pas borner les destinations par nom DNS, cette règle autorise HTTPS
vers toute destination depuis ce seul pod. Ne pas exposer d'Ingress tant que l'authentification
n'est pas implémentée et validée.

## Publication et activation

1. Fusionner les changements sur `main`. Le workflow `ia4ops-agent-chat` exécute les tests, puis
   publie `ghcr.io/fabianch/poc-ai4ops/ia4ops-agent-chat` avec un tag `latest` et un tag SHA.
2. Avant la réconciliation, rendre le package GHCR public depuis les paramètres du package, comme
   l'image de l'agent stable. Le workflow ne configure pas lui-même la visibilité. Si le package
   doit rester privé, créer un Secret de pull hors Git et ajouter sa référence au Deployment avant
   de le réconcilier.
3. Le manifeste utilise `latest` pour le premier démarrage et `imagePullPolicy: Always`. Après le
   premier build, préférer le tag immuable `sha-<7 caractères>` affiché par Actions et mettre à jour
   `newTag` dans `manifest/applications/ia4ops-agent-chat/kustomization.yaml`.
4. Attendre la réconciliation Flux (après création des Secrets requis) :

   ```bash
   flux get kustomizations
   flux get kustomization ia4ops-agent-chat
   kubectl -n ia4ops-agent-chat rollout status deployment/ia4ops-agent-chat
   kubectl -n ia4ops-agent-chat get pods,svc,pvc,networkpolicy
   ```

La Kustomization Flux attend la Kustomization de `kube-prometheus-stack`, car la configuration
Alertmanager inclut maintenant le receiver chatbot. Le receiver stable de `ia4ops-agent` est
conservé ; la route chatbot est ajoutée en parallèle pour `namespace=otel-demo`.

## Accès depuis Windows

Avec un kubeconfig et les droits `pods/portforward` dans le namespace :

```powershell
kubectl -n ia4ops-agent-chat port-forward --address 127.0.0.1 svc/ia4ops-agent-chat 8000:8000
```

Garder cette fenêtre PowerShell ouverte, puis ouvrir :

- Chat : <http://localhost:8000/chat/>
- Santé : <http://localhost:8000/health>
- API : <http://localhost:8000/docs>

Arrêter le tunnel avec `Ctrl+C`. Ne pas remplacer `127.0.0.1` par `0.0.0.0` : cela exposerait le
tunnel aux autres interfaces réseau du poste.

Le port-forward contourne les NetworkPolicies Kubernetes ; elles protègent le pod des autres
connexions directes inter-pods. Le port-forward reste accessible à toute personne disposant des
autorisations Kubernetes appropriées. Ce n'est pas un mécanisme d'authentification pour une URL
publique.

## Validation du webhook Alertmanager

Envoyer un payload Alertmanager v4 à `POST http://localhost:8000/webhooks/alertmanager` par le
tunnel (par exemple le payload de test utilisé en local). Une alerte firing doit apparaître dans le
chatbot comme étant en attente. Vérifier qu'aucune
collecte ne démarre avant **Investiguer** ; **Ignorer** clôt l'alerte sans diagnostic. La route
Alertmanager du cluster envoie également chaque alerte `otel-demo` à cette copie et à l'agent stable.

Le service ne reçoit pas de trafic opérateur direct depuis Internet. L'accès navigateur est initié
par le tunnel local ; seul Alertmanager est autorisé à joindre le webhook depuis le réseau du cluster.
