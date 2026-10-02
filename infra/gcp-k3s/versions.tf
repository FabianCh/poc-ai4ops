terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
  }

  # State local par défaut. Pour partager le state, copier backend.tf.example
  # en backend.tf et renseigner un bucket GCS.
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}
