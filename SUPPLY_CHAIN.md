# Software Supply-Chain Security

CI treats dependency, source-secret, and production-image security as release-blocking controls.

## Dependency audit

Python dependencies are audited with a pinned `pip-audit` release against `requirements.txt`.

The audit is blocking. A published Python vulnerability without a resolved compatible dependency version requires an explicit dependency remediation before release.

## Repository secret scanning

The complete checked-out Git history is scanned with a pinned Gitleaks release.

Only known example/fixture paths and explicit placeholder patterns are allowlisted in `.gitleaks.toml`. Real production secret formats must never be added to the allowlist to make a scan green.

## Production image vulnerability scan

CI builds the same hardened production Dockerfile and scans it with a pinned Trivy release.

The gate has two layers:

- HIGH and CRITICAL vulnerabilities are reported
- fixed or fixable CRITICAL vulnerabilities fail CI

`--ignore-unfixed` is used for the blocking CRITICAL gate so an upstream base-image issue without an available fix is visible without making every release permanently impossible. Production operators should still evaluate unfixed critical findings before deployment.

## SBOM

CI generates a CycloneDX JSON SBOM from the production image.

```text
sbom.cdx.json
```

The repository validator requires:

- CycloneDX format
- a declared spec version
- metadata
- at least one named component

The SBOM is generated from the built image rather than only from `requirements.txt`, so operating-system and Python packages are represented together.

## Automated dependency updates

Dependabot is configured for:

- Python/pip
- GitHub Actions
- Docker base images

Updates run weekly and should still pass the complete test, PostgreSQL, security, Kubernetes, and container gates before merge.

## Release policy

A production image is not considered release-ready unless all of the following pass:

```text
unit/integration tests
PostgreSQL E2E and release gate
container hardening
Kubernetes manifest validation
dependency vulnerability audit
full-history secret scan
production image vulnerability scan
CycloneDX SBOM validation
```

This repository provides build-time evidence. Registry-side image signing, immutable digest promotion, admission-policy signature verification, and organization-level artifact retention are deployment-platform responsibilities and should be enabled in the target registry/cluster.
