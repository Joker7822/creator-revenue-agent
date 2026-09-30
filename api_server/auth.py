import os
import secrets

from fastapi import Header, HTTPException, status


def require_service_token(
    authorization: str | None = Header(default=None),
) -> None:
    expected = (
        os.getenv("INTERNAL_API_TOKEN")
        or os.getenv("CUSTOM_API_TOKEN")
    )
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service token is not configured",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )

    supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
        )
