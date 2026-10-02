#!/usr/bin/env bash
set -euo pipefail

RENDERED="${1:-rendered-kubernetes.yaml}"

required_patterns=(
  "kind: Deployment"
  "kind: Service"
  "kind: PodDisruptionBudget"
  "kind: HorizontalPodAutoscaler"
  "kind: NetworkPolicy"
  "runAsNonRoot: true"
  "runAsUser: 10001"
  "allowPrivilegeEscalation: false"
  "readOnlyRootFilesystem: true"
  "type: RuntimeDefault"
  "drop:"
  "- ALL"
  "startupProbe:"
  "livenessProbe:"
  "readinessProbe:"
  "requests:"
  "limits:"
  "automountServiceAccountToken: false"
  "imagePullSecrets:"
  "- name: ghcr-pull"
  "minAvailable: 2"
)

for pattern in "${required_patterns[@]}"; do
  if ! grep -Fq -- "$pattern" "$RENDERED"; then
    echo "Missing Kubernetes hardening invariant: $pattern" >&2
    exit 1
  fi
done

if grep -Eq 'image:[[:space:]]+.*:latest([[:space:]]|$)' "$RENDERED"; then
  echo "Kubernetes manifests must not use :latest images" >&2
  exit 1
fi

if grep -Eq 'privileged:[[:space:]]+true' "$RENDERED"; then
  echo "Privileged containers are forbidden" >&2
  exit 1
fi

if ! grep -Fq 'pod-security.kubernetes.io/enforce: restricted' "$RENDERED"; then
  echo "Restricted Pod Security admission label is required" >&2
  exit 1
fi

if ! grep -Fq 'DATABASE_URL_FILE: /run/secrets/database_url' "$RENDERED"; then
  echo "Database credentials must use mounted secret files" >&2
  exit 1
fi

echo "Kubernetes hardening validation passed"
