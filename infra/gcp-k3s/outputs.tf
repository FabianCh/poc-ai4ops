output "project_id" {
  description = "Projet GCP."
  value       = var.project_id
}

output "zone" {
  description = "Zone de la VM."
  value       = var.zone
}

output "instance_name" {
  description = "Nom de la VM k3s."
  value       = google_compute_instance.k3s.name
}

output "external_ip" {
  description = "IP publique statique (entrée des applications et de l'API Kubernetes)."
  value       = google_compute_address.ingress.address
}

output "ingress_base_domain" {
  description = "Domaine wildcard résolu vers l'IP publique (via sslip.io) : <app>.<ingress_base_domain>."
  value       = "${google_compute_address.ingress.address}.sslip.io"
}

output "ssh_command" {
  description = "Commande SSH (via IAP)."
  value       = "gcloud compute ssh ${google_compute_instance.k3s.name} --project ${var.project_id} --zone ${var.zone} --tunnel-through-iap"
}

output "bootstrap_logs_command" {
  description = "Suivre l'installation de k3s sur la VM."
  value       = "gcloud compute ssh ${google_compute_instance.k3s.name} --project ${var.project_id} --zone ${var.zone} --tunnel-through-iap --command 'sudo tail -f /var/log/k3s-bootstrap.log'"
}

output "demo_url" {
  description = "URL de l'application de démo (déployée par Flux quelques minutes après le boot)."
  value       = "https://whoami.${google_compute_address.ingress.address}.sslip.io"
}

output "grafana_url" {
  description = "URL de Grafana (utilisateur admin, mot de passe dans le secret monitoring/kube-prometheus-stack-grafana)."
  value       = "https://grafana.${google_compute_address.ingress.address}.sslip.io"
}

output "otel_demo_url" {
  description = "URL de l'OpenTelemetry Demo (boutique, /feature, /jaeger/ui, /loadgen)."
  value       = "https://otel-demo.${google_compute_address.ingress.address}.sslip.io"
}
