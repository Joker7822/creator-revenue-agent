# Release Artifact Integrity

Release images are published by `.github/workflows/release.yml` when a semantic `v*` tag is pushed.

## Release identity

A release is identified by all of the following:

```text
source Git commit
release tag
GHCR image name
sha256 image digest
CycloneDX SBOM SHA-256
GitHub build-provenance attestation ID
GitHub SBOM attestation ID
```

The image digest is authoritative. Tags are convenience references only.

## Release workflow

The workflow:

1. rejects malformed release tags
2. requires the tagged commit to be an ancestor of `main`
3. migrates an isolated PostgreSQL database to Alembic head
4. runs the production release gate
5. builds and pushes the image to GHCR
6. resolves the immutable image digest
7. scans the exact pushed digest for fixable CRITICAL vulnerabilities
8. generates and validates a CycloneDX SBOM
9. creates GitHub build-provenance attestation
10. creates GitHub SBOM attestation
11. writes checksummed release evidence
12. uploads the evidence bundle as a workflow artifact

No `:latest` tag is published.

## Action pinning

Every external GitHub Action in repository workflows is pinned to a full 40-character commit SHA. Dependabot remains responsible for proposing controlled updates.

The normal CI supply-chain job runs:

```text
python scripts/validate_release_workflow.py
```

to reject mutable Action references and missing release invariants.

## Deployment

Deploy the exact value contained in:

```text
release-image.txt
```

For example:

```text
ghcr.io/example/creator-revenue-agent@sha256:<digest>
```

Use the same digest in the Kubernetes Deployment and migration Job.

Do not rebuild an image after attestation and then deploy the rebuilt copy under the same release tag.

## Verification

Before production promotion, verify:

- CI for the source commit succeeded
- release preflight succeeded
- release SBOM checksum matches
- release evidence checksum matches
- GitHub provenance attestation validates for the image digest
- GitHub SBOM attestation validates for the same digest
- deployed Kubernetes image ID equals the attested digest

The target environment should enforce attestation/signature policy at admission when the selected managed platform supports it.


## Verified promotion gate

Production promotion is a separate workflow from image publication:

```text
.github/workflows/promote.yml
```

It accepts only:

```text
release_tag
immutable GHCR image@sha256 digest
```

Before producing a deployment bundle it:

1. resolves the release tag to its source commit
2. rejects mutable image tags and repository mismatches
3. authenticates to GHCR
4. verifies the GitHub SLSA provenance attestation for the exact OCI digest
5. constrains signer identity to this repository's `.github/workflows/release.yml`
6. constrains source ref and source commit to the requested release tag
7. refuses attestations originating from self-hosted runners
8. verifies a CycloneDX SBOM attestation for the same digest
9. rewrites both the Kubernetes Deployment and migration Job to the same immutable digest
10. reruns Kubernetes hardening and schema validation
11. emits checksummed promotion evidence

The promotion workflow uses the GitHub `production` environment. Configure required reviewers / deployment protection rules on that environment in repository settings.

The uploaded `verified-promotion-<tag>` artifact is the deployable handoff. Downstream CD should consume that bundle rather than accepting an arbitrary image tag or rebuilding the image.
