# IA4Ops — Contrat d'interface Webhook Alertmanager

> **Source** : plan de Fabian Chauvin + standard Alertmanager v4  
> **Date** : octobre 2026  
> **Usage** : contrat d'entrée de la partie agentique  
> **Statut** : contrat d'implémentation en place ; Fabian rapporte que firing et resolved ont été testés en réel. Les payloads JSON réels ne sont pas encore présents dans les fixtures du dépôt.

---

## 1. Endpoint de réception

```http
POST /webhooks/alertmanager
Content-Type: application/json
```

> **Endpoint interne configuré dans le dépôt** : `http://ia4ops-agent.ia4ops.svc:8000/webhooks/alertmanager`. Pour les tests locaux, utiliser `http://localhost:8000/webhooks/alertmanager`.

### Comportement attendu

- Répondre **2xx immédiatement** (< 1s) — Alertmanager réessaie si pas de réponse rapide
- **Traitement asynchrone** : accuser réception, puis exécuter le workflow LangGraph en arrière-plan
- Réponse : `{"incident_id": "...", "status": "accepted"}`

---

## 2. Format du payload — Alertmanager v4

### Schéma complet

```json
{
  "version": "4",
  "groupKey": "{}/{namespace=\"otel-demo\"}:{namespace=\"otel-demo\"}",
  "truncatedAlerts": 0,
  "status": "firing",
  "receiver": "ai4ops-agent",
  "groupLabels": {
    "namespace": "otel-demo"
  },
  "commonLabels": {
    "namespace": "otel-demo",
    "alertname": "OtelDemoServiceHighErrorRate"
  },
  "commonAnnotations": {},
  "externalURL": "http://kube-prometheus-stack-alertmanager.monitoring:9093",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "OtelDemoServiceHighErrorRate",
        "service_name": "product-catalog",
        "severity": "critical",
        "namespace": "otel-demo"
      },
      "annotations": {
        "summary": "High error rate on product-catalog",
        "description": "Error rate exceeded threshold. Pistes : Jaeger, Loki, Prometheus."
      },
      "startsAt": "2026-10-02T18:41:26Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://.../graph?g0.expr=...",
      "fingerprint": "a1b2c3d4e5f6..."
    }
  ]
}
```

### Champs clés

| Champ | Type | Description | Obligatoire |
|---|---|---|---|
| `version` | string | Toujours `"4"` pour Alertmanager v4 | ✅ |
| `status` | `"firing"` \| `"resolved"` | État du groupe d'alertes | ✅ |
| `receiver` | string | Nom du receiver Alertmanager (`"ai4ops-agent"`) | ✅ |
| `groupLabels` | object | Labels de regroupement (ex: `{"namespace": "otel-demo"}`) | ✅ |
| `commonLabels` | object | Labels communs à toutes les alertes du groupe | ✅ |
| `alerts` | array | Liste des alertes individuelles du groupe | ✅ |
| `alerts[].fingerprint` | string | Identifiant stable de l'alerte — clé de déduplication | ✅ |
| `alerts[].startsAt` | ISO 8601 | Début de l'alerte | ✅ |
| `alerts[].endsAt` | ISO 8601 | Fin de l'alerte (`0001-01-01...` = non résolue) | ✅ |
| `alerts[].labels` | object | Labels de l'alerte (service, sévérité, namespace, etc.) | ✅ |
| `alerts[].annotations` | object | Texte descriptif (summary, description) | optionnel |
| `truncatedAlerts` | int | Nombre d'alertes tronquées (si `max_alerts` configuré) | ✅ |

### Sémantique importante

**Une notification = un groupe d'alertes**, pas une seule alerte.

Avec `group_by: [namespace]`, si `product-catalog`, `checkout` et `frontend` tombent simultanément, l'agent reçoit **une seule notification** avec les 3 alertes dans `alerts[]`. C'est voulu : permet d'identifier la cause racine vs les impacts en cascade.

**Idempotence** : Alertmanager renvoie le webhook selon `group_interval` (5 min) si l'état change, et `repeat_interval` (4h) pour rappel. Les notifications `firing` répétées sont ignorées avec la clé composite `fingerprint` + `startsAt`.

**Résolution** : avec `send_resolved: true`, Alertmanager envoie une notification avec `status: "resolved"` et `alerts[].endsAt` renseigné. L'agent associe cette notification à l'incident firing correspondant, met à jour `alert_status` et `resolved_at`, puis répond sans relancer le diagnostic. Une résolution sans incident connu est acquittée avec `status: "resolved_unmatched"` et ne crée pas d'incident. La corrélation étant conservée en mémoire, un redémarrage ou l'éviction de l'entrée peut rendre une résolution orpheline.

---

## 3. Modèle Pydantic pour la réception

```python
from pydantic import BaseModel
from typing import Literal
from datetime import datetime

class AlertLabels(BaseModel):
    alertname: str
    namespace: str
    severity: str | None = None
    service_name: str | None = None  # label OTel — à confirmer avec Fabian
    # autres labels selon la configuration Alertmanager

class AlertAnnotations(BaseModel):
    summary: str | None = None
    description: str | None = None

class AlertItem(BaseModel):
    status: Literal["firing", "resolved"]
    labels: AlertLabels
    annotations: AlertAnnotations = AlertAnnotations()
    startsAt: datetime
    endsAt: datetime
    generatorURL: str = ""
    fingerprint: str  # clé de déduplication

class AlertmanagerWebhook(BaseModel):
    version: Literal["4"]
    groupKey: str
    truncatedAlerts: int = 0
    status: Literal["firing", "resolved"]
    receiver: str
    groupLabels: dict[str, str]
    commonLabels: dict[str, str]
    commonAnnotations: dict[str, str] = {}
    externalURL: str = ""
    alerts: list[AlertItem]
```

### Clé de déduplication

```python
def make_dedup_key(webhook: AlertmanagerWebhook) -> str:
    """Clé composite pour ignorer les notifications répétées du même incident."""
    fingerprints = sorted(a.fingerprint for a in webhook.alerts)
    starts = min(a.startsAt for a in webhook.alerts).isoformat()
    return f"{'-'.join(fingerprints)}:{starts}"
```

---

## 4. Les 6 étapes de traitement (plan Fabian)

Ce découpage est le plan cible complet pour les scénarios 1, 2 et 3. Le scénario 1 couvre uniquement les étapes 1 à 3 (sans exécution ni remédiation).

| # | Étape | Scénario | Sortie interne |
|---|---|---|---|
| **1** | **Réception** (intake) | 1, 2, 3 | `Incident {id, status, alerts[], firstSeen, lastSeen}` |
| **2** | **Enrichissement** | 1, 2, 3 | `Context {metrics, logs, traces, events, flags, changes}` |
| **3** | **Diagnostic** (LLM, lecture seule) | 1, 2, 3 | `Diagnosis {rootCause, impacted[], evidence[], confidence}` |
| **4** | **Décision** (catalogue d'actions) | 2, 3 | `RemediationPlan {action, params, risk, requiresApproval}` |
| **5** | **Exécution** (feature flag / kubectl / GitOps) | 2 | `ActionResult {status, details}` |
| **6** | **Vérification et audit** | 2 | `Outcome {resolved, duration, report}` |

### Étape 1 — Réception

- Valider le payload v4
- Ignorer les alertes `Watchdog` (alerte de heartbeat Alertmanager — à ne pas traiter)
- Dédupliquer par `fingerprint` + `startsAt`
- Créer ou mettre à jour un incident avec un `incident_id`
- Répondre **200 immédiatement**

### Étape 2 — Enrichissement (scénario 1)

Sources à collecter **au moment de l'alerte** (pas uniquement au moment de la détection) :

| Source | Outil | Fenêtre |
|---|---|---|
| Taux d'erreur et latence | Prometheus — PromQL | 1-15 min |
| Logs d'erreur | Loki — LogQL | 15 min |
| État des pods et events | Kubernetes API | instantané |
| Feature flags actifs | flagd API | instantané |
| Derniers déploiements | Flux CD / Git history | 24h |

> **Note** : les traces Jaeger/Tempo ne sont pas disponibles pour le scénario 1.

### Étape 3 — Diagnostic (scénario 1)

- LLM en lecture seule (Gemini Flash via Vertex AI)
- Entrée : contexte structuré et borné (voir `ia4ops_scenario1_agentic_context.md` section 11)
- Sortie : `DiagnosticOutput` Pydantic validé (voir section 12 du même document)
- `action_executed` doit toujours être `False` dans le scénario 1

### Catalogue d'actions (scénarios 2+)

| Alerte | Action candidate |
|---|---|
| `OtelDemoServiceHighErrorRate`, `HighLatency` | Désactiver le feature flag fautif (rollback de config) |
| `OtelDemoContainerOOMKilled`, `MemoryNearLimit` | `rollout restart` du deployment, puis hausse de la limite mémoire par PR GitOps |
| `OtelDemoContainerHighCpu` | Désactiver `adHighCpu`, sinon scale out |
| `OtelDemoKafkaConsumerLag` | Désactiver `kafkaQueueProblems`, sinon restart des consumers |

---

## 5. Configuration Alertmanager à appliquer (Fabian)

Fichier : `manifest/base/kube-prometheus-stack/kube-prometheus-stack-helmrelease.yaml`

```yaml
alertmanager:
  config:
    global:
      resolve_timeout: 5m
    route:
      group_by: ["namespace"]
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 12h
      receiver: "null"
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
            max_alerts: 0
```

---

## 6. Vérification locale (sans cluster)

```bash
# Simuler un payload firing — cas productCatalogFailure
curl -X POST "http://localhost:8000/webhooks/alertmanager" \
  -H "Content-Type: application/json" \
  --data @tests/fixtures/alerts/alertmanager_v4_firing.json

# Simuler la résolution
curl -X POST "http://localhost:8000/webhooks/alertmanager" \
  -H "Content-Type: application/json" \
  --data @tests/fixtures/alerts/alertmanager_v4_resolved.json

# Consulter le résultat
curl "http://localhost:8000/api/v1/incidents/<incident_id>"
```

---

## 7. Payload réel à capturer (action Fabian)

Les tests firing et resolved ont été rapportés par Fabian. Pour rendre le contrat reproductible dans le dépôt, il reste à fournir/capturer les payloads JSON réels et à les ajouter comme fixtures :

1. Activer `productCatalogFailure` via `POST /feature/api/write`.
2. Récupérer les notifications firing et resolved dans les logs de l'agent/Alertmanager.
3. Les ajouter dans `poc-ai4ops/ia4ops-agent/tests/fixtures/alerts/` :
   - `alertmanager_v4_real_firing.json`
   - `alertmanager_v4_real_resolved.json`
4. Ajouter les tests de contrat sur ces payloads.
5. Désactiver le flag et restaurer l'état initial.

Les fixtures synthétiques existantes restent utiles ; les payloads réels doivent les compléter,
pas nécessairement les remplacer.

---

## 8. Points à confirmer avec Fabian

- [ ] Nom exact du label service dans Alertmanager : `service_name` ou `service` ou autre ?
- [ ] Autres labels présents dans les alertes OTel (pour mettre à jour `AlertLabels`)
- [ ] Annotations présentes dans les alertes réelles (summary, description, runbook_url ?)
- [ ] Format exact de `groupKey` généré par la configuration réelle
- [x] URL interne configurée dans le dépôt : `ia4ops-agent.ia4ops.svc:8000`
- [ ] Comportement souhaité pour les alertes hors namespace `otel-demo`
- [x] Comportement de clôture/corrélation pour `resolved` ; ne lance pas un nouveau diagnostic
- [x] Identifiant d'incident conservé entre l'accusé webhook et le rapport final

---

*Contrat webhook Alertmanager — IA4Ops — octobre 2026*
