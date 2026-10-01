# Security and Compliance Baseline

## Repository rules

- Never store explicit media in GitHub.
- Never commit API keys, tokens, payment credentials, identity documents, or consent evidence.
- Keep production assets and verification records in dedicated private systems.
- Use GitHub Actions secrets for service credentials.

## Adult-content safeguards

- Reject minors and age-ambiguous persons.
- Require positive age verification before adult-content workflows continue.
- Require documented consent.
- Require separately verified consent for sexual depictions of real people.
- Require policy success before an approval record can be created.
- Keep human review enabled by default.
- Do not use the system for coercive, exploitative, non-consensual, or otherwise illegal sexual material.

## Approval and audit

- Approval decisions store reviewer identity, reason and timestamps.
- Decision events are added to the audit table.
- The public API exposes no audit-delete operation.
- Production databases should apply backup, retention and access-control policies separately.

## API security

The starter uses bearer authentication for simplicity. Production deployments should prefer:

- short-lived JWT/service credentials
- HMAC request signing
- mTLS
- secret rotation
- audit logging
- replay protection
- least-privilege service roles


## Server-authoritative workflow state

- Persisted job verification facts are authoritative for policy evaluation.
- A caller cannot upgrade an existing job by resubmitting more permissive age or consent booleans.
- `REQUIRE_HUMAN_REVIEW=true` is enforced server-side and cannot be bypassed with `required=false`.
- Publication continues to require a persisted allowed policy result and an approved approval record.


## Production change controls

- Experiment reviews never mutate production directly.
- Change sets are derived server-side from approved experiment evidence.
- Rollout approval requires a distinct actor from the result reviewer and change-set creator.
- Rollout apply performs an optimistic state check before mutation.
- Price changes are capped to the experiment's 10% safety bound.
- Current actor strings are still caller-asserted behind service authentication; production should derive actors from cryptographically authenticated identities and authorization roles.
