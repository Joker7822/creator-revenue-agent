# GCP Production Foundation

This Terraform stack provisions the production cloud foundation for
`creator-revenue-agent` without placing application secret values in Terraform
state.

## Architecture

```text
GitHub Actions
  |  OIDC / Workload Identity Federation
  v
GCP deploy service account
  |
  | IAM: only discover/connect to GKE
  | Kubernetes RBAC: namespaced deployment permissions
  v
GKE Autopilot (regional, private nodes, DNS-only control plane)
  |
  +--> Cloud SQL for PostgreSQL 17
  |      private IP only
  |      REGIONAL HA
  |      automated backups + PITR
  |
  +--> external HTTPS Audit Anchor (next deployment layer)

separate GCP audit project
  |
  +--> Cloud Storage WORM bucket
  +--> Audit Anchor service account
  +--> Secret Manager containers for anchor auth/signing
```

The application and audit-anchor storage intentionally use different Google
Cloud projects. This improves separation from the application database and
cluster. The external Audit Anchor service itself is deployed separately and
must write signed receipts into the WORM bucket.

## Security properties

The stack creates:

- regional GKE Autopilot in `asia-northeast1` by default
- private GKE nodes with Cloud NAT for controlled outbound traffic
- DNS-based GKE control-plane access with direct IP access disabled
- IAM-only DNS endpoint authentication; Kubernetes bearer tokens and client
  certificates are not enabled for the DNS endpoint
- Cloud SQL PostgreSQL with no public IPv4 address
- `REGIONAL` Cloud SQL high availability
- automated backups and point-in-time recovery
- Terraform and API-level Cloud SQL deletion protection
- regional Secret Manager containers, but no secret versions
- GitHub OIDC Workload Identity Federation restricted to this repository and
  `refs/heads/main`
- a custom Google IAM role containing only `container.clusters.get` and
  `container.clusters.connect`; Kubernetes RBAC remains the authorization
  boundary for deployment mutations
- a separate-project Cloud Storage bucket with uniform bucket-level access,
  public-access prevention, versioning, a mandatory retention policy, and
  Terraform destroy protection
- an Audit Anchor service account with object-create and object-read/list
  permissions, not object-delete permission

## Irreversible WORM lock

`audit_anchor_retention_seconds` is deliberately required. The repository does
not choose a legal or business retention duration on your behalf.

The first apply should use:

```hcl
lock_audit_anchor_bucket = false
```

After the retention period is reviewed, verified in the real project, and
explicitly approved, change it to:

```hcl
lock_audit_anchor_bucket = true
```

Cloud Storage retention-policy locking is irreversible. Once locked, the
retention period cannot be reduced or removed.

## Prerequisites

Before applying this stack:

1. create two billing-enabled GCP projects:
   - application production project
   - independently administered audit-anchor project
2. install Terraform and Google Cloud CLI
3. authenticate an infrastructure administrator with permissions to create the
   resources in this stack
4. decide and approve the audit retention period
5. choose a remote, access-controlled Terraform state backend before the first
   production apply

Do not keep production Terraform state only on a developer workstation.
Terraform state contains infrastructure metadata even though this stack does
not create application secret versions.

## Validate locally

```bash
terraform -chdir=infra/gcp/production fmt -check
terraform -chdir=infra/gcp/production init -backend=false
terraform -chdir=infra/gcp/production validate
```

## Plan

Create a real `terraform.tfvars` that is not committed:

```hcl
project_id              = "<production-project-id>"
audit_anchor_project_id = "<separate-audit-project-id>"
region                  = "asia-northeast1"

audit_anchor_retention_seconds = <approved-retention-seconds>
lock_audit_anchor_bucket        = false
```

Then:

```bash
terraform -chdir=infra/gcp/production init
terraform -chdir=infra/gcp/production plan -out=production.tfplan
```

Review the plan before apply. In particular verify:

- the application and audit project IDs are different
- the region is the intended production data location
- GKE IP endpoint access is disabled
- Cloud SQL has no public IPv4 address
- Cloud SQL availability is `REGIONAL`
- the WORM retention duration is the approved value
- `lock_audit_anchor_bucket` remains false until the irreversible-lock review

## Apply

After review:

```bash
terraform -chdir=infra/gcp/production apply production.tfplan
```

Record the outputs:

```bash
terraform -chdir=infra/gcp/production output
```

The values needed by the GitHub `production` Environment are:

```text
GCP_PROJECT_ID              <- gcp_project_id
GCP_WIF_PROVIDER            <- github_workload_identity_provider
GCP_DEPLOY_SERVICE_ACCOUNT  <- github_deploy_service_account
GKE_CLUSTER                 <- gke_cluster_name
GKE_LOCATION                <- gke_location
```

No long-lived Google service-account key should be created for GitHub Actions.

## Required post-apply bootstrap

Terraform intentionally does not create database passwords, JWT keys, webhook
keys, audit HMAC keys, anchor tokens, receipt signing keys, or GHCR credentials.
Adding those values as Terraform resources would copy them into Terraform
state.

Populate Secret Manager versions through your approved secret provisioning
process, then create the Kubernetes Secrets required by the application:

```text
creator-revenue-agent-secrets
ghcr-pull
```

The application Secret still requires:

```text
database_url
service_jwt_keys_json
verification_webhook_keys_json
audit_hash_keys_json
audit_anchor_token
audit_anchor_receipt_keys_json
```

The Cloud SQL application user/password must also be created outside this
Terraform stack and included only in the protected `database_url` secret.

## GKE RBAC bootstrap

Google IAM grants the GitHub deploy identity permission to connect to the GKE
control plane. It does not grant namespaced deployment permission.

Using an initial cluster administrator, apply the GCP-specific RBAC template in
`deploy/kubernetes/production-deployer-gcp-rbac.example.yaml` after replacing
the deploy service-account email with the Terraform output.

After that bootstrap, the GitHub production workflow is expected to operate
only through its least-privilege namespaced Role.

## What this stack does not deploy yet

This foundation deliberately stops before deploying the Audit Anchor HTTPS
service. The WORM bucket, anchor identity, and anchor Secret Manager containers
are created here so that the service can be deployed next without weakening the
storage boundary.

Ingress/TLS, externally durable monitoring, and distributed edge rate limiting
also remain deployment layers above this foundation.
