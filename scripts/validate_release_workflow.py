from __future__ import annotations

import re
from pathlib import Path


WORKFLOWS = (
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/agent.yml"),
    Path(".github/workflows/release.yml"),
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

    if errors:
        for error in errors:
            print(error)
        return 1

    print("Release workflow security validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
