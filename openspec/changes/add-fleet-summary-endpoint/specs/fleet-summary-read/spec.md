## ADDED Requirements

### Requirement: API-key-authenticated fleet summary read endpoint
The service MUST expose `GET /api/fleet/summary` that returns a read-only, minimal per-account capacity summary, and MUST require a valid codex-lb API key (the same key mechanism used for proxy authorization). The endpoint MUST NOT accept a dashboard session in place of an API key, and MUST NOT require one.

Because the service binds to a non-loopback interface (see `deployment-networking`), this endpoint MUST NOT be reachable without a valid API key.

#### Scenario: request without an API key is rejected
- **WHEN** `GET /api/fleet/summary` is called with no API key (or an invalid/revoked key)
- **THEN** the service returns a 4xx authentication error and the response body contains no account data

#### Scenario: request with a valid API key returns the summary
- **WHEN** `GET /api/fleet/summary` is called with a valid, active API key
- **THEN** the service returns 200 with a list of per-account summaries, one per managed account

### Requirement: Minimal, non-sensitive projection
The fleet summary response MUST include only the fields needed to render a capacity fleet view, and MUST NOT include OAuth tokens, token/auth status, raw credit balances, or request-cost detail. For each account it MUST include `account_id`, `display_name`, `email`, `status`, `plan_type`, the primary and secondary windows (each with `remaining_percent`, `reset_at`, and `window_minutes` when known), and `last_refresh_at`.

The values MUST be derived from the same source as the dashboard's account view (no new data is collected or exposed beyond what the dashboard already shows).

#### Scenario: response omits sensitive fields
- **WHEN** a valid fleet summary response is returned
- **THEN** it contains the per-account capacity fields listed above
- **AND** it contains no OAuth access/refresh/id token, no auth/token-status object, no raw capacity/remaining credit amounts, and no request-cost detail

#### Scenario: window remaining and reset are exposed per account
- **WHEN** an account has a known primary window at 62% remaining resetting at a given time, and a secondary window at 80% remaining
- **THEN** the account's summary reports `primary.remaining_percent = 62` with that `reset_at`, and `secondary.remaining_percent = 80`, each with its `window_minutes` when known

### Requirement: Read-only and non-mutating
The endpoint MUST be read-only: it MUST NOT change account state, refresh tokens, alter routing, consume usage, or trigger any upstream call. Repeated requests MUST have no side effects on accounts or usage.

#### Scenario: repeated reads do not mutate state
- **WHEN** `GET /api/fleet/summary` is called repeatedly
- **THEN** no account status, token, usage counter, or routing state changes as a result
