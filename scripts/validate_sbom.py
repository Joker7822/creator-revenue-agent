from __future__ import annotations

import json
import sys
from pathlib import Path


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) != 2:
        return fail("usage: validate_sbom.py <cyclonedx-json>")

    path = Path(sys.argv[1])
    if not path.is_file():
        return fail(f"SBOM not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return fail(f"invalid SBOM: {type(exc).__name__}")

    if data.get("bomFormat") != "CycloneDX":
        return fail("SBOM is not CycloneDX")

    if not str(data.get("specVersion", "")).strip():
        return fail("SBOM specVersion is missing")

    components = data.get("components")
    if not isinstance(components, list) or not components:
        return fail("SBOM has no components")

    invalid = [
        component
        for component in components
        if not isinstance(component, dict)
        or not str(component.get("name", "")).strip()
    ]
    if invalid:
        return fail("SBOM contains unnamed components")

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return fail("SBOM metadata is missing")

    print(
        "CycloneDX SBOM validated: "
        f"components={len(components)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
