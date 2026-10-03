output "gcp_project_id" {
  value       = var.project_id
  description = "Production application project ID."
}

output "gke_cluster_name" {
  value       = google_container_cluster.production.name
  description = "Production GKE Autopilot cluster name."
}

output "gke_location" {
  value       = google_container_cluster.production.location
  description = "Production GKE region."
}

output "gke_dns_endpoint" {
  value       = google_container_cluster.production.control_plane_endpoints_config[0].dns_endpoint_config[0].endpoint
  description = "DNS-only GKE control-plane endpoint."
}

output "github_workload_identity_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Full Workload Identity Provider resource name for GitHub Actions."
}

output "github_deploy_service_account" {
  value       = google_service_account.github_deployer.email
  description = "GCP service account impersonated by the production GitHub deployment workflow."
}

output "cloud_sql_instance_connection_name" {
  value       = google_sql_database_instance.production.connection_name
  description = "Cloud SQL instance connection name."
}

output "cloud_sql_private_ip" {
  value       = google_sql_database_instance.production.private_ip_address
  description = "Private IP used by GKE workloads to reach PostgreSQL."
}

output "cloud_sql_database_name" {
  value       = google_sql_database.application.name
  description = "Application database name."
}

output "application_secret_ids" {
  value       = sort(keys(google_secret_manager_secret.application))
  description = "Secret Manager containers that require versions to be populated out of band."
}

output "audit_anchor_project_id" {
  value       = var.audit_anchor_project_id
  description = "Independent project containing WORM audit-anchor resources."
}

output "audit_anchor_bucket" {
  value       = google_storage_bucket.audit_anchor.name
  description = "External audit-anchor WORM bucket."
}

output "audit_anchor_bucket_locked" {
  value       = var.lock_audit_anchor_bucket
  description = "Whether the irreversible Cloud Storage retention-policy lock was requested."
}

output "audit_anchor_service_account" {
  value       = google_service_account.audit_anchor.email
  description = "Service account reserved for the external Audit Anchor service."
}

output "audit_anchor_secret_ids" {
  value       = sort(keys(google_secret_manager_secret.audit_anchor))
  description = "Audit project Secret Manager containers that require versions to be populated out of band."
}
