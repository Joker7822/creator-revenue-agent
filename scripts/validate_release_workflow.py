from __future__ import annotations

import re
from pathlib import Path


WORKFLOWS = (
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/agent.yml"),
    Path(".github/workflows/release.yml"),
    Path(".github/workflows/promote.yml"),
    Path(".github/workflows/staging-release-rehearsal.yml"),
)

USES_LINE = re.compile(
    r"^\s*(?:-\s*)?uses:\s+([^\s#]+)"
)

PINNED_ACTION = re.compile(
    r"^[^\s@]+@([0-9a-f]{40})$"
)


def validate_pinned_actions(path: Path) -> list[str]:
    errors: list[str] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        match = USES_LINE.match(line)
        if match is None:
            continue

        action_ref = match.group(1)
        if action_ref.startswith("./"):
            continue

        if PINNED_ACTION.fullmatch(action_ref) is None:
            errors.append(
                f"{path}:{line_number}: external action must be pinned "
                "to a 40-character commit SHA"
            )
    return errors


def validate_release_workflow(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    required = (
        "packages: write",
        "id-token: write",
        "attestations: write",
        "push-to-registry: true",
        "actions/attest-build-provenance@",
        "actions/attest-sbom@",
        "subject-digest: ${{ env.IMAGE_DIGEST }}",
        "release-sbom.cdx.json",
        "IMAGE_REF=",
        "git merge-base --is-ancestor",
    )
    for token in required:
        if token not in text:
            errors.append(
                f"{path}: missing release invariant: {token}"
            )

    if ":latest" in text:
        errors.append(f"{path}: :latest image tags are forbidden")

    if re.search(r"uses:\s+[^\s]+@(v\d+|main|master)\b", text):
        errors.append(
            f"{path}: mutable GitHub Action ref is forbidden"
        )

    return errors


def validate_promotion_workflow(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    required = (
        "workflow_call:",
        "target_environment:",
        "production|staging",
        "environment: ${{ inputs.target_environment }}",
        "attestations: read",
        "packages: read",
        "refs/heads/main",
        "gh attestation verify",
        "--signer-workflow",
        ".github/workflows/release.yml",
        "--source-ref",
        "--source-digest",
        "--deny-self-hosted-runners",
        '--predicate-type "https://cyclonedx.org/bom"',
        "scripts/render_release_manifests.py",
        "verified-application.yaml",
        "scripts/validate_kubernetes.sh",
        "kubeconform",
        "promotion-evidence.json",
    )
    for token in required:
        if token not in text:
            errors.append(
                f"{path}: missing promotion invariant: {token}"
            )

    if ":latest" in text:
        errors.append(
            f"{path}: :latest image tags are forbidden"
        )

    if re.search(
        r"uses:\s+[^\s]+@(v\d+|main|master)\b",
        text,
    ):
        errors.append(
            f"{path}: mutable GitHub Action ref is forbidden"
        )

    return errors


def validate_staging_rehearsal_workflow(
    path: Path,
) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    required = (
        "workflow_run:",
        "Release Image",
        "types:",
        "- completed",
        "actions: read",
        "group: staging-release-rehearsal",
        "cancel-in-progress: false",
        "github.event.workflow_run.conclusion == 'success'",
        "release-evidence.json.sha256",
        "release-sbom.cdx.json.sha256",
        "git merge-base --is-ancestor",
        "uses: ./.github/workflows/promote.yml",
        "target_environment: staging",
        "environment: staging",
        "KUBECONFIG_B64",
        "KUBE_CONTEXT",
        "KUBE_SERVER",
        "scripts/render_staging_manifests.py",
        "scripts/validate_kubernetes.sh",
        "SHA256SUMS",
        "kubectl config use-context",
        "creator-revenue-agent-secrets",
        "migration-job.yaml",
        "kubectl apply -k staging-kubernetes",
        "rollout status",
        "imageID",
        "staging-rollout-evidence.json",
    )
    for token in required:
        if token not in text:
            errors.append(
                f"{path}: missing staging rehearsal invariant: "
                f"{token}"
            )

    if ":latest" in text:
        errors.append(
            f"{path}: :latest image tags are forbidden"
        )

    if re.search(
        r"uses:\s+[^\s]+@(v\d+|main|master)\b",
        text,
    ):
        errors.append(
            f"{path}: mutable GitHub Action ref is forbidden"
        )

    return errors


def main() -> int:
    errors: list[str] = []
    for workflow in WORKFLOWS:
        if not workflow.is_file():
            errors.append(f"missing workflow: {workflow}")
            continue
        errors.extend(validate_pinned_actions(workflow))

    release = Path(".github/workflows/release.yml")
    if release.is_file():
        errors.extend(validate_release_workflow(release))

    promotion = Path(".github/workflows/promote.yml")
    if promotion.is_file():
        errors.extend(validate_promotion_workflow(promotion))

    staging = Path(
        ".github/workflows/staging-release-rehearsal.yml"
    )
    if staging.is_file():
        errors.extend(
            validate_staging_rehearsal_workflow(staging)
        )

    if errors:
        for error in errors:
            print(error)
        return 1

    print("Release workflow security validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
