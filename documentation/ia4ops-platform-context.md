# IA4Ops — Contexte technique de la plateforme (Fabian)

> **Auteur** : synthèse Maël Mitchel à partir de la réunion avec Fabian Chauvin + lecture du dépôt `poc-ai4ops/`  
> **Date** : octobre 2026  
> **Usage** : référence pour l'implémentation de l'agent  
> **Statut des champs** : ✅ confirmé (dépôt lu) | ⏳ en attente | ❓ à clarifier

> **Mise à jour du 26 octobre 2026** : Keep est déployé (`manifest/applications/keep/`) et reçoit les
> alertes en parallèle de l'agent stable et du chatbot `ia4ops-agent-chat` (namespace dédié, sans Ingress,
> accès par port-forward). Les traces Jaeger sont lues par les agents via Grafana depuis le 9 octobre.
> Depuis le 19 octobre, chaque agent a un ServiceAccount et un Role `get/list` sur `pods`, `events`,
> `deployments` et `replicasets` dans `otel-demo` ; le chatbot a une NetworkPolicy d'egress vers l'API
> Kubernetes (TCP 6443). Les Kustomizations Flux des agents dépendent de `otel-demo` et n'ont plus de
> `targetNamespace`. État du cluster non vérifié depuis le dépôt. Détail dans `ia4ops-progress.md`.

> **Mise à jour du 8 octobre 2026** : la plateforme, Flux, l'observabilité, les alertes,
> les providers Prometheus/Loki réels et l'envoi réel des webhooks sont opérationnels en cluster.
> Le manifeste de travail configure maintenant `LLM_PROVIDER=gemini` et `DATA_PROVIDER=real` pour
> le prochain test ; ce changement et le correctif Keep attendent encore CI/publication/déploiement.
> Le test Keep a déjà prouvé création + association d'alerte, mais pas la publication d'activité.
> Voir `ia4ops-progress.md` pour le suivi détaillé.

> **Complément du 7 octobre 2026 — réunion et suivi** : Maël rapporte avoir désormais
> accès au cluster via Cloud Shell/IAP. Il a créé le Secret `model-garden-credentials` dans
> `ia4ops`, avec le fichier `service-account.json`. Le Secret est maintenant monté dans le pod
> et Maël a confirmé un appel direct réussi à `gemini-2.5-flash` depuis ce pod (une tentative).
> Les permissions effectives permettent donc cet appel ; aucune attribution IAM supplémentaire
> n'a été requise pour le test, mais cela ne prouve pas l'absence du rôle dans les permissions
> héritées ou existantes. Le diagnostic des webhooks reste en mode mock. Le compte partagé et la
> clé JSON sont des simplifications temporaires du POC, à réévaluer. Keep est retenu comme interface de
> démonstration supervisée. Les alertes sont routées en parallèle vers Keep et l'agent dans le
> dépôt ; le câblage local de publication vers Keep est réalisé le 8 octobre, en attente de
> publication et validation réelle.
> Ces éléments de réunion sont des déclarations rapportées, pas une validation technique
> indépendante du cluster.

> **Mise à jour Keep du 8 octobre 2026** : le Secret Kubernetes
> `ia4ops/ia4ops-agent-keep` existe (confirmation de Maël, une clé ; valeur non consultée), une
> clé dédiée à l'agent est configurée avec le rôle `admin` par le script, et la NetworkPolicy
> autorise l'agent vers Keep sur TCP 8080. L'image référencée par Flux contient le client HTTP
> préparatoire, mais pas encore le publisher branché localement. Les tests simulés passent ; aucun
> appel réel agent → Keep n'a encore été validé.

> **Résultat du test Keep du 8 octobre** : l'incident a été créé et lié aux alertes, mais l'activité
> de diagnostic n'a pas été publiée. Loki montre que l'association répond `202 Accepted` puis le
> client échoue en attendant du JSON sur cette réponse. Correctif local : traiter le `202` de
> l'association comme un acquittement sans corps ; tests ciblés passent. Correctif à committer,
> republier et redéployer avant répétition du test en cluster.

---

## 1. Infrastructure

### Déploiement

| Élément | Valeur | Statut |
|---|---|---|
| Cloud provider | Google Cloud Platform (GCP) | ✅ |
| Type d'instance | Google Compute Engine — `e2-standard-4`, Ubuntu 24.04 | ✅ |
| Provisionnement | Terraform (`infra/gcp-k3s/`) | ✅ |
| Orchestrateur | **k3s** (single node) | ✅ confirmé dépôt |
| Outil de déploiement applicatif | **FluxCD** (GitOps, branche `main`, repo public HTTPS) | ✅ |
| Dépôt GitOps | `poc-ai4ops` — GitHub de Fabian (public) | ✅ |
| États Terraform | Non publiés dans le dépôt principal | ✅ |

### Accès

| Élément | Valeur | Statut |
|---|---|---|
| DNS | **sslip.io** — `<app>.<IP>.sslip.io` résout vers la VM | ✅ confirmé dépôt |
| TLS | cert-manager + Let's Encrypt automatique | ✅ |
| Ingress | **Traefik** (`ingressClassName: traefik`) | ✅ confirmé dépôt |
| IP publique | `terraform -chdir=infra/gcp-k3s output -raw external_ip` | ✅ |
| Connexion locale | `make tunnel` (tunnel IAP) ou `make kubeconfig` si `admin_source_ranges` configuré | Tunnel et `kubectl get nodes` confirmés par Maël le 7 octobre |
| Connexion recommandée | Cloud Shell GCP | Accès cluster obtenu via les droits supplémentaires fournis par Joseph, selon Maël |
| Accès Maël au projet | Droits supplémentaires reçus ; niveau exact à confirmer | Opérationnel pour la session Cloud Shell rapportée |

---

## 2. Application de démonstration

### OTel Demo — Mini-marketplace

| Élément | Valeur | Statut |
|---|---|---|
| Application | OpenTelemetry Demo (mini-marketplace) | ✅ |
| Namespace Kubernetes | `otel-demo` | ✅ |
| Services principaux | `product-catalog`, `checkout`, `frontend`, et autres | ✅ |
| Injection d'incidents | Via feature flags (onglet dédié dans l'UI) | ✅ |

### Feature flags (injection de pannes)

Ces flags sont utilisés pour créer les scénarios de démonstration. Ils sont activables via l'API flagd (`/feature/api/write`).

| Flag | Effet | Alerte déclenchée |
|---|---|---|
| `productCatalogFailure` | Erreurs sur le service product-catalog | `OtelDemoServiceHighErrorRate` |
| `adHighCpu` | Consommation CPU élevée sur le service ad | `OtelDemoContainerHighCpu` |
| `kafkaQueueProblems` | Lag sur les consumers Kafka | `OtelDemoKafkaConsumerLag` |
| Autres flags | À documenter avec Fabian | ⏳ |

> **Note** : le test `productCatalogFailure` a été validé de bout en bout (pending → firing → reçue par Alertmanager → résolue) avant la réunion.

---

## 3. Stack d'observabilité

### Composants déployés

| Composant | Rôle | État |
|---|---|---|
| **Prometheus + Alertmanager** (`kube-prometheus-stack`) | Métriques du cluster, règles d'alerte, rétention 7j | ✅ déployé |
| **Grafana** | Dashboards, Explore (Prometheus, Loki, Jaeger), Alerting | ✅ déployé — auth `admin` + mdp généré |
| **Loki** | Logs applicatifs, rétention 7j | ✅ déployé |
| **Alloy** | Collecte logs de tous les pods + événements Kubernetes → Loki | ✅ déployé |
| **Jaeger** | Traces distribuées (fourni par OTel Demo) | ✅ déployé — opérationnel |
| **OTel Collector** | Pipeline OTLP → Prometheus + Loki | ✅ déployé |

> **Correction** : les traces Jaeger **sont disponibles** (via OTel Demo) et sont désormais consommées par les agents (collecte des traces en erreur via Grafana, depuis le 9 octobre).

### Endpoints — namespace `monitoring`

Prometheus et Alertmanager ne sont **pas exposés publiquement**. Accès via port-forward ou **proxy Grafana API** (recommandé pour l'agent).

| Service | Accès port-forward | Via Grafana API proxy |
|---|---|---|
| Prometheus | `kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090` | `https://grafana.<IP>.sslip.io/api/datasources/proxy/uid/prometheus/api/v1/...` |
| Alertmanager | `kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093` | `https://grafana.<IP>.sslip.io/api/datasources/proxy/uid/alertmanager/api/v2/alerts` |
| Loki | `kubectl -n monitoring port-forward svc/loki 3100` | `https://grafana.<IP>.sslip.io/api/datasources/proxy/uid/loki/loki/api/v1/query_range` |
| Grafana | — | `https://grafana.<IP>.sslip.io` — `admin` + mdp |

Récupérer le mot de passe Grafana :
```bash
kubectl -n monitoring get secret kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Les appels via Grafana utilisent l'authentification HTTP basique : `curl -u admin:<password> ...`

### Labels OTel dans les métriques et logs

| Source | Label de service | Exemple |
|---|---|---|
| Métriques Prometheus (spanmetrics) | `service_name` | `{service_name="productcatalog"}` |
| Logs Loki | `service_name` | `{service_name="cart"}` |
| Logs Loki (namespace Kubernetes) | `k8s_namespace_name` | `{k8s_namespace_name="otel-demo"}` |
| Événements Kubernetes | `job="kubernetes-events"` | `{job="kubernetes-events"}` |

**Vérification Grafana par Maël — 7 octobre 2026** : pour `product-catalog`, Prometheus
retourne des séries avec `service_name="product-catalog"` (et aucune avec
`service_name="productcatalog"`). Loki retourne également des logs avec
`{service_name="product-catalog"}`. Correction issue de la vérification API du 7 octobre :
les streams Loki ne portent pas `namespace`; ils portent `k8s_namespace_name="otel-demo"`.
Le label `service_namespace` observé vaut `opentelemetry-demo`, donc n'est pas interchangeable
avec le namespace Kubernetes. Les streams récents inspectés étaient des logs INFO, avec les
labels `detected_level` et `severity_text` disponibles. Le provider Loki doit filtrer sur
`service_name`, `k8s_namespace_name` et `detected_level`, et non sur `namespace`.
`traces_span_metrics_calls_total` existe : la requête
`count(...)` retourne 200 séries au total et 4 pour `product-catalog`. À l'état observé,
le taux d'erreur calculé sur les spans serveur est à 0 et le p95 de
`traces_span_metrics_duration_milliseconds_bucket` oscille entre 50 et 75 ms. C'est une
mesure nominale à cet instant.

Après le déclenchement d'une erreur de catalogue par Maël le même jour, la formule de taux
d'erreur est montée depuis 0 (hausse décrite comme exponentielle, sans valeur exacte rapportée).
Le p95 a atteint un pic d'environ 82 ms puis est redescendu. Après désactivation de l'erreur,
Maël a confirmé le retour des métriques à la normale. Cette observation confirme que les
séries réagissent à l'injection ; le pic p95 reste largement inférieur au seuil d'alerte de
latence configuré à 1 000 ms. Le sélecteur Loki `{service_name="product-catalog"}` retourne
bien des logs ; l'utilisateur n'a pas observé de changement pendant l'incident. Une lecture
postérieure sur les 30 dernières minutes a trouvé 100 lignes, toutes de niveau INFO dans
l'échantillon plafonné, sans correspondance avec les niveaux d'erreur attendus. Cette lecture
ne permet pas de conclure qu'aucune erreur n'a été émise pendant l'injection, mais confirme
qu'il faudra vérifier la source/service qui porte les logs d'erreur attendus.

---

## 4. Alerting et webhook

### Règles d'alerte connues (OTel Demo) — confirmées dépôt

| Alerte | Condition | Sévérité | Feature flags déclencheurs |
|---|---|---|---|
| `OtelDemoServiceHighErrorRate` | > 5% spans serveur en erreur, 2 min | critical | `productCatalogFailure`, `cartFailure`, `paymentFailure` |
| `OtelDemoServiceHighLatency` | p95 > 1s, 5 min (hors services LLM) | warning | `imageSlowLoad`, `adManualGc` |
| `OtelDemoKafkaConsumerLag` | lag > 1000 messages, 5 min | warning | `kafkaQueueProblems` |
| `OtelDemoContainerHighCpu` | > 0.5 cœur, 5 min (hors load-generator) | warning | `adHighCpu` |
| `OtelDemoContainerMemoryNearLimit` | > 90% limite mémoire, 5 min | warning | `recommendationCacheFailure` |
| `OtelDemoContainerOOMKilled` | redémarrage après OOMKill | critical | `recommendationCacheFailure` |
| `OtelDemoFrontendNoTraffic` | plus de requêtes sur le frontend, 5 min | warning | arrêt load-generator |

### Configuration Alertmanager (dans le dépôt)

Le dépôt configure actuellement le receiver `ai4ops-agent` pour les alertes du namespace
`otel-demo`, avec `send_resolved: true`. La destination est le Service interne sur le port
**8000**. Fabian rapporte que l'envoi réel des webhooks firing et resolved a été testé.

```yaml
route:
  receiver: "null"
  group_by: ["namespace"]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 12h
  routes:
    - receiver: "null"
      matchers:
        - alertname = "Watchdog"
    - receiver: "ai4ops-agent"
      matchers:
        - namespace = "otel-demo"
      group_by: ["namespace", "alertname"]
      repeat_interval: 4h

receivers:
  - name: "null"
  - name: "ai4ops-agent"
    webhook_configs:
      - url: "http://ia4ops-agent.ia4ops.svc:8000/webhooks/alertmanager"
        send_resolved: true
```

> **Important — résolution non traitée comme clôture pour l'instant** : le code n'a pas de
> branche métier qui clôt l'incident sur `resolved`. En outre, la clé de déduplication
> (`fingerprints + startsAt`) ne distingue pas `firing` de `resolved` ; si l'alerte résolue
> reprend le même fingerprint et startsAt alors que sa clé est en cache, la route la renvoie
> comme doublon et n'exécute pas de clôture. Ajouter un chemin `resolved` avant la déduplication
> est donc nécessaire ; ne pas décrire le comportement courant comme une nouvelle analyse.
> Le groupement réel inclut `namespace` et `alertname` ; ne pas supposer que toutes les
> alertes d'un namespace sont toujours regroupées dans une notification unique.

### Décisions et pistes de la réunion du 7 octobre

- **Keep est l'interface de démonstration et de pilotage** : pas de frontend spécifique à
  construire pour la première démo. La pré-analyse doit rester une aide à la décision humaine ;
  aucune action automatique n'est dans le périmètre initial.
- **Routage existant** : le manifeste Alertmanager envoie déjà chaque alerte non-Watchdog à
  Keep et poursuit le routage vers l'agent pour `otel-demo` (`continue: true`). Cette
  architecture parallèle est donc le comportement actuel du dépôt. La réunion a aussi évoqué
  un flux où Keep solliciterait l'agent ; ce mode n'est pas configuré et n'est pas retenu pour
  la première mise en œuvre sans décision supplémentaire.
- **Précision sur les traces** : les événements JSON ne sont pas inclus dans le corps de réponse
  du webhook/API ; l'agent les écrit séparément sur stdout. La réponse HTTP confirme l'acceptation
  et l'API d'incident expose le rapport ; les traces passent par Alloy/Loki.
- **Lien Keep ↔ agent** : le publisher local recherche l'incident lié aux fingerprints du groupe,
  réutilise l'incident existant ou en crée un, associe les nouvelles alertes et ajoute l'activité
  de pré-analyse après le diagnostic. Les activités `resolved` sont publiées sans clôture
  automatique. L'idempotence est en mémoire ; une divergence de rattachement entre plusieurs
  incidents Keep est signalée au lieu de fusionner automatiquement. Tests simulés passés ; la
  validation de l'API et des scopes réels avec Keep `0.1.97` reste à faire après déploiement.
- **Routage / délais** : la route Keep configure `group_interval: 1m`, tandis que la route de
  l'agent hérite de `group_interval: 5m` défini sur la route parente. Les deux destinataires
  reçoivent donc les mises à jour à des cadences différentes. La réunion rapporte un décalage
  `resolved` d'environ cinq minutes ; vérifier les notifications observées et aligner le réglage
  de l'agent si le délai est confirmé et inacceptable pour la démo.
- **Réseau Keep** : le commit `bbc9678` ajoute la NetworkPolicy autorisant le pod
  `ia4ops-agent` du namespace `ia4ops` vers le backend Keep sur TCP 8080.
- **Secrets Keep** : le commit `bbc9678` ajoute une clé dédiée `ia4ops-agent` à la configuration
  Keep sans remplacer la clé Alertmanager et crée le Secret Kubernetes
  `ia4ops/ia4ops-agent-keep`. Maël en a confirmé l'existence le 7 octobre ; la valeur n'a pas été
  consultée ici. Le script attribue à cette clé le rôle Keep `admin` ; confirmer les permissions
  effectives et réduire le rôle si Keep le permet.
- **Périmètre d'action** : les scénarios d'approbation, dry-run, rollback et exécution décrits
  dans la proposition Claude sont des étapes ultérieures. Le premier incrément Keep doit publier
  une pré-analyse lisible à un humain, sans exécuter d'action.
- **À valider en cluster** : tester les scopes de la clé `admin`, la création/commentaire
  d'incident, les groupes multi-alertes, les répétitions et les retards de visibilité. Réduire
  le rôle de la clé si Keep permet un rôle moins privilégié.
- **Périmètre d'observation initial** : Prometheus pour les métriques et Loki pour les logs
  applicatifs. Ne pas ajouter au départ les événements Kubernetes ni agréger les logs du
  cluster dans les données consommées par l'agent. La nécessité d'un provider d'état des
  workloads Kubernetes reste à clarifier séparément.
- **Secret du modèle** : création d'un Secret d'accès au modèle rapportée pendant la réunion.
  Vérifier localement dans le cluster son nom et si le Deployment le monte ; ne jamais copier
  les valeurs dans Git, le compte-rendu ou une conversation avec une IA.
- **Secrets d'administration** : `make get-secrets` peut afficher des informations Grafana et
  Keep dans le terminal de l'opérateur. Ne pas transmettre ces valeurs à l'agent conversationnel.
  Les utiliser localement uniquement si une opération les requiert.

### Format du webhook

Voir `ia4ops-webhook-contract.md` pour le schéma complet Alertmanager v4.

---

## 5. Conventions Kubernetes et GitOps

### Namespace et service de l'agent

- Namespace : `ia4ops` (déjà créé par `manifest/applications/ia4ops-agent/ia4ops-agent-namespace.yaml`)
- Service interne : `ia4ops-agent.ia4ops.svc:8000`
- API non exposée publiquement ; consultation possible via `kubectl port-forward`.
- La NetworkPolicy autorise l'ingress au port 8000 depuis les pods Alertmanager du namespace `monitoring`.

### Structure réelle du dépôt Flux

```text
poc-ai4ops/
├── ia4ops-agent/                     ← projet Python, tests, Dockerfile, uv.lock et docs
└── manifest/
    ├── applications/
    │   └── ia4ops-agent/             ← uniquement les manifests Kubernetes
    │       ├── kustomization.yaml
    │       ├── ia4ops-agent-namespace.yaml
    │       ├── ia4ops-agent-deployment.yaml
    │       ├── ia4ops-agent-service.yaml
    │       ├── ia4ops-agent-pvc.yaml
    │       └── ia4ops-agent-networkpolicy.yaml
    └── flux-system/applications/
        ├── kustomization.yaml
        └── ia4ops-agent-ks.yaml
```

Le projet Python a été déplacé de `manifest/applications/ia4ops-agent/` vers
`ia4ops-agent/` dans le commit `84dd36f`. Le Deployment du manifeste de travail configure
`LLM_PROVIDER=gemini` et `DATA_PROVIDER=real` (choix découplés), n'embarque pas de token Kubernetes et conserve
l'audit trail sur un PVC. L'image est
construite et publiée par la CI (publication effective rapportée par Fabian).

La NetworkPolicy versionnée refuse l'ingress par défaut et autorise l'ingress depuis les
pods Alertmanager. Ces manifests ne définissent pas de politique d'egress ; les flux
sortants devront être revus lorsque les providers réels seront activés.

### RBAC Kubernetes pour l'agent (lecture seule)

Permissions nécessaires pour le scénario 1 — à créer dans `ia4ops-agent-rbac.yaml` :

```yaml
rules:
  - apiGroups: [""]
    resources: ["pods", "events", "services", "endpoints"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list"]
```

---

## 6. Informations à obtenir de Fabian

### Priorité haute — reste à faire pour la première démo

- [x] Secret rapporté créé : `model-garden-credentials` / `ia4ops`, avec `service-account.json` ; ne pas lire/afficher sa valeur.
- [x] Séparer le choix du LLM de celui des providers (`LLM_PROVIDER` / `DATA_PROVIDER`) afin de tester Gemini avec les providers de données mockés.
- [x] Secret monté et appel direct depuis le pod à `gemini-2.5-flash` réussi le 7 octobre ; permissions effectives fonctionnelles pour cette requête.
- [ ] Pour un usage durable/production, faire revoir par l'administrateur IAM le rôle minimal requis ; aucune attribution IAM supplémentaire n'a été nécessaire pour le test réussi.
- [ ] Tester le webhook complet avec `LLM_PROVIDER=gemini` et `DATA_PROVIDER=real` après CI,
  publication de l'image et mise à jour Flux ; vérifier le diagnostic et l'activité Keep.
- [ ] Implémenter Prometheus et Loki sur les vraies requêtes et labels ; confirmer les noms de services et exemples de données avec Fabian.
- [x] Accès sortant vers Vertex AI validé par l'appel réel ; valider séparément l'accès vers Grafana.
- [x] Brancher localement la pré-analyse et les activités `resolved` vers Keep ; tester groupes,
  fingerprints tardifs et idempotence avec transport HTTP simulé.
- [ ] Déployer et valider le retour agent → Keep en cluster avec le Secret existant et les scopes réels.
- [ ] Valider en cluster la collecte Alloy → Loki et la consultation des traces JSON dans Grafana.
- [ ] Capturer les payloads firing/resolved réels pour les fixtures de contrat. Fabian rapporte que le déclenchement et la résolution ont été testés sur la plateforme.
- [ ] Pour un besoin ultérieur seulement : décider si l'agent doit lire les workloads Kubernetes ; les logs et événements Kubernetes sont exclus du premier périmètre.
- [ ] Tester la NetworkPolicy depuis un autre namespace.

### Priorité normale

- [ ] Définir le catalogue de scénarios reproductibles (cause attendue, déclenchement et nettoyage) pour mesurer les diagnostics.
- [ ] Corriger la limite inotify du nœud qui fait perdre des logs (`too many open files`), selon le rapport Fabian.
- [ ] Retirer `pip` de l'image, ajouter un scan de sécurité et une reconstruction hebdomadaire.
- [ ] Documenter le contrat réel dans `poc-ai4ops/docs/agent-contract.md`.
- [x] Mettre à jour le README agent sur `AUDIT_DIR` et `/webhooks/alertmanager`.
- [x] Corréler `resolved` en mémoire et publier une activité dans Keep sans clôture automatique ;
  valider en cluster après déploiement.
- [x] Émettre sur stdout des événements JSON structurés, corrélés, bornés et expurgés ; les tests locaux ciblés passent.
- [ ] Valider en cluster la collecte Alloy → Loki et la consultation des événements dans Grafana après déploiement.
- [ ] (Piste différée) Réévaluer SQLite/API d'historique ou GitHub Issues seulement si un besoin distinct de celui couvert par Keep apparaît.

### Déjà connus grâce au dépôt ✅

- ~~Endpoints Prometheus/Loki~~ → proxy via Grafana API
- ~~Type de Kubernetes~~ → k3s confirmé
- ~~Conventions GitOps~~ → confirmées par le dépôt
- ~~Alertes et feature flags~~ → documentés dans `otel-demo-prometheusrule.yaml`
- ~~Label `service_name`~~ → confirmé dans les exemples du README
- ~~Endpoint interne Alertmanager → agent~~ → `http://ia4ops-agent.ia4ops.svc:8000/webhooks/alertmanager`
- ~~Publication image~~ → pipeline CI présente ; publication effective rapportée par Fabian

---

## 7. Chronologie des dépendances

```text
Maël peut démarrer maintenant (Tasks 1-4)
│
├── Tasks 1-7 : complètes
│
├── Task 8 — déploiement GitOps : en place (image, Flux, webhook, réseau entrant)
│   ├── Providers réels + RBAC K8s : à implémenter/configurer
│   └── Identité Gemini + sorties réseau : décision et validation requises
│
├── Défauts de cycle de vie : résolution, ID d'incident, log du résumé et documentation d'audit
│
├── Scénarios reproductibles + fiabilisation : nécessaires pour qualifier les résultats
│
└── Remédiation : étape ultérieure, après diagnostic fiable et définition des garde-fous
```

---

*Document de contexte plateforme — IA4Ops — octobre 2026*
