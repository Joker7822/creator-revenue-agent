variable "project_id" {
  description = "Google Cloud project that owns the production application infrastructure."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid Google Cloud project ID."
  }
}

variable "audit_anchor_project_id" {
  description = "Separate Google Cloud project that owns the external/WORM audit-anchor storage."
  type        = string

  validation {
    condition = (
      can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.audit_anchor_project_id)) &&
      var.audit_anchor_project_id != var.project_id
    )
    error_message = "audit_anchor_project_id must be a valid project ID distinct from project_id."
  }
}

variable "region" {
  description = "Primary production region. Tokyo is the default."
  type        = string
  default     = "asia-northeast1"
}

variable "cluster_name" {
  description = "GKE Autopilot cluster name."
  type        = string
  default     = "creator-revenue-agent-production"
}

variable "network_name" {
  description = "Production VPC name."
  type        = string
  default     = "creator-revenue-agent-production"
}

variable "subnet_cidr" {
  description = "Primary subnet CIDR."
  type        = string
  default     = "10.40.0.0/20"
}

variable "pods_cidr" {
  description = "GKE Pod secondary CIDR."
  type        = string
  default     = "10.48.0.0/14"
}

variable "services_cidr" {
  description = "GKE Service secondary CIDR."
  type        = string
  default     = "10.52.0.0/20"
}

variable "private_services_prefix_length" {
  description = "Prefix length reserved for Google private service access."
  type        = number
  default     = 16

  validation {
    condition     = var.private_services_prefix_length >= 16 && var.private_services_prefix_length <= 24
    error_message = "private_services_prefix_length must be between /16 and /24."
  }
}

variable "cloud_sql_instance_name" {
  description = "Cloud SQL PostgreSQL instance name."
  type        = string
  default     = "creator-revenue-agent-production"
}

variable "cloud_sql_database_name" {
  description = "Application database name."
  type        = string
  default     = "creator_agent"
}

variable "cloud_sql_tier" {
  description = "Cloud SQL Enterprise custom machine tier."
  type        = string
  default     = "db-custom-2-7680"
}

variable "cloud_sql_disk_size_gb" {
  description = "Initial Cloud SQL SSD size."
  type        = number
  default     = 50

  validation {
    condition     = var.cloud_sql_disk_size_gb >= 10
    error_message = "cloud_sql_disk_size_gb must be at least 10 GiB."
  }
}

variable "github_repository" {
  description = "Human-readable GitHub repository name used for documentation and defense-in-depth claim checks."
  type        = string
  default     = "Joker7822/creator-revenue-agent"
}

variable "github_repository_id" {
  description = "Immutable GitHub repository ID allowed to federate into production."
  type        = string
  default     = "1398816848"

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be a numeric GitHub repository ID."
  }
}

variable "github_repository_owner_id" {
  description = "Immutable GitHub repository-owner ID allowed to federate into production."
  type        = string
  default     = "107754027"

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must be a numeric GitHub owner ID."
  }
}

variable "github_workload_identity_pool_id" {
  description = "Workload Identity Pool ID for GitHub Actions."
  type        = string
  default     = "github-production"
}

variable "github_workload_identity_provider_id" {
  description = "Workload Identity Pool provider ID."
  type        = string
  default     = "creator-revenue-agent"
}

variable "github_deploy_service_account_id" {
  description = "Google service account ID used by the production GitHub deployment workflow."
  type        = string
  default     = "github-production-deployer"
}

variable "audit_anchor_bucket_name" {
  description = "Globally unique Cloud Storage bucket name. Empty derives a name from audit_anchor_project_id."
  type        = string
  default     = ""
}

variable "audit_anchor_retention_seconds" {
  description = "Required WORM retention period. Choose this from the actual business/legal retention policy before apply."
  type        = number

  validation {
    condition = (
      var.audit_anchor_retention_seconds > 0 &&
      var.audit_anchor_retention_seconds < 3155760000
    )
    error_message = "audit_anchor_retention_seconds must be between 1 second and 100 years."
  }
}

variable "lock_audit_anchor_bucket" {
  description = "Irreversibly lock the bucket retention policy. Leave false until retention policy is explicitly reviewed and approved."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Additional labels for supported production resources."
  type        = map(string)
  default     = {}
}
