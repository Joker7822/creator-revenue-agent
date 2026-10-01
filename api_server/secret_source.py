from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, status


MAX_SECRET_BYTES = 1_048_576


def read_secret_setting(
    name: str,
    *,
    default: str = "",
) -> str:
    direct = os.getenv(name)
    file_path = os.getenv(f"{name}_FILE")

    if direct is not None and file_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name} and {name}_FILE cannot both be set",
        )

    if file_path:
        path = Path(file_path)
        try:
            if not path.is_file():
                raise OSError("not a regular file")
            size = path.stat().st_size
            if size <= 0 or size > MAX_SECRET_BYTES:
                raise OSError("secret file size is invalid")
            value = path.read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{name}_FILE cannot be read",
            ) from exc

        if not value:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{name}_FILE is empty",
            )
        return value

    return (direct if direct is not None else default).strip()
