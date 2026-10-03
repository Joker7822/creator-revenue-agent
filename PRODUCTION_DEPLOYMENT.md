# Production Deployment

This document defines the production deployment control path for
`creator-revenue-agent`.

The default production foundation is Google Cloud:

```text
GitHub Actions
  -> GitHub OIDC / Google Workload Identity Federation
  -> GKE Autopilot (regional, private nodes, DNS-only control plane)
  -> Cloud SQL PostgreSQL (private IP, regional HA, backups + PITR)
  -> independently administered HTTPS Audit Anchor
       -> separate-project Cloud Storage WORM bucket
```

The Terraform foundation is under:

```text
infra/gcp/production/
```

The application workflow deploys only an already released, attested,
staging-rehearsed immutable image. It does not rebuild the release image.

## Release path

```text
semantic release tag
  -> Release Image
  -> Staging Release Rehearsal (must succeed)
  -> Production Preflight
       -> GitHub OIDC / Google WIF
       -> short-lived GKE credentials
       -> production cluster contract validation
  -> Production Deployment
       -> Verify Release Promotion
       -> verify exact staging evidence
       -> render production configuration
       -> migration Job
       -> Kubernetes rollout
       -> readiness
       -> runtime digest verification
       -> checksummed production evidence
```

Production identity is the exact value:

```text
ghcr.io/<owner>/creator-revenue-agent@sha256:<digest>
```

that passed staging.

## GitHub production Environment

Create a protected GitHub Environment named:

```text
production
```

Configure required reviewers / deployment protection rules appropriate for
production. The promotion gate and rollout both target this Environment.

No long-lived Google service-account key and no long-lived
`KUBECONFIG_B64` are required for production deployment.

### Environment Variables

Configure:

```text
GCP_PROJECT_ID
GCP_WIF_PROVIDER
GCP_DEPLOY_SERVICE_ACCOUNT
GKE_CLUSTER
GKE_LOCATION
K8S_NAMESPACE
SERVICE_JWT_ACTIVE_KID
AUDIT_HASH_ACTIVE_KID
AUDIT_ANCHOR_BASE_URL
AUDIT_ANCHOR_NAMESPACE
```

The first five values are emitted by the GCP Terraform foundation:

```text
GCP_PROJECT_ID              <- gcp_project_id
GCP_WIF_PROVIDER            <- github_workload_identity_provider
GCP_DEPLOY_SERVICE_ACCOUNT  <- github_deploy_service_account
GKE_CLUSTER                 <- gke_cluster_name
GKE_LOCATION                <- gke_location
```

`AUDIT_ANCHOR_BASE_URL` must be a real HTTPS endpoint. Localhost,
Docker Desktop hostnames, and `.invalid` test endpoints are rejected.

## Production cloud foundation

The GCP Terraform stack provisions the durable foundation without creating
secret values:

- custom VPC, production subnet, Cloud Router and Cloud NAT
- regional GKE Autopilot with private nodes
- DNS-based GKE control-plane endpoint with direct IP endpoint disabled
- Cloud SQL PostgreSQL over private IP only
- regional Cloud SQL HA, backups and point-in-time recovery
- application Secret Manager containers without secret versions
- GitHub OIDC Workload Identity Federation restricted to this repository and
  `refs/heads/main`
- a deploy Google service account with only GKE discovery/connect IAM
  permissions; Kubernetes RBAC remains the deployment authorization boundary
- a separate GCP project for external audit-anchor storage
- a non-public Cloud Storage bucket with retention policy, versioning, and
  destroy protection
- an audit-anchor service account with object create/read but no object-delete
  permission

See:

```text
infra/gcp/production/README.md
```

The retention duration is deliberately a required input. The repository does
not invent a legal/business retention period. Cloud Storage retention locking
is irreversible and defaults to disabled until separately reviewed.

## Cluster prerequisites

Pre-create the production Namespace with:

```text
pod-security.kubernetes.io/enforce=restricted
```

Pre-provision these Kubernetes Secrets outside GitHub Actions:

```text
creator-revenue-agent-secrets
ghcr-pull
```

`creator-revenue-agent-secrets` requires:

```text
database_url
service_jwt_keys_json
verification_webhook_keys_json
audit_hash_keys_json
audit_anchor_token
audit_anchor_receipt_keys_json
```

The production database URL must use `postgresql+psycopg://` and point at the
private Cloud SQL PostgreSQL service through the approved production network
path.

The active JWT and audit KIDs configured through Environment variables must
exist in their corresponding production key rings.

`ghcr-pull` must be a `kubernetes.io/dockerconfigjson` Secret containing
read credentials for `ghcr.io`.

Use production-only credentials. Never reuse local or staging database
passwords, JWT keys, webhook keys, audit keys, anchor credentials, or registry
credentials.

The Terraform stack creates Secret Manager containers only. Populate secret
versions and Kubernetes Secrets through the approved secret-provisioning
process so secret values are not copied into Terraform state.

## Deployer IAM and Kubernetes RBAC

GitHub Actions exchanges its GitHub OIDC token for short-lived Google
credentials through Workload Identity Federation.

Google IAM is intentionally narrow: the deploy identity receives only the
permissions needed to discover/connect to the GKE cluster. GKE deployment
permissions are granted separately through Kubernetes RBAC.

For GCP, bootstrap:

```text
deploy/kubernetes/production-deployer-gcp-rbac.example.yaml
```

using an initial cluster administrator after replacing the placeholder subject
with the Terraform output `github_deploy_service_account`.

The resulting Kubernetes principal is expected to have only this surface:

- get the exact production Namespace
- get `creator-revenue-agent-secrets` and `ghcr-pull`
- get/create/patch ServiceAccount, ConfigMap, Service, Deployment,
  PodDisruptionBudget, HorizontalPodAutoscaler, and NetworkPolicy
- get/list/create/delete/watch Jobs
- get/list/watch Pods and get Pods/log
- watch Deployments

It must not have Secret create/patch permission or production Namespace delete
permission.

Both Production Preflight and Production Deployment verify these boundaries.

## Production Preflight

Run:

```text
.github/workflows/production-preflight.yml
```

before the first production deployment and after material IAM/RBAC/cluster or
secret changes.

The preflight:

1. obtains short-lived Google credentials through GitHub OIDC/WIF
2. obtains short-lived GKE credentials using the DNS-based endpoint
3. requires the generated context to be `production`
4. rejects non-GKE-DNS control-plane endpoints
5. requires restricted Pod Security
6. validates the six-key application Secret and active key IDs
7. validates the GHCR pull Secret
8. verifies required namespaced deployment permissions
9. verifies Secret mutation and Namespace deletion are denied

The preflight performs no `kubectl apply` or `kubectl create`.

## Required external dependencies

Before rollout, provision and validate:

1. the GCP production foundation in `infra/gcp/production/`
2. production PostgreSQL credentials and a tested restore procedure
3. an independently administered append-only/WORM Audit Anchor HTTPS service
4. a verification provider with production webhook signing keys
5. production Kubernetes application and GHCR Secrets
6. ingress/TLS, external monitoring, distributed rate limiting, and alerting
7. GHCR read access for the immutable release image

The foundation creates the separate WORM bucket and anchor identity, but the
actual HTTPS Audit Anchor service is a separate deployment layer.

The application readiness endpoint fails closed when database revision,
authentication configuration, trusted verification, audit-chain integrity, or
Audit Anchor freshness is invalid.

## Production Deployment inputs

Run:

```text
.github/workflows/production-deploy.yml
```

with:

```text
release_tag
image_ref
staging_run_id
backup_reference
change_reference
```

`staging_run_id` must identify a successful `Staging Release Rehearsal`
containing `staging-rehearsal-<release_tag>`. The workflow verifies the
checksummed evidence and requires the exact release tag, source commit, image
digest, ready replica count, and runtime image IDs to match.

`backup_reference` identifies the production database backup/snapshot created
before deployment. The repository records this reference in evidence; it does
not pretend to create or validate the external backup itself.

`change_reference` identifies the approved production change/ticket.

## Deployment sequence

After the production Environment gate passes, the workflow:

1. resolves the semantic tag to its source commit
2. verifies the supplied image is this repository's immutable GHCR digest
3. verifies the exact successful staging rehearsal evidence
4. reruns the attestation/SBOM Promotion Gate for production
5. renders environment-specific production manifests
6. reruns Kubernetes hardening and schema validation
7. authenticates with GitHub OIDC/WIF and obtains DNS-based GKE credentials
8. revalidates cluster, Secret, GHCR, and RBAC contracts
9. runs the one-shot Alembic migration Job
10. applies the Kustomize application
11. waits for Deployment rollout and Pod readiness
12. verifies running container `imageID` values match the attested digest
13. writes checksummed production deployment evidence

A failed migration or failed readiness prevents successful deployment evidence.

## Evidence

A successful deployment uploads:

```text
production-deployment-<release-tag>
```

with 180-day retention.

The evidence records release/tag/digest identity, staging and promotion evidence
hashes, backup/change references, GCP project and GKE identity, Kubernetes
context/server/namespace, Deployment generations, replica readiness, runtime
image IDs, rendered manifest hashes, and UTC generation time.

## First production rollout order

Use this order:

1. create separate application and audit Google Cloud projects
2. configure remote protected Terraform state
3. plan/review/apply `infra/gcp/production/` with an approved retention period
4. test the Cloud SQL restore procedure
5. deploy the external HTTPS Audit Anchor against the separate-project WORM
   storage and verify signed receipts
6. create the restricted production Namespace
7. populate production Secret Manager versions and Kubernetes Secrets
8. bootstrap the GCP deploy identity Kubernetes RBAC
9. configure and protect the GitHub `production` Environment variables
10. run Production Preflight successfully
11. create the semantic release tag and require Release Image success
12. require Staging Release Rehearsal success and capture its run ID
13. create/verify the production database backup and capture its reference
14. obtain production change approval/reference
15. run Production Deployment with the exact tag and digest
16. retain the checksummed production evidence artifact

Do not bypass staging evidence, the Promotion Gate, production reviewers,
migration completion, readiness, or the external Audit Anchor to force a
rollout.
