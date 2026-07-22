## ADDED Requirements

### Requirement: Fleet summary requires API key authentication

The system SHALL expose `GET /api/fleet/summary` for trusted local fleet
consumers. The route MUST require a valid Bearer API key even when global proxy
API-key authentication is disabled.

#### Scenario: Valid fleet summary key returns account capacity and reset-credit state

- **WHEN** a client calls `GET /api/fleet/summary` with a valid API key whose
  usage policy permits `upstream_limits` and `account_pool_usage`
- **THEN** the response includes `accounts[]`
- **AND** each account includes `accountId`, `displayName`, `email`, `status`,
  `planType`, `primary`, `secondary`, `lastRefreshAt`, and
  `rateLimitResetCredits`
- **AND** a cached reset-credit snapshot is projected as `availableCount` and
  `nearestExpiresAt`
- **AND** a cached `availableCount: 0` remains a confirmed zero
- **AND** an account without a cached snapshot returns
  `rateLimitResetCredits: null`

#### Scenario: Ineligible account does not expose a stale cache entry

- **GIVEN** a paused, reauthentication-required, or deactivated account still
  has an older process-local reset-credit snapshot
- **WHEN** a valid fleet client requests the summary
- **THEN** that account returns `rateLimitResetCredits: null`

#### Scenario: Account without upstream identity does not expose a stale cache entry

- **GIVEN** an account without a ChatGPT account identity still has an older
  process-local reset-credit snapshot
- **WHEN** a valid fleet client requests the summary
- **THEN** that account returns `rateLimitResetCredits: null`

#### Scenario: Usage policy suppresses reset-credit state

- **WHEN** a valid API key lacks either required usage section or upstream
  quota visibility is disabled
- **THEN** `rateLimitResetCredits` is `null`

### Requirement: Fleet summary excludes sensitive data

Fleet summary responses MUST NOT include OAuth token material, auth token
status, credit identifiers or descriptions, redemption request material,
request-cost detail, additional quota detail, or deactivation reasons.

#### Scenario: Reset-credit projection remains minimal

- **WHEN** a cached reset-credit snapshot contains credit items
- **THEN** the fleet response includes only its available count and nearest
  expiry
- **AND** no credit id, title, description, grant timestamp, redemption
  timestamp, or token field is returned
