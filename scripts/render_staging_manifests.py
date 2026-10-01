from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit


TAG_RE = re.compile(
    r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(
    r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+"
    r"@sha256:[0-9a-f]{64}$"
)
NAMESPACE_RE = re.compile(
    r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$"
)

BASE_NAMESPACE = "creator-revenue-agent"

CONFIG_KEYS = (
    "SERVICE_JWT_ACTIVE_KID",
    "AUDIT_HASH_ACTIVE_KID",
    "AUDIT_ANCHOR_BASE_URL",
    "AUDIT_ANCHOR_NAMESPACE",
)

REQUIRED_SOURCE_FILES = (
    "namespace.yaml",
    "service-account.yaml",
    "config-map.yaml",
    "deployment.yaml",
    "service.yaml",
    "pdb.yaml",
    "hpa.yaml",
    "network-policy.yaml",
    "kustomization.yaml",
    "migration-job.yaml",
    "promotion-metadata.json",
    "SHA256SUMS",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_text_value(
    name: str,
    value: str,
    *,
    maximum: int = 256,
) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} must be a single line")
    if len(value) > maximum:
        raise ValueError(
            f"{name} exceeds maximum length {maximum}"
        )
    return value


def validate_inputs(
    *,
    release_tag: str,
    source_commit: str,
    image_ref: str,
    namespace: str,
    service_jwt_active_kid: str,
    audit_hash_active_kid: str,
    audit_anchor_base_url: str,
    audit_anchor_namespace: str,
) -> None:
    if TAG_RE.fullmatch(release_tag) is None:
        raise ValueError("invalid release tag")
    if COMMIT_RE.fullmatch(source_commit) is None:
        raise ValueError("invalid source commit")
    if IMAGE_RE.fullmatch(image_ref) is None:
        raise ValueError(
            "image reference must be an immutable GHCR sha256 digest"
        )
    if NAMESPACE_RE.fullmatch(namespace) is None:
        raise ValueError(
            "namespace must be a valid Kubernetes DNS label"
        )

    validate_text_value(
        "service_jwt_active_kid",
        service_jwt_active_kid,
        maximum=128,
    )
    validate_text_value(
        "audit_hash_active_kid",
        audit_hash_active_kid,
        maximum=128,
    )
    validate_text_value(
        "audit_anchor_namespace",
        audit_anchor_namespace,
        maximum=256,
    )

    anchor_url = validate_text_value(
        "audit_anchor_base_url",
        audit_anchor_base_url,
        maximum=2048,
    )
    parsed = urlsplit(anchor_url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "audit_anchor_base_url must be HTTPS and must not "
            "contain embedded credentials"
        )


def verify_sha256s(source_dir: Path) -> None:
    sums_path = source_dir / "SHA256SUMS"
    if not sums_path.is_file():
        raise ValueError("source promotion bundle lacks SHA256SUMS")

    for line_number, raw in enumerate(
        sums_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        parts = raw.split("  ", 1)
        if len(parts) != 2:
            raise ValueError(
                f"SHA256SUMS:{line_number}: invalid checksum line"
            )
        expected, relative = parts
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError(
                f"SHA256SUMS:{line_number}: invalid sha256"
            )

        path = source_dir / relative
        try:
            path.resolve().relative_to(source_dir.resolve())
        except ValueError as exc:
            raise ValueError(
                "SHA256SUMS contains path traversal"
            ) from exc

        if not path.is_file():
            raise ValueError(
                f"SHA256SUMS references missing file: {relative}"
            )
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(
                f"checksum mismatch for {relative}"
            )


def require_source_bundle(
    *,
    source_dir: Path,
    release_tag: str,
    source_commit: str,
    image_ref: str,
) -> dict[str, object]:
    if not source_dir.is_dir():
        raise ValueError("source promotion bundle is missing")

    missing = [
        name
        for name in REQUIRED_SOURCE_FILES
        if not (source_dir / name).is_file()
    ]
    if missing:
        raise ValueError(
            "source promotion bundle is missing: "
            + ", ".join(missing)
        )

    verify_sha256s(source_dir)

    metadata = json.loads(
        (source_dir / "promotion-metadata.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "version": "promotion-bundle-v1",
        "release_tag": release_tag,
        "source_commit": source_commit,
        "image_ref": image_ref,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(
                f"promotion metadata mismatch for {key}"
            )
    return metadata


def replace_exact_once(
    path: Path,
    old: str,
    new: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise ValueError(
            f"{path.name}: expected exactly one occurrence of "
            f"{old!r}, found {count}"
        )
    path.write_text(
        text.replace(old, new),
        encoding="utf-8",
    )


def replace_config_value(
    path: Path,
    key: str,
    value: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^(  {re.escape(key)}:).*$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError(
            f"{path.name}: expected exactly one {key} setting"
        )
    quoted = json.dumps(value)
    text = pattern.sub(
        lambda match: f"{match.group(1)} {quoted}",
        text,
        count=1,
    )
    path.write_text(text, encoding="utf-8")


def inject_config_hash(
    deployment_path: Path,
    *,
    config_sha256: str,
) -> None:
    text = deployment_path.read_text(encoding="utf-8")
    marker = (
        "  template:\n"
        "    metadata:\n"
        "      labels:\n"
    )
    if text.count(marker) != 1:
        raise ValueError(
            "deployment.yaml: expected exactly one pod template "
            "metadata block"
        )
    replacement = (
        "  template:\n"
        "    metadata:\n"
        "      annotations:\n"
        "        creator-revenue-agent/config-sha256: "
        f"\"{config_sha256}\"\n"
        "      labels:\n"
    )
    deployment_path.write_text(
        text.replace(marker, replacement, 1),
        encoding="utf-8",
    )


def verify_image_identity(
    path: Path,
    image_ref: str,
) -> None:
    image_values: list[str] = []
    for raw in path.read_text(
        encoding="utf-8"
    ).splitlines():
        stripped = raw.strip()
        if not stripped.startswith("image:"):
            continue
        value = stripped.split(":", 1)[1].strip()
        image_values.append(value.strip("'\""))

    if image_values != [image_ref]:
        raise ValueError(
            f"{path.name}: expected exactly one image equal to "
            "the attested digest"
        )


def write_sha256s(output_dir: Path) -> None:
    lines: list[str] = []
    for path in sorted(output_dir.iterdir()):
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        lines.append(f"{sha256_file(path)}  {path.name}")
    (output_dir / "SHA256SUMS").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def render_staging_bundle(
    *,
    source_dir: Path,
    output_dir: Path,
    release_tag: str,
    source_commit: str,
    image_ref: str,
    namespace: str,
    service_jwt_active_kid: str,
    audit_hash_active_kid: str,
    audit_anchor_base_url: str,
    audit_anchor_namespace: str,
) -> None:
    validate_inputs(
        release_tag=release_tag,
        source_commit=source_commit,
        image_ref=image_ref,
        namespace=namespace,
        service_jwt_active_kid=service_jwt_active_kid,
        audit_hash_active_kid=audit_hash_active_kid,
        audit_anchor_base_url=audit_anchor_base_url,
        audit_anchor_namespace=audit_anchor_namespace,
    )

    source_metadata = require_source_bundle(
        source_dir=source_dir,
        release_tag=release_tag,
        source_commit=source_commit,
        image_ref=image_ref,
    )
    source_metadata_sha256 = sha256_file(
        source_dir / "promotion-metadata.json"
    )

    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(source_dir, output_dir)

    sums_path = output_dir / "SHA256SUMS"
    if sums_path.exists():
        sums_path.unlink()

    replace_exact_once(
        output_dir / "namespace.yaml",
        f"  name: {BASE_NAMESPACE}\n",
        f"  name: {namespace}\n",
    )
    kustomization_path = output_dir / "kustomization.yaml"
    replace_exact_once(
        kustomization_path,
        f"namespace: {BASE_NAMESPACE}\n",
        f"namespace: {namespace}\n",
    )
    replace_exact_once(
        kustomization_path,
        "resources:\n  - namespace.yaml\n",
        "resources:\n",
    )

    config_path = output_dir / "config-map.yaml"
    replacements = {
        "SERVICE_JWT_ACTIVE_KID": service_jwt_active_kid,
        "AUDIT_HASH_ACTIVE_KID": audit_hash_active_kid,
        "AUDIT_ANCHOR_BASE_URL": audit_anchor_base_url,
        "AUDIT_ANCHOR_NAMESPACE": audit_anchor_namespace,
    }
    for key, value in replacements.items():
        replace_config_value(config_path, key, value)

    config_sha256 = sha256_file(config_path)
    inject_config_hash(
        output_dir / "deployment.yaml",
        config_sha256=config_sha256,
    )

    app_env_pattern = re.compile(
        r"^  APP_ENV:\s*production\s*$",
        re.MULTILINE,
    )
    if app_env_pattern.search(
        config_path.read_text(encoding="utf-8")
    ) is None:
        raise ValueError(
            "staging rehearsal must retain APP_ENV=production"
        )

    verify_image_identity(
        output_dir / "deployment.yaml",
        image_ref,
    )
    verify_image_identity(
        output_dir / "migration-job.yaml",
        image_ref,
    )

    for path in output_dir.glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        if "ghcr.io/replace-me/" in text:
            raise ValueError(
                f"{path.name}: unresolved image placeholder"
            )
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("image:"):
                continue
            value = stripped.split(":", 1)[1].strip()
            value = value.strip("'\"")
            if (
                value.startswith("ghcr.io/")
                and "@sha256:" not in value
            ):
                raise ValueError(
                    f"{path.name}: mutable GHCR image is forbidden"
                )

    metadata = {
        "version": "staging-rehearsal-bundle-v1",
        "release_tag": release_tag,
        "source_commit": source_commit,
        "image_ref": image_ref,
        "namespace": namespace,
        "service_jwt_active_kid": service_jwt_active_kid,
        "audit_hash_active_kid": audit_hash_active_kid,
        "audit_anchor_base_url": audit_anchor_base_url,
        "audit_anchor_namespace": audit_anchor_namespace,
        "config_map_sha256": config_sha256,
        "source_promotion_metadata_sha256": (
            source_metadata_sha256
        ),
        "source_promotion_version": source_metadata.get(
            "version"
        ),
    }
    (output_dir / "staging-metadata.json").write_text(
        json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    write_sha256s(output_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument(
        "--service-jwt-active-kid",
        required=True,
    )
    parser.add_argument(
        "--audit-hash-active-kid",
        required=True,
    )
    parser.add_argument(
        "--audit-anchor-base-url",
        required=True,
    )
    parser.add_argument(
        "--audit-anchor-namespace",
        required=True,
    )
    args = parser.parse_args()

    render_staging_bundle(
        source_dir=Path(args.source_dir),
        output_dir=Path(args.output_dir),
        release_tag=args.release_tag.strip(),
        source_commit=args.source_commit.strip().lower(),
        image_ref=args.image_ref.strip().lower(),
        namespace=args.namespace.strip(),
        service_jwt_active_kid=(
            args.service_jwt_active_kid.strip()
        ),
        audit_hash_active_kid=(
            args.audit_hash_active_kid.strip()
        ),
        audit_anchor_base_url=(
            args.audit_anchor_base_url.strip()
        ),
        audit_anchor_namespace=(
            args.audit_anchor_namespace.strip()
        ),
    )

    print(
        json.dumps(
            {
                "output_dir": args.output_dir,
                "release_tag": args.release_tag.strip(),
                "source_commit": (
                    args.source_commit.strip().lower()
                ),
                "image_ref": args.image_ref.strip().lower(),
                "namespace": args.namespace.strip(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
