from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse


RECEIPT_VERSION = "audit-anchor-receipt-v1"
HEX_64 = r"^[0-9a-f]{64}$"
ANCHOR_ID = r"^anc_[0-9a-f]{40}$"


class AnchorRequest(BaseModel):
    namespace: str = Field(min_length=1, max_length=120)
    anchor_id: str = Field(pattern=ANCHOR_ID)
    head_event_id: int | None = Field(default=None, ge=1)
    head_hash: str = Field(pattern=HEX_64)
    head_state_hash: str = Field(pattern=HEX_64)
    head_hash_key_id: str = Field(min_length=1, max_length=120)
    requested_by: str = Field(min_length=1, max_length=512)


class AnchorReceipt(AnchorRequest):
    receipt_id: str = Field(min_length=1, max_length=160)
    anchored_at: str = Field(min_length=20, max_length=64)
    receipt_key_id: str = Field(min_length=1, max_length=120)
    receipt_signature: str = Field(pattern=HEX_64)


class AnchorStore(Protocol):
    def get(self, namespace: str, anchor_id: str) -> dict | None: ...

    def put_if_absent(
        self,
        namespace: str,
        anchor_id: str,
        receipt: dict,
    ) -> dict: ...

    def latest(self, namespace: str) -> dict | None: ...


class GcsAnchorStore:
    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage

        self.bucket_name = bucket_name
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    @staticmethod
    def _prefix(namespace: str) -> str:
        encoded = quote(namespace, safe="")
        return f"anchors/{encoded}/"

    @classmethod
    def _object_name(cls, namespace: str, anchor_id: str) -> str:
        return f"{cls._prefix(namespace)}{anchor_id}.json"

    @staticmethod
    def _decode(blob) -> dict:
        try:
            data = json.loads(blob.download_as_text(encoding="utf-8"))
            return AnchorReceipt.model_validate(data).model_dump()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="stored audit anchor receipt is invalid",
            ) from exc

    def get(self, namespace: str, anchor_id: str) -> dict | None:
        blob = self.bucket.blob(self._object_name(namespace, anchor_id))
        try:
            if not blob.exists():
                return None
            return self._decode(blob)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="audit anchor storage unavailable",
            ) from exc

    def put_if_absent(
        self,
        namespace: str,
        anchor_id: str,
        receipt: dict,
    ) -> dict:
        existing = self.get(namespace, anchor_id)
        if existing is not None:
            return existing

        blob = self.bucket.blob(self._object_name(namespace, anchor_id))
        body = json.dumps(
            receipt,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"
        try:
            blob.upload_from_string(
                body,
                content_type="application/json",
                if_generation_match=0,
            )
            return receipt
        except Exception as exc:
            # A concurrent creator can win the generation-zero precondition.
            # Never retry as an overwrite: return the immutable winner instead.
            try:
                existing = self.get(namespace, anchor_id)
            except HTTPException:
                existing = None
            if existing is not None:
                return existing
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="audit anchor storage unavailable",
            ) from exc

    def latest(self, namespace: str) -> dict | None:
        prefix = self._prefix(namespace)
        try:
            blobs = list(
                self.client.list_blobs(
                    self.bucket_name,
                    prefix=prefix,
                )
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="audit anchor storage unavailable",
            ) from exc

        if not blobs:
            return None

        floor = datetime.min.replace(tzinfo=timezone.utc)
        latest_blob = max(
            blobs,
            key=lambda blob: (
                blob.time_created or blob.updated or floor,
                blob.name,
            ),
        )
        return self._decode(latest_blob)


class MemoryAnchorStore:
    """Deterministic in-memory store used only by unit tests."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.order: list[tuple[str, str]] = []

    def get(self, namespace: str, anchor_id: str) -> dict | None:
        row = self.rows.get((namespace, anchor_id))
        return None if row is None else dict(row)

    def put_if_absent(
        self,
        namespace: str,
        anchor_id: str,
        receipt: dict,
    ) -> dict:
        key = (namespace, anchor_id)
        existing = self.rows.get(key)
        if existing is not None:
            return dict(existing)
        self.rows[key] = dict(receipt)
        self.order.append(key)
        return dict(receipt)

    def latest(self, namespace: str) -> dict | None:
        for key in reversed(self.order):
            if key[0] == namespace:
                return dict(self.rows[key])
        return None


def _read_setting(name: str) -> str:
    value = os.getenv(name, "").strip()
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if value and file_name:
        raise RuntimeError(f"configure only one of {name} or {name}_FILE")
    if file_name:
        path = os.path.abspath(file_name)
        try:
            if os.path.getsize(path) > 1024 * 1024:
                raise RuntimeError(f"{name}_FILE exceeds 1 MiB")
            with open(path, encoding="utf-8") as handle:
                value = handle.read().strip()
        except OSError as exc:
            raise RuntimeError(f"unable to read {name}_FILE") from exc
    return value


def _token() -> str:
    value = _read_setting("AUDIT_ANCHOR_TOKEN")
    if len(value) < 32:
        raise RuntimeError("AUDIT_ANCHOR_TOKEN must contain at least 32 characters")
    return value


def _receipt_keys() -> dict[str, str]:
    raw = _read_setting("AUDIT_ANCHOR_RECEIPT_KEYS_JSON")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AUDIT_ANCHOR_RECEIPT_KEYS_JSON is invalid") from exc
    if (
        not isinstance(value, dict)
        or not value
        or not all(
            isinstance(kid, str)
            and kid
            and len(kid) <= 120
            and isinstance(secret, str)
            and len(secret) >= 32
            for kid, secret in value.items()
        )
    ):
        raise RuntimeError("AUDIT_ANCHOR_RECEIPT_KEYS_JSON is invalid")
    return value


def _active_receipt_key() -> tuple[str, str]:
    key_id = os.getenv("AUDIT_ANCHOR_RECEIPT_ACTIVE_KID", "").strip()
    keys = _receipt_keys()
    secret = keys.get(key_id)
    if not key_id or secret is None:
        raise RuntimeError("AUDIT_ANCHOR_RECEIPT_ACTIVE_KID is invalid")
    return key_id, secret


def _bucket_name() -> str:
    value = os.getenv("AUDIT_ANCHOR_BUCKET", "").strip()
    if not value or len(value) > 222:
        raise RuntimeError("AUDIT_ANCHOR_BUCKET is invalid")
    return value


def _store() -> AnchorStore:
    return GcsAnchorStore(_bucket_name())


def _canonical(receipt: dict) -> bytes:
    return json.dumps(
        {
            "anchor_id": receipt["anchor_id"],
            "anchored_at": receipt["anchored_at"],
            "head_event_id": receipt["head_event_id"],
            "head_hash": receipt["head_hash"],
            "head_hash_key_id": receipt["head_hash_key_id"],
            "head_state_hash": receipt["head_state_hash"],
            "namespace": receipt["namespace"],
            "receipt_id": receipt["receipt_id"],
            "receipt_key_id": receipt["receipt_key_id"],
            "requested_by": receipt["requested_by"],
            "version": RECEIPT_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sign(receipt: dict, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        _canonical(receipt),
        hashlib.sha256,
    ).hexdigest()


def _authorize(authorization: str | None) -> None:
    expected = f"Bearer {_token()}"
    provided = authorization or ""
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid audit anchor credential",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _validated_receipt(data: dict) -> dict:
    try:
        return AnchorReceipt.model_validate(data).model_dump()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stored audit anchor receipt is invalid",
        ) from exc


app = FastAPI(
    title="Creator Revenue Agent Audit Anchor",
    version="1",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/anchors")
def create_anchor(
    payload: AnchorRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
):
    _authorize(authorization)
    if idempotency_key != payload.anchor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must equal anchor_id",
        )

    store = _store()
    existing = store.get(payload.namespace, payload.anchor_id)
    if existing is not None:
        return JSONResponse(_validated_receipt(existing), status_code=200)

    key_id, secret = _active_receipt_key()
    receipt = {
        **payload.model_dump(),
        "receipt_id": f"receipt-{payload.anchor_id}",
        "anchored_at": datetime.now(timezone.utc).isoformat(),
        "receipt_key_id": key_id,
    }
    receipt["receipt_signature"] = _sign(receipt, secret)
    receipt = _validated_receipt(receipt)

    stored = store.put_if_absent(
        payload.namespace,
        payload.anchor_id,
        receipt,
    )
    status_code = 201 if stored == receipt else 200
    return JSONResponse(_validated_receipt(stored), status_code=status_code)


@app.get("/v1/anchors/latest")
def latest_anchor(
    namespace: str = Query(min_length=1, max_length=120),
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    receipt = _store().latest(namespace)
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no audit anchor exists for namespace",
        )
    return JSONResponse(_validated_receipt(receipt), status_code=200)
