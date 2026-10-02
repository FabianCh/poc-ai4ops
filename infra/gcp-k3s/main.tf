locals {
  # Plage utilisée par Identity-Aware Proxy pour le TCP forwarding (SSH / tunnels).
  iap_source_range = "35.235.240.0/20"
  node_tag         = "${var.name}-node"
}

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------
resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com",
    "iap.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Réseau
# ---------------------------------------------------------------------------
resource "google_compute_network" "vpc" {
  name                    = "${var.name}-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "subnet" {
  name                     = "${var.name}-subnet"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

# IP publique statique : elle sert de point d'entrée unique pour toutes les
# applications exposées (Traefik / ServiceLB écoutent sur 80/443 du nœud).
resource "google_compute_address" "ingress" {
  name         = "${var.name}-ip"
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Firewall
# ---------------------------------------------------------------------------
resource "google_compute_firewall" "ingress_http" {
  name        = "${var.name}-allow-http-https"
  network     = google_compute_network.vpc.name
  description = "Exposition des applications (Traefik) sur Internet."
  direction   = "INGRESS"

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }

  source_ranges = var.ingress_source_ranges
  target_tags   = [local.node_tag]
}

resource "google_compute_firewall" "iap" {
  name        = "${var.name}-allow-iap"
  network     = google_compute_network.vpc.name
  description = "SSH et API Kubernetes via tunnel IAP."
  direction   = "INGRESS"

  allow {
    protocol = "tcp"
    ports    = ["22", "6443"]
  }

  source_ranges = [local.iap_source_range]
  target_tags   = [local.node_tag]
}

resource "google_compute_firewall" "admin" {
  # Sans plage explicite, GCP ouvrirait la règle à 0.0.0.0/0 : on ne la crée
  # que si des plages admin sont fournies.
  count = length(var.admin_source_ranges) > 0 ? 1 : 0

  name        = "${var.name}-allow-admin"
  network     = google_compute_network.vpc.name
  description = "Accès admin direct (SSH + API Kubernetes)."
  direction   = "INGRESS"

  allow {
    protocol = "tcp"
    ports    = ["22", "6443"]
  }

  source_ranges = var.admin_source_ranges
  target_tags   = [local.node_tag]
}
