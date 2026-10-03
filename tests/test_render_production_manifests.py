from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.render_release_manifests import render_bundle
from scripts.render_production_manifests import render_production_bundle


RELEASE_TAG = "v1.2.3"
SOURCE_COMMIT = "a" * 40
IMAGE_REF = (
    "ghcr.io/joker7822/creator-revenue-agent@sha256:"
    + "b" * 64
)


def verified_bundle(tmp_path: Path) -> Path:
    output = tmp_path / "verified-kubernetes"
    render_bundle(
        source_dir=Path("deploy/kubernetes"),
        output_dir=output,
        image_ref=IMAGE_REF,
        release_tag=RELEASE_TAG,
        source_commit=SOURCE_COMMIT,
    )
    return output


def render(
    tmp_path: Path,
    *,
    namespace: str = "creator-revenue-agent",
    audit_anchor_base_url: str = (
        "https://audit-anchor.production.example.internal"
    ),
) -> Path:
    source = verified_bundle(tmp_path)
    output = tmp_path / "production-kubernetes"
    render_production_bundle(
        source_dir=source,
        output_dir=output,
        release_tag=RELEASE_TAG,
        source_commit=SOURCE_COMMIT,
        image_ref=IMAGE_REF,
        namespace=namespace,
        service_jwt_active_kid="production-jwt",
        audit_hash_active_kid="production-audit",
        audit_anchor_base_url=audit_anchor_base_url,
        audit_anchor_namespace="creator-revenue-agent",
    )
    return output


def test_render_production_bundle_rebinds_environment(
    tmp_path: Path,
) -> None:
    output = render(tmp_path)

    namespace_text = (
        output / "namespace.yaml"
    ).read_text(encoding="utf-8")
    kustomization_text = (
        output / "kustomization.yaml"
    ).read_text(encoding="utf-8")
    config_text = (
        output / "config-map.yaml"
    ).read_text(encoding="utf-8")

    assert "name: creator-revenue-agent" in namespace_text
    assert (
        "namespace: creator-revenue-agent"
        in kustomization_text
    )
    assert "  - namespace.yaml" not in kustomization_text
    assert 'SERVICE_JWT_ACTIVE_KID: "production-jwt"' in config_text
    assert 'AUDIT_HASH_ACTIVE_KID: "production-audit"' in config_text
    assert (
        'AUDIT_ANCHOR_BASE_URL: '
        '"https://audit-anchor.production.example.internal"'
        in config_text
    )
    assert (
        'AUDIT_ANCHOR_NAMESPACE: '
        '"creator-revenue-agent"'
        in config_text
    )
    assert "APP_ENV: production" in config_text

    deployment_text = (
        output / "deployment.yaml"
    ).read_text(encoding="utf-8")
    migration_text = (
        output / "migration-job.yaml"
    ).read_text(encoding="utf-8")
    assert deployment_text.count(IMAGE_REF) == 1
    assert migration_text.count(IMAGE_REF) == 1

    service_account_text = (
        output / "service-account.yaml"
    ).read_text(encoding="utf-8")
    assert "imagePullSecrets:" in service_account_text
    assert "  - name: ghcr-pull" in service_account_text

    metadata = json.loads(
        (output / "production-metadata.json").read_text(
            encoding="utf-8"
        )
    )
    config_sha256 = metadata["config_map_sha256"]
    assert len(config_sha256) == 64
    assert (
        'creator-revenue-agent/config-sha256: '
        f'"{config_sha256}"'
        in deployment_text
    )
    assert metadata["version"] == "production-deployment-bundle-v1"
    assert metadata["release_tag"] == RELEASE_TAG
    assert metadata["source_commit"] == SOURCE_COMMIT
    assert metadata["image_ref"] == IMAGE_REF
    assert (
        metadata["namespace"]
        == "creator-revenue-agent"
    )
    assert (output / "SHA256SUMS").is_file()


def test_config_change_changes_pod_template_hash(
    tmp_path: Path,
) -> None:
    first = render(tmp_path)
    first_deployment = (
        first / "deployment.yaml"
    ).read_text(encoding="utf-8")

    source = verified_bundle(tmp_path / "second-source")
    second = tmp_path / "second-production"
    render_production_bundle(
        source_dir=source,
        output_dir=second,
        release_tag=RELEASE_TAG,
        source_commit=SOURCE_COMMIT,
        image_ref=IMAGE_REF,
        namespace="creator-revenue-agent",
        service_jwt_active_kid="production-jwt-rotated",
        audit_hash_active_kid="production-audit",
        audit_anchor_base_url=(
            "https://audit-anchor.production.example.internal"
        ),
        audit_anchor_namespace=(
            "creator-revenue-agent"
        ),
    )
    second_deployment = (
        second / "deployment.yaml"
    ).read_text(encoding="utf-8")

    assert first_deployment != second_deployment


@pytest.mark.parametrize(
    ("namespace", "audit_anchor_base_url"),
    [
        ("Creator-Revenue-Agent", "https://anchor.example"),
        ("bad_namespace", "https://anchor.example"),
        (
            "creator-revenue-agent",
            "http://anchor.example",
        ),
        (
            "creator-revenue-agent",
            "https://user:pass@anchor.example",
        ),
    ],
)
def test_render_production_bundle_rejects_invalid_environment(
    tmp_path: Path,
    namespace: str,
    audit_anchor_base_url: str,
) -> None:
    with pytest.raises(ValueError):
        render(
            tmp_path,
            namespace=namespace,
            audit_anchor_base_url=audit_anchor_base_url,
        )
