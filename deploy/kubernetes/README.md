# Kubernetes Production Template

This directory contains a provider-neutral production Kubernetes baseline.

## Included resources

The Kustomize base includes:

- Namespace with Pod Security Admission `restricted`
- ServiceAccount with service-account token automount disabled
- ConfigMap containing non-secret production settings
- Deployment with three replicas and zero-unavailable rolling updates
- ClusterIP Service
- PodDisruptionBudget
- HorizontalPodAutoscaler
- ingress/egress NetworkPolicy

The migration Job and Secret example are intentionally not part of the normal Kustomize Deployment render.

## Image pinning

Before deployment, replace:

```text
ghcr.io/replace-me/creator-revenue-agent:replace-me
```

with an immutable registry digest, for example:

```text
ghcr.io/example/creator-revenue-agent@sha256:<digest>
```

Use the same digest for the migration Job and application Deployment.

Do not use `:latest`.

## Secrets

Create the Secret named:

```text
creator-revenue-agent-secrets
```

through the target platform's secret manager / CSI driver / External Secrets integration when possible.

Required keys:

```text
database_url
service_jwt_keys_json
verification_webhook_keys_json
audit_hash_keys_json
audit_anchor_token
audit_anchor_receipt_keys_json
```

`secret.example.yaml` documents the expected key names only. It is not included in `kustomization.yaml` and must not contain real credentials.

The Deployment mounts the Secret read-only under `/run/secrets` and consumes it through the application's `*_FILE` configuration.

## Network policy

Ingress is allowed on TCP/8000 from:

- Pods in the same namespace
- namespaces labeled:

```text
creator-revenue-agent-access=allowed
```

Label only the ingress/API-gateway and monitoring namespaces that require access.

Egress is limited to:

- cluster DNS on TCP/UDP 53
- HTTPS on TCP/443
- PostgreSQL on TCP/5432

The generic template allows 443 and 5432 to any IPv4 destination because provider addresses are not known in this repository. In production, narrow these egress destinations to managed PostgreSQL and WORM/service CIDRs or use a CNI with FQDN/L7 policy.

## Probes

```text
startup  -> GET /health
liveness -> GET /health
readiness -> GET /ready
```

Readiness intentionally includes database revision, trusted verification, audit integrity, WORM freshness, and production concurrency checks. A dependency or integrity failure therefore removes a Pod from Service endpoints without causing a liveness restart loop.

## Migration release sequence

Do not run Alembic from every application replica.

Recommended sequence:

1. build and sign an immutable image
2. create/verify a database backup
3. inject production secrets
4. run the release gate against production configuration
5. set the immutable image digest in `migration-job.yaml`
6. create the migration Job
7. require Job success
8. deploy the Kustomize application resources
9. wait for Deployment availability
10. require `/ready` to pass
11. verify audit/WORM state
12. shift external traffic

The migration template executes:

```text
alembic upgrade head
```

and mounts only the database Secret.

## Resource and availability defaults

Application Pods:

```text
replicas: 3
requests: 250m CPU / 256Mi
limits:   1 CPU / 512Mi
PDB minAvailable: 2
HPA: 3..10 replicas, CPU target 70%
```

Tune these from measured production traffic rather than removing limits.

## CI validation

CI renders the Kustomize base, appends the migration Job, validates native Kubernetes schemas with kubeconform, and checks hardening invariants with:

```text
scripts/validate_kubernetes.sh
```
