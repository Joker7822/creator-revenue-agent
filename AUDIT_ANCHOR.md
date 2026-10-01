# External Audit Anchor Contract

The creator-revenue-agent uses a separate append-only / WORM service to anchor authenticated audit-chain heads.

The external service should be administered independently from the application database. The local `audit_anchor_receipts` table is not authoritative.

## Configuration

```text
AUDIT_ANCHOR_BASE_URL=https://audit-anchor.example.internal
AUDIT_ANCHOR_TOKEN=<secret>
AUDIT_ANCHOR_NAMESPACE=creator-revenue-agent-production
AUDIT_ANCHOR_RECEIPT_KEYS_JSON={"2026-10-current":"<secret>"}
AUDIT_ANCHOR_TIMEOUT_SECONDS=5
```

## Create anchor

```http
POST /v1/anchors
Authorization: Bearer <AUDIT_ANCHOR_TOKEN>
Idempotency-Key: <anchor_id>
Content-Type: application/json
```

Request body:

```json
{
  "namespace": "creator-revenue-agent-production",
  "anchor_id": "anc_...",
  "head_event_id": 1234,
  "head_hash": "<64 hex>",
  "head_state_hash": "<64 hex>",
  "head_hash_key_id": "2026-10-current",
  "requested_by": "audit-anchor-service"
}
```

The service must be append-only for accepted anchors and idempotent by `anchor_id`. Reusing an anchor ID must return the original receipt rather than replacing stored content.

Response status is 200 or 201.

## Latest anchor

```http
GET /v1/anchors/latest?namespace=<namespace>
Authorization: Bearer <AUDIT_ANCHOR_TOKEN>
```

Return 404 when no anchor exists for the namespace. Otherwise return the most recent committed receipt.

## Signed receipt

The response contains the original anchor fields plus:

```json
{
  "receipt_id": "receipt-...",
  "anchored_at": "2026-10-01T00:00:00+00:00",
  "receipt_key_id": "2026-10-current",
  "receipt_signature": "<64 hex>"
}
```

`receipt_signature` is HMAC-SHA256 over compact, sorted JSON containing:

```text
anchor_id
anchored_at
head_event_id
head_hash
head_hash_key_id
head_state_hash
namespace
receipt_id
receipt_key_id
requested_by
version = "audit-anchor-receipt-v1"
```

The signing secret is selected by `receipt_key_id`. The application accepts only keys configured in `AUDIT_ANCHOR_RECEIPT_KEYS_JSON`.

## Rollback detection

Verification first checks the local HMAC audit chain, then fetches the latest external receipt.

```text
external event == local event and hash matches
    -> in_sync

external event < local event and anchored prefix hash matches
    -> local_ahead

external event > local event
    -> rollback_detected

anchored event missing or hash mismatch
    -> rollback_detected / anchor_mismatch
```

This detects a restore of the entire application database to an older internally valid state, provided the external WORM service was not rolled back with it.

## Scheduling

Anchor after security-sensitive release operations and also on a regular operational cadence. A scheduler should call:

```text
POST /v1/audit/anchors
```

using a short-lived credential carrying only the `audit_anchor_operator` role.

The cadence should be chosen from the maximum acceptable rollback-detection gap. Anchoring more frequently narrows that gap.
