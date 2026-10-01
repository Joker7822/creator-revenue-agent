import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.render_release_manifests import (
    validate_inputs,
)


DIGEST = "a" * 64
IMAGE = (
    "ghcr.io/joker7822/creator-revenue-agent"
    f"@sha256:{DIGEST}"
)


def test_validate_inputs_requires_expected_digest() -> None:
    validate_inputs(
        image_ref=IMAGE,
        expected_image=(
            "ghcr.io/joker7822/creator-revenue-agent"
        ),
        release_tag="v1.2.3",
        source_commit="b" * 40,
    )

    with pytest.raises(ValueError):
        validate_inputs(
            image_ref=(
                "ghcr.io/joker7822/"
                "creator-revenue-agent:v1.2.3"
            ),
            expected_image=(
                "ghcr.io/joker7822/"
                "creator-revenue-agent"
            ),
            release_tag="v1.2.3",
            source_commit="b" * 40,
        )


def test_renderer_pins_deployment_and_migration(
    tmp_path: Path,
) -> None:
    output = tmp_path / "verified"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/render_release_manifests.py",
            "--image-ref",
            IMAGE,
            "--expected-image",
            "ghcr.io/joker7822/creator-revenue-agent",
            "--release-tag",
            "v1.2.3",
            "--source-commit",
            "b" * 40,
            "--output-dir",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    rendered = json.loads(result.stdout)
    assert rendered["image_ref"] == IMAGE

    deployment = (
        output / "deployment.yaml"
    ).read_text(encoding="utf-8")
    migration = (
        output / "migration-job.yaml"
    ).read_text(encoding="utf-8")
    assert IMAGE in deployment
    assert IMAGE in migration
    assert ":replace-me" not in deployment
    assert ":replace-me" not in migration

    metadata = json.loads(
        (output / "promotion-metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["release_tag"] == "v1.2.3"
    assert metadata["source_commit"] == "b" * 40
    assert (output / "SHA256SUMS").is_file()
    assert not (output / "secret.example.yaml").exists()
