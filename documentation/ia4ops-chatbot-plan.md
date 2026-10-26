# IA4Ops Chat — cadrage fonctionnel et plan prévisionnel

> **Statut au 26 octobre 2026** : cadrage validé le 15 octobre ; étapes 1 à 3 implémentées,
> déploiement privé (étape 4) en place et testé par tunnel le 16 octobre, diagnostic Gemini et données
> réelles actifs. Restent : authentification, persistance des alertes en attente, validation
> navigateur/multi-ops et étape 5 (démonstration rejouable). Voir `ia4ops-progress.md`.
> **Projet de référence** : `poc-ai4ops/ia4ops-agent/` reste la version stable.
> **Nouvelle version** : copie indépendante en cours dans `poc-ai4ops/ia4ops-agent-chat/`.
> **Principe directeur** : diagnostic en lecture seule, investigation déclenchée ou approuvée par un opérateur.
> **Mode de développement convenu** : diagnostic LLM mock et Prometheus/Loki réels ;
> interpréteur naturel désactivé par défaut et activé explicitement pour les essais Gemini.

## 1. Objectif

Créer une vitrine chatbot destinée aux ops, afin qu'ils puissent demander une investigation
d'incident à partir des données d'observabilité et consulter un diagnostic sourcé. La nouvelle
version reprend le code de l'agent existant, mais évolue et se déploie indépendamment.

Le périmètre vise deux parcours :

1. l'opérateur demande une investigation depuis le chat ;
2. Alertmanager signale une alerte à la nouvelle version ; le chat la présente comme une
   investigation en attente, puis ne lance le diagnostic qu'après confirmation explicite d'un
   opérateur.

## 2. Périmètre fonctionnel approuvé

### Investigation à la demande

- L'opérateur décrit sa demande en langage naturel ; un interpréteur à sortie JSON contrainte en
  extrait le service, la fenêtre et la question, puis l'IHM les fait confirmer avant le lancement.
- La commande structurée `/investigate <service> [minutes] | <question>` reste disponible comme
  raccourci et solution de repli.
- Le fournisseur d'interprétation est configuré indépendamment du LLM de diagnostic ; il est
  désactivé par défaut et ne peut pas déclencher une investigation.
- Le backend utilise le workflow LangGraph et les clients/providers copiés dans la nouvelle version.
- Les données proviennent des APIs Loki et Prometheus via le proxy Grafana, en lecture seule.
- Le LLM de diagnostic reste en mock pendant le développement et les essais ordinaires. Le nouvel
  interpréteur est désactivé par défaut ; son activation explicite pour une démonstration utilise
  Vertex AI pour extraire les paramètres, sans activer le diagnostic Gemini. Les providers
  Prometheus/Loki restent réels.
- Les requêtes sont construites par le code à partir de paramètres bornés et de services autorisés ;
  le LLM ne reçoit pas un accès libre à LogQL, PromQL, Grafana ou au shell.
- Le résultat présente un résumé, les observations et leurs références, les limites/données
  manquantes et des hypothèses prudentes.
- L'agent peut suggérer des vérifications et des pistes de remédiation, mais ne les exécute jamais.

### Alerte Alertmanager et approbation de l'investigation

- La nouvelle version dispose de son propre webhook Alertmanager et répond rapidement en 2xx.
- Le routage Alertmanager envoie les alertes à la version stable existante et à la nouvelle version ;
  la route stable n'est pas remplacée.
- La nouvelle version enregistre l'alerte comme « en attente » et la rend visible dans le chat.
- Le diagnostic ne commence qu'après une action explicite d'un opérateur (investiguer / ignorer).
- Une alerte `resolved` met à jour l'état correspondant ; elle ne déclenche pas une nouvelle
  investigation.
- Les notifications répétées sont dédupliquées selon le contrat existant (`fingerprint` +
  `startsAt`).

**Conséquence à prévoir** : la version stable continue son traitement actuel en parallèle. Si un ops
accepte ensuite l'investigation dans le chatbot, les deux versions peuvent produire leur propre
diagnostic mocké. Aucun appel Gemini n'est prévu pendant les essais ordinaires. Une activation
ultérieure de Gemini dans l'une ou l'autre version peut faire deux appels pour le même incident ;
elle devra être explicite et son coût contrôlé.

## 3. Architecture et isolation prévues

```text
Alertmanager ──┬──> ia4ops-agent stable (comportement inchangé)
               └──> ia4ops-agent-chat / webhook rapide
                                  │
                                  ├──> alerte en attente
                                  │       └──> confirmation ops dans Chainlit
                                  │                └──> workflow LangGraph
                                  └──> chat à la demande ──> workflow LangGraph
                                                              ├──> Prometheus
                                                              ├──> Loki
                                                              └──> LLM mock (Gemini uniquement sur activation explicite)
```

- Copier le projet Python dans `poc-ai4ops/ia4ops-agent-chat/` ; ne pas modifier l'agent stable
  pour les besoins de la nouvelle interface.
- Chainlit fournit l'interface ; FastAPI conserve les endpoints métier/webhook ; LangGraph orchestre
  les investigations. Les contrats précis entre l'interface et l'API seront définis avant le code.
- Appliquer le [guide de direction artistique de l'IHM](../GUIDE-DIRECTION-ARTISTIQUE-IHM.md)
  à toute évolution visuelle Chainlit.
- Construire et publier une image dédiée à la nouvelle application, avec un nom et des tags
  distincts de ceux de `ia4ops-agent`.
- Ajouter des manifests de déploiement distincts, dans un namespace dédié recommandé (nom à
  confirmer), avec Services et politiques réseau propres. L'agent stable et son Service restent
  inchangés.
- Référencer les secrets existants ou dédiés via Kubernetes ; ne copier aucun `.env`, credential,
  fichier d'audit local ou secret dans le dépôt.
- Ne donner aucun droit d'écriture Kubernetes à la nouvelle version. Les accès de données restent
  bornés à Grafana/Prometheus/Loki.
- Protéger l'interface par un contrôle d'accès avant toute exposition publique. Le mécanisme
  d'authentification est à décider avant le déploiement de la vitrine.

## 4. Plan prévisionnel et critères de sortie

### Étape 0 — Figer et inventorier la référence

- Base de la copie confirmée : commit stable `ebc2221` du 15 octobre 2026.
- [x] Vérifier le dépôt stable propre au commit source et ne pas modifier l'application ou son déploiement stable.
- Définir précisément les exclusions de la copie (secrets, `.env`, audit logs et fichiers locaux).

**État** : terminé. Source propre au commit `ebc2221`, présent dans l'historique Git. La copie
initiale exclut `.env`, `credentials/`, `audit_logs/`, `.venv/` et les caches.

### Étape 1 — Créer et isoler la copie

- [x] Créer `poc-ai4ops/ia4ops-agent-chat/` depuis le code source de l'agent stable.
- [x] Séparer l'identité du projet installé, du nom affiché par l'API, de la commande et des
  événements d'audit ; les imports Python internes restent inchangés dans cette application isolée.
- [x] Exclure `.env`, credentials, données d'audit locales, environnements virtuels et caches.
- [x] Lancer la suite héritée et mettre à jour/vérifier le lockfile.
- [x] Ajouter Chainlit avec `uv`, verrouiller `uv.lock` et conserver les tests existants.
- Ajouter une CI et une image distinctes ; les pull requests exécutent les tests/builds sans déployer
  ni publier une image de production.

**Sortie attendue** : copie isolée, suite de tests verte, image identifiable par commit et aucun
changement de comportement requis sur l'agent stable.

**Validation du socle copiée** : `uv sync --locked --extra dev` réussi et 246 tests passés.
Les fichiers modifiés passent Ruff ciblé. Le lint complet retourne 22 erreurs, identiques en
nombre et catégories dans le projet source ; elles ne sont pas introduites par la copie.

### Étape 2 — Chat et investigation manuelle

- [x] Monter Chainlit sur FastAPI sous `/chat/` et définir l'API `POST /api/v1/investigations`.
- [x] Borne d'entrée : identifiant de service (63 caractères, charset restreint), namespace
  `otel-demo`, fenêtre 1–60 minutes et question limitée à 500 caractères.
- [x] Transmettre la fenêtre choisie aux collecteurs métriques, traces, logs et événements cluster.
- [x] Réutiliser le graphe LangGraph et présenter séparément les observations collectées, le
  diagnostic, les données manquantes et les suggestions non exécutées.
- [x] Afficher un avertissement explicite lorsque FakeLLM est utilisé ; ne pas présenter ses
  éléments préconfigurés comme des observations de la collecte.
- [ ] Valider l'expérience interactive dans un navigateur avec `DATA_PROVIDER=real` et Grafana.
- [ ] Ajouter l'authentification avant de rendre l'interface accessible hors d'un réseau local
  ou de test protégé.

**État** : parcours local et contrat couverts par tests avec providers mockés. Les collectes réelles
et l'expérience navigateur restent à valider ; aucune exposition publique n'est autorisée sans
authentification.

### Étape 3 — Alertes en attente et décision humaine

- [x] Ajouter le webhook de la copie, avec validation, déduplication et réponse 2xx rapide.
- [x] Enregistrer les alertes firing comme éléments en attente et les rendre visibles dans les
  sessions Chainlit actives ainsi qu'à l'ouverture d'une session.
- [x] Faire démarrer le graphe uniquement après confirmation explicite ; permettre d'ignorer l'alerte.
- [x] Corréler les résolutions et ne pas démarrer de diagnostic si l'alerte est résolue avant décision.
- [x] Couvrir les notifications répétées, l'approbation, l'ignorance et la résolution anticipée par tests.
- [ ] Valider le polling et les actions Chainlit en navigateur, dont plusieurs ops connectés.
- [ ] Décider et tester la persistance des alertes en attente après redémarrage.

**État** : parcours API et IHM implémentés ; alertes en attente et cache de déduplication conservés
en mémoire, donc perdus au redémarrage. La validation navigateur, la persistance et le comportement
multi-ops restent à faire. Aucune investigation n'est lancée par le webhook seul.

### Étape 4 — Déploiement isolé

- [x] Ajouter namespace, Deployment, Service ClusterIP, PVC d'audit et NetworkPolicies propres à
  la copie ; aucun Ingress n'est créé.
- [x] Ajouter la Kustomization Flux et un workflow dédié de tests et publication GHCR. Le premier
  déploiement utilise le mode mock et n'exige aucun secret.
- [x] Configurer le routage Alertmanager en parallèle sans retirer le receiver stable ; les faux
  webhooks peuvent toujours être envoyés manuellement via le tunnel.
- [x] Limiter l'accès réseau du pod à Alertmanager en ingress et DNS en egress ; le port-forward
  local est l'unique accès utilisateur prévu.
- [ ] Valider la réconciliation Flux, le port-forward et un webhook synthétique dans le cluster.

**État** : manifests et workflow prêts dans le dépôt ; le déploiement effectif reste à faire après
publication de l'image sur GHCR, création hors Git des Secrets Gemini/Grafana et réconciliation
Flux. Le profil chatbot est maintenant configuré avec Gemini pour diagnostic et interprétation,
et avec les providers réels pour métriques/logs/traces ; le provider Kubernetes (lecture seule,
`otel-demo`, ServiceAccount dédié) a été ajouté le 19 octobre, rollout cluster à confirmer.
`make lint` reste la validation requise avant commit.

### Étape 5 — Validation de bout en bout et démonstration

- Tester un scénario manuel avec mocks puis avec Loki/Prometheus réels.
- Confirmer que les deux versions utilisent le LLM mock pendant les essais ordinaires et qu'aucun
  appel Vertex AI n'est observé ; une évaluation Gemini éventuelle est déclenchée séparément.
- Tester une alerte synthétique reçue en parallèle par les deux versions, en vérifiant l'absence
  d'investigation chatbot avant acceptation.
- Vérifier l'affichage, les preuves, les erreurs, le traitement `resolved`, les traces/audits,
  l'isolation réseau, les limites de charge et le coût Gemini.
- Comparer les résultats de diagnostic aux scénarios reproductibles existants.

**Sortie attendue** : démonstration rejouable, version stable inchangée, critères de réussite
documentés et limites connues explicites.

## 5. Décisions techniques à prendre avant les étapes concernées

| Sujet | Proposition de travail | À confirmer |
|---|---|---|
| Nom du namespace et URLs | Namespace isolé `ia4ops-agent-chat`, accès par port-forward loopback, sans Ingress | Confirmé |
| État des alertes en attente | Persistance au-delà de la session et des redémarrages | Choix du stockage ; SQLite/PVC peut convenir au POC mono-réplique |
| Notification Chainlit | Message dans les sessions actives et liste à la reconnexion | Valider le mécanisme Chainlit et la gestion multi-ops |
| Accès utilisateur | Authentification requise avant exposition | Mécanisme et périmètre d'accès |
| Routage Alertmanager | Route parallèle vers le chatbot et l'agent stable ; webhooks synthétiques possibles via port-forward | Confirmé ; diagnostics mock pour éviter les appels Gemini |
| Utilisation Gemini | Diagnostic mock par défaut ; interpréteur configurable séparément | Activer Vertex AI uniquement pour une démonstration ou un test ciblé |
| Processus UI/API | Contrat HTTP interne entre Chainlit et FastAPI | Confirmer le packaging et le mode d'exécution le plus simple à déployer |

## 6. Hors périmètre de cette version

- Exécution de commandes, remédiation automatique ou modification de feature flags.
- Écriture dans Kubernetes, GitOps ou les systèmes observés.
- Accès libre du LLM aux APIs Grafana, aux requêtes arbitraires ou au shell.
- Remplacement de l'agent stable avant validation formelle de la nouvelle version.
- Multi-agent, catalogue exécutable de remédiations et approbation d'actions d'écriture.

## 7. Références

- État de la version stable et travaux de raccordement : [ia4ops-progress.md](./ia4ops-progress.md)
- Architecture de l'agent actuel : [ia4ops-langgraph-architecture.md](./ia4ops-langgraph-architecture.md)
- Contrat webhook : [ia4ops-webhook-contract.md](./ia4ops-webhook-contract.md)
- Contexte de la plateforme et endpoints : [ia4ops-platform-context.md](./ia4ops-platform-context.md)
- Conventions du dépôt : [poc-ai4ops/CLAUDE.md](../CLAUDE.md)
- Direction artistique de l'IHM : [poc-ai4ops/GUIDE-DIRECTION-ARTISTIQUE-IHM.md](../GUIDE-DIRECTION-ARTISTIQUE-IHM.md)
