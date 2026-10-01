from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError


def lock_row(
    session: Session,
    model: Any,
    key_column: Any,
    key_value: Any,
):
    return session.scalar(
        select(model)
        .where(key_column == key_value)
        .with_for_update()
    )


def commit_state_change(
    session: Session,
    *,
    conflict_detail: str = "concurrent state change detected",
) -> None:
    try:
        session.commit()
    except StaleDataError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=conflict_detail,
        ) from exc


def rollback_integrity_conflict(
    session: Session,
    exc: IntegrityError,
    *,
    detail: str,
) -> None:
    session.rollback()
    raise HTTPException(
        status_code=409,
        detail=detail,
    ) from exc
