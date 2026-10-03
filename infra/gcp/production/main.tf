data "google_project" "application" {
  project_id = var.project_id
}

data "google_project" "anchor" {
  provider   = google.anchor
  project_id = var.audit_anchor_project_id
}

locals {
  common_labels = merge(
    {
      application = "creator-revenue-agent"
      environment = "production"
      managed-by  = "terraform"
    },
    var.labels,
  )

  application_services = toset([
    "compute.googleapis.com",
    "container.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "sts.googleapis.com",
  ])

  anchor_services = toset([
    "iam.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])

  application_secret_ids = toset([
    "creator-revenue-agent-database-url",
    "creator-revenue-agent-service-jwt-keys-json",
    "creator-revenue-agent-verification-webhook-keys-json",
    "creator-revenue-agent-audit-hash-keys-json",
    "creator-revenue-agent-audit-anchor-token",
    "creator-revenue-agent-audit-anchor-receipt-keys-json",
    "creator-revenue-agent-ghcr-pull",
  ])

  anchor_secret_ids = toset([
    "creator-revenue-agent-anchor-token",
    "creator-revenue-agent-anchor-receipt-keys-json",
  ])

  audit_bucket_name = (
    var.audit_anchor_bucket_name != ""
    ? var.audit_anchor_bucket_name
    : "${var.audit_anchor_project_id}-creator-agent-audit"
  )
}

resource "google_project_service" "application" {
  for_each = local.application_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_project_service" "anchor" {
  provider = google.anchor
  for_each = local.anchor_services

  project            = var.audit_anchor_project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "production" {
  name                    = var.network_name
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.application]
}

resource "google_compute_subnetwork" "production" {
  name                     = "${var.network_name}-${var.region}"
  region                   = var.region
  network                  = google_compute_network.production.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "gke-pods"
    ip_cidr_range = var.pods_cidr
  }

  secondary_ip_range {
    range_name    = "gke-services"
    ip_cidr_range = var.services_cidr
  }
}

resource "google_compute_router" "production" {
  name    = "${var.network_name}-router"
  region  = var.region
  network = google_compute_network.production.id
}

resource "google_compute_router_nat" "production" {
  name                               = "${var.network_name}-nat"
  router                             = google_compute_router.production.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

resource "google_compute_global_address" "private_services" {
  name          = "${var.network_name}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_services_prefix_length
  network       = google_compute_network.production.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.production.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]

  depends_on = [
    google_project_service.application["servicenetworking.googleapis.com"],
  ]
}

resource "google_container_cluster" "production" {
  name     = var.cluster_name
  location = var.region

  enable_autopilot = true
  network          = google_compute_network.production.id
  subnetwork       = google_compute_subnetwork.production.id

  deletion_protection = true

  release_channel {
    channel = "REGULAR"
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "gke-pods"
    services_secondary_range_name = "gke-services"
  }

  private_cluster_config {
    enable_private_nodes = true
  }

  control_plane_endpoints_config {
    dns_endpoint_config {
      allow_external_traffic    = true
      enable_k8s_tokens_via_dns = false
      enable_k8s_certs_via_dns  = false
    }

    ip_endpoints_config {
      enabled = false
    }
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  resource_labels = local.common_labels

  depends_on = [
    google_compute_router_nat.production,
    google_project_service.application["container.googleapis.com"],
  ]
}

resource "google_sql_database_instance" "production" {
  name             = var.cloud_sql_instance_name
  region           = var.region
  database_version = "POSTGRES_17"

  deletion_protection = true

  settings {
    tier              = var.cloud_sql_tier
    edition           = "ENTERPRISE"
    availability_type = "REGIONAL"

    deletion_protection_enabled = true
    disk_type                   = "PD_SSD"
    disk_size                   = var.cloud_sql_disk_size_gb
    disk_autoresize             = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      location                       = var.region

      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.production.id
    }

    user_labels = local.common_labels
  }

  depends_on = [
    google_project_service.application["sqladmin.googleapis.com"],
    google_service_networking_connection.private_services,
  ]

  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      settings[0].disk_size,
    ]
  }
}

resource "google_sql_database" "application" {
  name            = var.cloud_sql_database_name
  instance        = google_sql_database_instance.production.name
  charset         = "UTF8"
  project         = var.project_id
  deletion_policy = "ABANDON"
}

resource "google_secret_manager_secret" "application" {
  for_each = local.application_secret_ids

  secret_id = each.value
  project   = var.project_id
  labels    = local.common_labels

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [
    google_project_service.application["secretmanager.googleapis.com"],
  ]
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = var.github_workload_identity_pool_id
  display_name              = "GitHub production deployments"
  description               = "Trust boundary for creator-revenue-agent production GitHub Actions."
  project                   = var.project_id

  depends_on = [
    google_project_service.application["iam.googleapis.com"],
    google_project_service.application["iamcredentials.googleapis.com"],
    google_project_service.application["sts.googleapis.com"],
  ]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.github_workload_identity_provider_id
  display_name                       = "creator-revenue-agent production"
  project                            = var.project_id

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
  }

  attribute_condition = join(" && ", [
    "assertion.repository == '${var.github_repository}'",
    "assertion.repository_owner == '${split("/", var.github_repository)[0]}'",
    "assertion.ref == 'refs/heads/main'",
  ])

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com/"
  }
}

resource "google_service_account" "github_deployer" {
  account_id   = var.github_deploy_service_account_id
  display_name = "GitHub production Kubernetes deployer"
  project      = var.project_id
}

resource "google_project_iam_custom_role" "gke_dns_connect" {
  role_id     = "creatorAgentGkeDnsConnect"
  title       = "Creator Agent GKE DNS Connect"
  description = "Minimum Google IAM permissions needed to discover and connect to the production GKE control plane. Kubernetes RBAC controls namespaced mutations."
  project     = var.project_id
  permissions = [
    "container.clusters.connect",
    "container.clusters.get",
  ]
}

resource "google_project_iam_member" "github_deployer_gke_connect" {
  project = var.project_id
  role    = google_project_iam_custom_role.gke_dns_connect.name
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_service_account_iam_member" "github_wif" {
  service_account_id = google_service_account.github_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member = (
    "principalSet://iam.googleapis.com/projects/${data.google_project.application.number}"
    + "/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}"
    + "/attribute.repository/${var.github_repository}"
  )
}

resource "google_storage_bucket" "audit_anchor" {
  provider = google.anchor

  name                        = local.audit_bucket_name
  project                     = var.audit_anchor_project_id
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = var.audit_anchor_retention_seconds
    is_locked        = var.lock_audit_anchor_bucket
  }

  depends_on = [
    google_project_service.anchor["storage.googleapis.com"],
  ]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "audit_anchor" {
  provider = google.anchor

  account_id   = "creator-agent-audit-anchor"
  display_name = "Creator Revenue Agent external audit anchor"
  project      = var.audit_anchor_project_id
}

resource "google_storage_bucket_iam_member" "audit_anchor_creator" {
  provider = google.anchor

  bucket = google_storage_bucket.audit_anchor.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.audit_anchor.email}"
}

resource "google_storage_bucket_iam_member" "audit_anchor_viewer" {
  provider = google.anchor

  bucket = google_storage_bucket.audit_anchor.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.audit_anchor.email}"
}

resource "google_secret_manager_secret" "audit_anchor" {
  provider = google.anchor
  for_each = local.anchor_secret_ids

  secret_id = each.value
  project   = var.audit_anchor_project_id
  labels    = local.common_labels

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [
    google_project_service.anchor["secretmanager.googleapis.com"],
  ]
}

resource "google_secret_manager_secret_iam_member" "audit_anchor_access" {
  provider = google.anchor
  for_each = google_secret_manager_secret.audit_anchor

  project   = var.audit_anchor_project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.audit_anchor.email}"
}
