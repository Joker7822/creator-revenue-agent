from __future__ import annotations

import json
import sys
from dataclasses import asdict

from api_server.migration_runtime import (
    current_revision,
    head_revision,
)
from api_server.production_check import (
    Check,
    production_configuration_checks,
)


def release_gate_checks() -> list[Check]:
    checks = list(production_configuration_checks())

    try:
        current = current_revision()
        head = head_revision()
        checks.append(
            Check(
                name="database_revision",
                ok=current == head,
                detail=f"current={current!r}, head={head!r}",
            )
        )
    except Exception as exc:
        checks.append(
            Check(
                name="database_revision",
                ok=False,
                detail=type(exc).__name__,
            )
        )

    return checks


def main() -> int:
    checks = release_gate_checks()
    payload = {
        "ready": all(check.ok for check in checks),
        "checks": [asdict(check) for check in checks],
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
