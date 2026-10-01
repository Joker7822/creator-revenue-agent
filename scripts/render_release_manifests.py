from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


TAG_RE = re.compile(
    r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"
)
DIGEST_RE = re.compile(
    r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+"
    r"@sha256:[0-9a-f]{64}$"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PLACEHOLDER = (
    "ghcr.io/replace-me/creator-revenue-agent:replace-me"
)


def validate_inputs(
    *,
    image_ref: str,
    expected_image: str,
    release_tag: str,
    source_commit: str,
) -> None:
    if TAG_RE.fullmatch(release_tag) is None:
        raise ValueError("invalid release tag")

    if COMMIT_RE.fullmatch(source_commit) is None:
        raise ValueError("invalid source commit")

    if DIGEST_RE.fullmatch(image_ref) is None:
        raise ValueError(
            "image reference must be an immutable GHCR sha256 digest"
        )

    expected_prefix = expected_image.lower() + "@sha256:"
    if not image_ref.startswith(expected_prefix):
        raise ValueError(
            "image reference does not match expected repository"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_bundle(
    *,
    source_dir: Path,
    output_dir: Path,
    image_ref: str,
    release_tag: str,
    source_commit: str,
) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(source_dir, output_dir)

    secret_example = output_dir / "secret.example.yaml"
    if secret_example.exists():
        secret_example.unlink()

    for relative in ("deployment.yaml", "migration-job.yaml"):
        path = output_dir / relative
        text = path.read_text(encoding="utf-8")
        count = text.count(PLACEHOLDER)
        if count != 1:
            raise ValueError(
                f"{relative}: expected exactly one image placeholder"
            )
        path.write_text(
            text.replace(PLACEHOLDER, image_ref),
            encoding="utf-8",
        )

    for path in output_dir.glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        if PLACEHOLDER in text:
            raise ValueError(
                f"{path.name}: unresolved image placeholder"
            )
        if re.search(
            r"image:\s+ghcr\.io/[^\s]+:(?!sha256)",
            text,
        ):
            raise ValueError(
                f"{path.name}: mutable image tag is forbidden"
            )

    metadata = {
        "version": "promotion-bundle-v1",
        "release_tag": release_tag,
        "source_commit": source_commit,
        "image_ref": image_ref,
    }
    metadata_path = output_dir / "promotion-metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    checksums: list[str] = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            checksums.append(
                f"{sha256_file(path)}  {path.name}"
            )
    (output_dir / "SHA256SUMS").write_text(
        "\n".join(checksums) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--source-dir",
        default="deploy/kubernetes",
    )
    parser.add_argument(
        "--output-dir",
        default="verified-kubernetes",
    )
    args = parser.parse_args()

    image_ref = args.image_ref.strip().lower()
    expected_image = args.expected_image.strip().lower()
    release_tag = args.release_tag.strip()
    source_commit = args.source_commit.strip().lower()

    validate_inputs(
        image_ref=image_ref,
        expected_image=expected_image,
        release_tag=release_tag,
        source_commit=source_commit,
    )
    render_bundle(
        source_dir=Path(args.source_dir),
        output_dir=Path(args.output_dir),
        image_ref=image_ref,
        release_tag=release_tag,
        source_commit=source_commit,
    )
    print(
        json.dumps(
            {
                "image_ref": image_ref,
                "release_tag": release_tag,
                "source_commit": source_commit,
                "output_dir": args.output_dir,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
