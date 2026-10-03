#!/usr/bin/env bash
set -euo pipefail

required_env=(
  K8S_NAMESPACE
  SERVICE_JWT_ACTIVE_KID
  AUDIT_HASH_ACTIVE_KID
  AUDIT_ANCHOR_BASE_URL
  AUDIT_ANCHOR_NAMESPACE
)

for name in "${required_env[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "missing production environment setting: $name" >&2
    exit 1
  fi
done

python - <<'PY'
import os
from urllib.parse import urlsplit

anchor = urlsplit(os.environ["AUDIT_ANCHOR_BASE_URL"])
if anchor.scheme != "https" or not anchor.hostname:
    raise SystemExit(
        "AUDIT_ANCHOR_BASE_URL must be an absolute HTTPS URL"
    )
if anchor.username is not None or anchor.password is not None:
    raise SystemExit(
        "AUDIT_ANCHOR_BASE_URL must not embed credentials"
    )
forbidden = {
    "localhost",
    "127.0.0.1",
    "host.docker.internal",
    "kubernetes.docker.internal",
}
hostname = (anchor.hostname or "").lower()
if hostname in forbidden or hostname.endswith(".invalid"):
    raise SystemExit(
        "production audit anchor must not use a local/test host"
    )
PY

context="$(kubectl config current-context)"
if [ "$context" != "production" ]; then
  echo "unexpected production kube context: $context" >&2
  exit 1
fi

actual_server="$(
  kubectl config view \
    --minify \
    -o jsonpath='{.clusters[0].cluster.server}'
)"
case "$actual_server" in
  https://*.gke.goog) ;;
  *)
    echo "production must use the GKE DNS-based control-plane endpoint" >&2
    exit 1
    ;;
esac

kubectl cluster-info >/dev/null

enforced_policy="$(
  kubectl get namespace "$K8S_NAMESPACE" \
    -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}'
)"
if [ "$enforced_policy" != "restricted" ]; then
  echo "production namespace must enforce restricted Pod Security" >&2
  exit 1
fi

kubectl -n "$K8S_NAMESPACE" \
  get secret creator-revenue-agent-secrets \
  -o json \
  > "$RUNNER_TEMP/production-secret.json"

python - <<'PY'
import base64
import json
import os
from pathlib import Path

payload = json.loads(
    Path(
        os.environ["RUNNER_TEMP"] + "/production-secret.json"
    ).read_text(encoding="utf-8")
)
encoded = payload.get("data", {})
required = {
    "database_url",
    "service_jwt_keys_json",
    "verification_webhook_keys_json",
    "audit_hash_keys_json",
    "audit_anchor_token",
    "audit_anchor_receipt_keys_json",
}
missing = sorted(required - set(encoded))
if missing:
    raise SystemExit(
        "production application secret is missing keys: "
        + ", ".join(missing)
    )


def decode(name: str) -> str:
    try:
        value = base64.b64decode(
            encoded[name], validate=True
        ).decode("utf-8")
    except Exception as exc:
        raise SystemExit(
            f"invalid encoded secret value: {name}"
        ) from exc
    if not value:
        raise SystemExit(f"empty production secret value: {name}")
    return value


def key_ring(name: str) -> dict[str, str]:
    try:
        value = json.loads(decode(name))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON key ring: {name}") from exc
    if (
        not isinstance(value, dict)
        or not value
        or not all(
            isinstance(kid, str)
            and kid
            and isinstance(secret, str)
            and len(secret) >= 32
            for kid, secret in value.items()
        )
    ):
        raise SystemExit(f"invalid key ring contract: {name}")
    return value


database_url = decode("database_url")
if not database_url.startswith("postgresql+psycopg://"):
    raise SystemExit(
        "production database_url must use postgresql+psycopg"
    )

jwt_keys = key_ring("service_jwt_keys_json")
if os.environ["SERVICE_JWT_ACTIVE_KID"] not in jwt_keys:
    raise SystemExit(
        "SERVICE_JWT_ACTIVE_KID is absent from production key ring"
    )

audit_keys = key_ring("audit_hash_keys_json")
if os.environ["AUDIT_HASH_ACTIVE_KID"] not in audit_keys:
    raise SystemExit(
        "AUDIT_HASH_ACTIVE_KID is absent from production key ring"
    )

key_ring("audit_anchor_receipt_keys_json")

try:
    webhook = json.loads(decode("verification_webhook_keys_json"))
except json.JSONDecodeError as exc:
    raise SystemExit("invalid verification webhook key JSON") from exc
if not isinstance(webhook, dict) or not webhook:
    raise SystemExit("verification webhook key ring must not be empty")
for provider, keys in webhook.items():
    if (
        not isinstance(provider, str)
        or not provider
        or not isinstance(keys, dict)
        or not keys
        or not all(
            isinstance(kid, str)
            and kid
            and isinstance(secret, str)
            and len(secret) >= 32
            for kid, secret in keys.items()
        )
    ):
        raise SystemExit(
            "invalid verification webhook key ring contract"
        )

decode("audit_anchor_token")
PY

rm -f "$RUNNER_TEMP/production-secret.json"

kubectl -n "$K8S_NAMESPACE" \
  get secret ghcr-pull \
  -o json \
  > "$RUNNER_TEMP/ghcr-pull.json"

python - <<'PY'
import base64
import json
import os
from pathlib import Path

payload = json.loads(
    Path(
        os.environ["RUNNER_TEMP"] + "/ghcr-pull.json"
    ).read_text(encoding="utf-8")
)
if payload.get("type") != "kubernetes.io/dockerconfigjson":
    raise SystemExit(
        "ghcr-pull must be kubernetes.io/dockerconfigjson"
    )
raw = payload.get("data", {}).get(".dockerconfigjson")
if not raw:
    raise SystemExit("ghcr-pull is missing .dockerconfigjson")
config = json.loads(
    base64.b64decode(raw, validate=True).decode("utf-8")
)
if "ghcr.io" not in config.get("auths", {}):
    raise SystemExit("ghcr-pull does not contain ghcr.io credentials")
PY

rm -f "$RUNNER_TEMP/ghcr-pull.json"

require_yes() {
  local result
  result="$(kubectl auth can-i "$@")"
  if [ "$result" != "yes" ]; then
    echo "required permission missing: $*" >&2
    exit 1
  fi
}

require_no() {
  local result
  result="$(kubectl auth can-i "$@")"
  if [ "$result" != "no" ]; then
    echo "unexpected privileged permission: $*" >&2
    exit 1
  fi
}

require_yes get "namespace/$K8S_NAMESPACE"
require_yes get secret/creator-revenue-agent-secrets \
  -n "$K8S_NAMESPACE"
require_yes get secret/ghcr-pull -n "$K8S_NAMESPACE"

for resource in \
  serviceaccounts \
  configmaps \
  services \
  deployments.apps \
  poddisruptionbudgets.policy \
  horizontalpodautoscalers.autoscaling \
  networkpolicies.networking.k8s.io
do
  require_yes get "$resource" -n "$K8S_NAMESPACE"
  require_yes create "$resource" -n "$K8S_NAMESPACE"
  require_yes patch "$resource" -n "$K8S_NAMESPACE"
done

require_yes get jobs.batch -n "$K8S_NAMESPACE"
require_yes list jobs.batch -n "$K8S_NAMESPACE"
require_yes create jobs.batch -n "$K8S_NAMESPACE"
require_yes delete jobs.batch -n "$K8S_NAMESPACE"
require_yes watch jobs.batch -n "$K8S_NAMESPACE"
require_yes watch deployments.apps -n "$K8S_NAMESPACE"
require_yes get pods -n "$K8S_NAMESPACE"
require_yes list pods -n "$K8S_NAMESPACE"
require_yes watch pods -n "$K8S_NAMESPACE"
require_yes get pods/log -n "$K8S_NAMESPACE"

require_no create secrets -n "$K8S_NAMESPACE"
require_no patch secrets -n "$K8S_NAMESPACE"
require_no delete "namespace/$K8S_NAMESPACE"

grep -F "imagePullSecrets:" deploy/kubernetes/service-account.yaml
grep -F "  - name: ghcr-pull" deploy/kubernetes/service-account.yaml

printf '%s\n' "production cluster, secret, registry, and RBAC contracts validated"
