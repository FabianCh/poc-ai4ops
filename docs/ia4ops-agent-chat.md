# Déploiement privé du chatbot IA4Ops

Le chatbot Chainlit est déployé dans un namespace distinct (`ia4ops-agent-chat`) sans Ingress.
L'accès depuis un poste opérateur passe par `kubectl port-forward` ; aucun endpoint public ou DNS
n'est créé.

## Profil initial

- `LLM_PROVIDER=mock` : le diagnostic ne fait aucun appel Gemini.
- `DATA_PROVIDER=mock` : les observations sont synthétiques.
- `REQUEST_INTERPRETER_PROVIDER=disabled` : pas d'appel Vertex AI ; utiliser la commande
  `/investigate <service> [minutes] | <question>`.
- Le webhook Alertmanager est routé en parallèle à l'agent stable. Les alertes du namespace
  `otel-demo` restent en attente et n'exécutent aucun diagnostic avant confirmation opérateur.
- Un webhook synthétique peut aussi être envoyé manuellement à
  `http://localhost:8000/webhooks/alertmanager` pendant que le port-forward est actif. Il sera
  traité par la même validation, déduplication et attente d'approbation que les alertes réelles.
- Les événements d'audit sont stockés sur un PVC local-path ; l'état des alertes en attente reste
  en mémoire et est perdu si le pod redémarre.
- Le répertoire interne Chainlit `/app/.files` est monté sur un `emptyDir` inscriptible, requis
  même lorsque l'IHM n'active pas l'upload de fichiers ; son contenu temporaire disparaît au
  redémarrage du pod.

Pour activer l'interpréteur naturel et les providers réels dans le cluster, il faudra provisionner
les Secrets hors Git, configurer les sorties réseau nécessaires vers Vertex AI et Grafana, puis
réviser la politique egress restrictive. Ne pas exposer d'Ingress tant que l'authentification n'est
pas implémentée et validée.

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
4. Attendre la réconciliation Flux :

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
