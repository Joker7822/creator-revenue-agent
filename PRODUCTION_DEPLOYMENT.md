# Production Deployment

This document defines the production deployment control path for
`creator-revenue-agent`.

The repository workflow deploys only an already released, attested,
staging-rehearsed immutable image. It does not provision a cloud cluster,
PostgreSQL service, external audit-anchor service, DNS, TLS ingress, or
secret manager. Those are production infrastructure prerequisites.

## Release path

```text
semantic release tag
  -> Release Image
  -> Staging Release Rehearsal (must succeed)
  -> Production Preflight
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

Production never rebuilds the application image. The exact
`ghcr.io/<owner>/creator-revenue-agent@sha256:<digest>` that passed staging
is the deployment identity.

## GitHub production Environment

Create a protected GitHub Environment named:

```text
production
```

Configure required reviewers / deployment protection rules appropriate for
production. The promotion gate and rollout both target this Environment.

### Environment Secret

```text
KUBECONFIG_B64
```

It is the base64 encoding of the least-privilege production kubeconfig.
The workflow rejects Docker Desktop / localhost endpoints.

The credential must not be able to create or patch application Secrets or
delete the production Namespace.

### Environment Variables

```text
KUBE_CONTEXT
KUBE_SERVER
K8S_NAMESPACE
SERVICE_JWT_ACTIVE_KID
AUDIT_HASH_ACTIVE_KID
AUDIT_ANCHOR_BASE_URL
AUDIT_ANCHOR_NAMESPACE
```

`AUDIT_ANCHOR_BASE_URL` must be a real HTTPS endpoint. Localhost,
Docker Desktop hostnames, and `.invalid` test endpoints are rejected.

## Cluster prerequisites

Pre-create the production Namespace with:

```text
pod-security.kubernetes.io/enforce=restricted
```

Pre-provision these Secrets outside GitHub Actions:

```text
creator-revenue-agent-secrets
ghcr-pull
```

`creator-revenue-agent-secrets` requires exactly the application contract:

```text
database_url
service_jwt_keys_json
verification_webhook_keys_json
audit_hash_keys_json
audit_anchor_token
audit_anchor_receipt_keys_json
```

The production database URL must use `postgresql+psycopg://`.
The active JWT and audit KIDs configured through Environment variables must
exist in their corresponding production key rings.

`ghcr-pull` must be a `kubernetes.io/dockerconfigjson` Secret containing
credentials for `ghcr.io`.

Use production-only credentials. Never reuse local or staging database
passwords, JWT keys, webhook keys, audit keys, anchor credentials, or
registry credentials.

## Deployer RBAC

The kubeconfig principal is expected to have only the following deployment
surface:

- get the exact production Namespace
- get `creator-revenue-agent-secrets` and `ghcr-pull`
- get/create/patch ServiceAccount, ConfigMap, Service, Deployment,
  PodDisruptionBudget, HorizontalPodAutoscaler, and NetworkPolicy
- get/list/create/delete/watch Jobs
- get/list/watch Pods and get Pods/log
- watch Deployments

It must not have:

- Secret create
- Secret patch
- production Namespace delete

Both Production Preflight and Production Deployment verify these boundaries.

## Production Preflight

Run:

```text
.github/workflows/production-preflight.yml
```

before attempting the first production deployment and after material
credential/RBAC/cluster changes.

The preflight is read-only. It validates the exact kube context/server,
restricted Pod Security, Secret/key-ring contracts, GHCR pull credentials,
and least-privilege RBAC.

It deliberately performs no `kubectl apply` or `kubectl create`.

## Required external dependencies

Before production rollout, provision and validate:

1. a reachable production Kubernetes cluster
2. production PostgreSQL with backups and restore procedures
3. an independently administered append-only/WORM Audit Anchor HTTPS service
4. a verification provider with production webhook signing keys
5. a secret manager or equivalent controlled Secret provisioning path
6. production ingress/TLS, monitoring, distributed rate limiting, and alerting
7. GHCR read access for the immutable release image

The application readiness endpoint fails closed when the database revision,
authentication configuration, trusted verification, audit-chain integrity,
or Audit Anchor freshness is not valid.

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

`staging_run_id` must identify a successful
`Staging Release Rehearsal` containing
`staging-rehearsal-<release_tag>`. The workflow verifies the checksummed
staging rollout evidence and requires the exact release tag, source commit,
image digest, ready replica count, and runtime image IDs to match.

`backup_reference` identifies the production database snapshot/backup
created by the production database platform before deployment.
The repository records this reference in deployment evidence; it does not
create or independently validate the external backup.

`change_reference` identifies the approved production change/ticket.

## Deployment sequence

After the production Environment gate passes, the workflow:

1. resolves the semantic tag to its source commit
2. verifies the supplied image is this repository's immutable GHCR digest
3. verifies the exact successful staging rehearsal evidence
4. reruns the attestation/SBOM Promotion Gate for production
5. renders environment-specific production manifests
6. reruns Kubernetes hardening and schema validation
7. verifies the exact production kube context/server
8. revalidates the Secret, GHCR, and RBAC contracts
9. runs the one-shot Alembic migration Job
10. applies the Kustomize application
11. waits for Deployment rollout and Pod readiness
12. verifies running container `imageID` values match the attested digest
13. writes checksummed production deployment evidence

A failed migration or failed readiness prevents the workflow from producing
successful deployment evidence.

## Evidence

A successful deployment uploads:

```text
production-deployment-<release-tag>
```

with 180-day retention.

The evidence records:

- release tag
- source commit
- immutable image reference
- staging rehearsal run ID and evidence hash
- production promotion evidence hash
- backup reference
- change reference
- Kubernetes context/server/namespace
- Deployment UID/generation
- desired and ready replicas
- runtime image IDs
- rendered manifest hashes
- UTC generation time

## First production rollout order

Use this order:

1. provision managed production PostgreSQL and test restore
2. provision the external/WORM Audit Anchor service
3. provision the production Kubernetes cluster and restricted Namespace
4. provision production application and GHCR Secrets
5. configure least-privilege deployment credentials
6. configure and protect the GitHub `production` Environment
7. run Production Preflight successfully
8. create the semantic release tag
9. require Release Image success
10. require Staging Release Rehearsal success and capture its run ID
11. create/verify the production database backup and capture its reference
12. obtain the production change approval/reference
13. run Production Deployment with the exact tag and digest
14. retain the checksummed production evidence artifact

Do not bypass staging evidence, the Promotion Gate, production reviewers,
migration completion, or readiness to force a rollout.
