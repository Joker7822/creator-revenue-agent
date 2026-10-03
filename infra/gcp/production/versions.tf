terraform {
  required_version = "= 1.16.4"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 8.5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google" {
  alias   = "anchor"
  project = var.audit_anchor_project_id
  region  = var.region
}
