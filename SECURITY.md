# Security

ASTRAL handles potentially sensitive orbital and operator data. Its security controls are reasonable for a research deployment; they are **not** equivalent to a reviewed agency identity and security programme.

## Reporting a vulnerability

Email the maintainers privately (do not open a public issue) with steps to reproduce. Expect acknowledgement within 5 working days.

## Threat model (summary)

| Asset | Threats | Controls |
|---|---|---|
| Operator datasets, results | Cross-project access, IDOR, leakage via errors | Every project route enforces membership/role server-side; 404 for missing *and* forbidden; admins have no implicit data access; error bodies carry code/message/request id only |
| Accounts | Credential stuffing, brute force, session theft, CSRF | Argon2id (RFC 9106 profile), ≥ 12-char passwords, lockout after 5 failures (15 min), auth rate limit, httpOnly SameSite=Lax cookies (Secure in production), per-session CSRF token on unsafe methods, hashed tokens at rest, revocation |
| Server | Malicious uploads, XML bombs, path traversal, DoS | Size limits (header and streamed), UTF-8/ASCII text only, `defusedxml`, server-generated storage keys validated against a strict pattern, filenames never used as paths, per-user job quotas, object/window limits, concurrency cap, rate limits |
| Integrity of results | Tampered inputs/artefacts | SHA-256 of raw files, snapshots, reports and model artefacts; verified before use/download |
| Secrets | Leakage in logs/repo | Settings from environment only; `.env` gitignored; audit details redact keys containing password/token/secret/credential; production refuses the default secret key, SQLite or insecure cookies |
| Browser | XSS, clickjacking | React escaping, CSP `default-src 'self'`, `frame-ancestors 'none'`, nosniff, no-referrer, HSTS when secure |
| Injection | SQL injection | SQLAlchemy parameterised queries; sort keys mapped through allow-lists |

## Data flow

Browser → (TLS proxy) → API → PostgreSQL (metadata) and object store volume (raw/snapshots/reports/models) → worker (same DB and volume). Optional outbound HTTPS to CelesTrak/Space-Track only when explicitly triggered.

## Audit

Recorded: logins (including denied), logout, API token create/revoke, uploads (including rejected), approvals, transformations, job submit/complete/cancel, scenario create/delete, all exports, admin account changes, ML train/activate.

## Identity provider path

Users carry an `external_subject` column for OIDC `sub`. An OIDC login (authorisation code + PKCE) mapping to local roles is **not yet implemented** (ROADMAP R7). Until then use local accounts behind a VPN or SSO-enforcing proxy.

## Verification checklist (tests in `backend/tests/security`)

- [x] Unauthenticated requests rejected
- [x] Lockout after repeated failures
- [x] Cross-project isolation (including admins)
- [x] Viewer cannot write; non-owner cannot manage members
- [x] CSRF enforced for cookie sessions; bearer tokens work without cookies
- [x] Non-admins cannot administer
- [x] Upload size limit
- [x] Storage keys cannot escape; filenames never become paths
- [x] Injection strings in query parameters are inert
- [x] Job quotas
- [x] Security headers and error shape
- [x] Audit records with redaction
- [ ] Penetration test by a third party (not done)
- [ ] Shared rate limiter for multi-replica deployments (not done)
