# Coûts du POC (Google Cloud)

Estimation au **tarif public**, région `europe-west1` (Belgique), en **USD hors taxes**, relevée en
octobre 2026. Les prix évoluent : vérifier avec le
[Google Cloud Pricing Calculator](https://cloud.google.com/products/calculator) avant de s'engager.

## Ressources facturées

Ressources créées par `infra/gcp-k3s` avec les valeurs par défaut :

| Ressource | Tarif unitaire | Facturée quand |
| --- | --- | --- |
| VM `e2-standard-4` (4 vCPU, 16 Go), à la demande | ~0,147 $/h | la VM tourne |
| VM `e2-standard-4` en **Spot** (`spot = true`) | ~0,068 $/h (variable, peut être préemptée) | la VM tourne |
| Disque `pd-balanced` 50 Go (OS + volumes Prometheus / Loki / Alertmanager) | 0,10 $/Go/mois, soit ~5 $/mois | **toujours**, même VM arrêtée |
| IP externe statique **attachée** à une VM qui tourne | ~0,005 $/h, soit ~3,65 $/mois | la VM tourne |
| IP externe statique **réservée non utilisée** (VM arrêtée) | ~0,01 $/h, soit ~7,30 $/mois | la VM est arrêtée |
| Trafic sortant Internet (navigation Grafana / boutique) | ~0,12 $/Gio | à l'usage, négligeable pour le POC (< 1 $/mois) |

Keep (4 pods : backend, frontend, websocket, MySQL) ajoute environ 1,5 Go de RAM demandée et un
PVC de 2 Go (~0,20 $/mois) : à surveiller si des pods passent `Pending` (voir la note sur `e2-standard-8`).

Gratuit : IAP (SSH, tunnels), Cloud Shell, VPC et règles firewall, sslip.io, certificats Let's
Encrypt, repo GitHub public. La VM n'a pas de service account : pas de Cloud Logging/Monitoring
facturé. Les machines E2 ne bénéficient pas des remises automatiques d'utilisation prolongée.

## Scénarios

| Scénario | VM à la demande | VM Spot |
| --- | --- | --- |
| **24 h/24, 7 j/7** (≈ 730 h/mois) | **~116 $/mois** (107 VM + 5 disque + 3,65 IP) | **~58 $/mois** (50 VM + 5 + 3,65) |
| **Une journée complète** (24 h), puis `make destroy` | **~3,80 $** | **~1,90 $** |
| **Une journée de travail** (8 h), puis `make destroy` | **~1,30 $** | **~0,65 $** |
| VM **arrêtée** entre deux sessions (`gcloud compute instances stop`) | ~12 $/mois (disque 5 + IP réservée 7,30) | idem |
| Infrastructure **détruite** (`make destroy`) | 0 $ | 0 $ |

Exemple : 2 journées de travail par semaine (8 h), en gardant la VM arrêtée le reste du temps :
~8,7 jours × 8 h × 0,147 $ + ~12 $ ≈ **22 $/mois** (à la demande).

> En cas de manque de RAM (pods `Pending`), passer à `e2-standard-8` (8 vCPU, 32 Go) double
> environ le coût de la VM (~0,29 $/h, estimation non vérifiée).

## Recommandations

- **Usage ponctuel** : `make apply` en début de session, `make destroy` en fin de session.
  Coût nul entre deux sessions, mais :
  - le bootstrap complet (k3s, Flux, monitoring, OTel Demo) prend ~10-15 min ;
  - l'**IP publique change** à chaque recréation : URLs différentes, nouveau mot de passe Grafana
    (voir [cloudshell.md](cloudshell.md)) ;
  - l'historique des métriques et des logs est perdu.
- **Usage régulier sur plusieurs semaines** : arrêter la VM entre les sessions
  (`gcloud compute instances stop/start`, ~12 $/mois à l'arrêt). L'IP, les URLs, le mot de passe
  Grafana et l'historique sont conservés ; tout redémarre seul au `start`.
- **VM Spot** (`spot = true` dans `terraform.tfvars`) : -55 % environ, acceptable pour un POC,
  mais la VM peut être arrêtée à tout moment par Google (elle est alors stoppée, pas supprimée,
  et un simple `start` la relance).
- **Garde-fou** : créer une alerte budgétaire sur le projet
  (Facturation > Budgets et alertes, par exemple 30 $/mois).

## Sources

- Prix e2-standard-4 europe-west1 (à la demande / Spot) : [Holori GCP calculator](https://calculator.holori.com/gcp/vm/e2-standard-4/europe-west1?os=Linux), [DevZero](https://www.devzero.io/instances/gcp/e2-standard-4)
- Disque pd-balanced europe-west1 : [gcloud-compute.com](https://gcloud-compute.com/pd-balanced.html)
- IP externes : [Google Cloud VPC pricing](https://cloud.google.com/vpc/network-pricing), [DoiT : No more free external IPs](https://www.doit.com/blog/no-more-free-external-ips-on-google-cloud-how-much-will-it-cost-you)
- Grille officielle VM : [Compute Engine pricing](https://cloud.google.com/compute/vm-instance-pricing)
