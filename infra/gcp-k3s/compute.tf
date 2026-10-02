resource "google_compute_instance" "k3s" {
  name         = var.name
  machine_type = var.machine_type
  zone         = var.zone
  tags         = [local.node_tag]
  labels       = var.labels

  allow_stopping_for_update = true

  boot_disk {
    initialize_params {
      image  = var.boot_image
      size   = var.boot_disk_size_gb
      type   = var.boot_disk_type
      labels = var.labels
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.subnet.id

    access_config {
      nat_ip       = google_compute_address.ingress.address
      network_tier = "PREMIUM"
    }
  }

  metadata = {
    enable-oslogin = "TRUE"
    startup-script = templatefile("${path.module}/templates/startup.sh.tftpl", {
      external_ip          = google_compute_address.ingress.address
      k3s_channel          = var.k3s_channel
      k3s_version          = var.k3s_version
      cert_manager_version = var.cert_manager_version
      acme_email           = var.acme_email
    })
  }

  service_account {
    email  = google_service_account.node.email
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  scheduling {
    provisioning_model          = var.spot ? "SPOT" : "STANDARD"
    preemptible                 = var.spot
    automatic_restart           = !var.spot
    on_host_maintenance         = var.spot ? "TERMINATE" : "MIGRATE"
    instance_termination_action = var.spot ? "STOP" : null
  }

  depends_on = [google_project_iam_member.node]
}
