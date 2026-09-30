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
