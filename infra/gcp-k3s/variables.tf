variable "project_id" {
  description = "ID du projet Google Cloud cible."
  type        = string
}

variable "region" {
  description = "Région GCP."
  type        = string
  default     = "europe-west1"
}

variable "zone" {
  description = "Zone GCP de la VM."
  type        = string
  default     = "europe-west1-b"
}

variable "name" {
  description = "Préfixe de nommage des ressources (VM, réseau, IP, firewall...)."
  type        = string
  default     = "ai4ops-k3s"

  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,40}[a-z0-9])?$", var.name))
    error_message = "Le nom doit respecter le format GCP : minuscules, chiffres et tirets, 42 caractères max."
  }
}

variable "machine_type" {
  description = "Type de machine Compute Engine."
  type        = string
  default     = "e2-standard-4"
}

variable "boot_image" {
  description = "Image de boot de la VM."
  type        = string
  default     = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
}

variable "boot_disk_size_gb" {
  description = "Taille du disque de boot (Go)."
  type        = number
  default     = 50
}

variable "boot_disk_type" {
  description = "Type de disque de boot."
  type        = string
  default     = "pd-balanced"
}

variable "spot" {
  description = "Utiliser une VM Spot (beaucoup moins chère, mais peut être préemptée à tout moment)."
  type        = bool
  default     = false
}

variable "subnet_cidr" {
  description = "Plage CIDR du sous-réseau dédié."
  type        = string
  default     = "10.10.0.0/24"
}

variable "ingress_source_ranges" {
  description = "Plages autorisées à joindre les applications exposées (HTTP/HTTPS)."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "admin_source_ranges" {
  description = <<-EOT
    Plages autorisées à joindre directement l'API Kubernetes (6443) et SSH (22),
    typiquement votre IP publique en /32. Si vide, l'accès admin se fait uniquement
    via IAP (gcloud compute ssh --tunnel-through-iap / start-iap-tunnel).
  EOT
  type        = list(string)
  default     = []
}

variable "k3s_channel" {
  description = "Canal de release k3s (stable, latest, v1.33...). Ignoré si k3s_version est renseigné."
  type        = string
  default     = "stable"
}

variable "k3s_version" {
  description = "Version exacte de k3s à installer (ex: v1.33.4+k3s1). Vide = dernière version du canal."
  type        = string
  default     = ""
}

variable "flux_git_url" {
  description = "Repo Git (public) synchronisé par Flux. Vide = ne pas installer Flux."
  type        = string
  default     = "https://github.com/FabianCh/poc-ai4ops"
}

variable "flux_branch" {
  description = "Branche Git synchronisée par Flux."
  type        = string
  default     = "main"
}

variable "flux_version" {
  description = "Version de Flux installée au premier démarrage (même version que manifest/flux-system/gotk-components.yaml)."
  type        = string
  default     = "v2.9.5"
}

variable "labels" {
  description = "Labels appliqués aux ressources."
  type        = map(string)
  default = {
    project = "poc-ai4ops"
    managed = "terraform"
  }
}
