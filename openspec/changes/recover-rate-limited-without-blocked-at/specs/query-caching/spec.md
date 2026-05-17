## MODIFIED Requirements

### Requirement: Request-path selection uses cached usage snapshots
`LoadBalancer.select_account()` on the proxy request path MUST use persisted usage snapshots that are already available in `usage_history` and MUST NOT run `UsageUpdater.refresh_accounts()` inline. Freshness MUST be provided by the background usage refresh scheduler instead of synchronous per-request refresh.

#### Scenario: Restart-safe rate-limit recovery without a persisted block marker uses a strictly later primary reset
- **GIVEN** an account is persisted as `rate_limited`
- **AND** the account record carries a stale runtime reset guard (`Account.reset_at` still in the future from the original block event)
- **AND** the account record has no persisted block marker (`Account.blocked_at` is `NULL`), which is the case for accounts marked `rate_limited` via the usage-data path
- **WHEN** the latest primary-window usage row is recent enough, reports `used_percent < 100`, and carries a `reset_at` strictly later than the stored runtime reset guard
- **THEN** the balancer clears the stale runtime reset guard
- **AND** the account may return to `active` without a manual reactivate action

#### Scenario: Restart-safe rate-limit recovery without a persisted block marker does not trust stale primary usage
- **GIVEN** an account is persisted as `rate_limited`
- **AND** the account record has no persisted block marker
- **WHEN** the latest primary-window usage row was recorded too long ago to satisfy the freshness threshold
- **THEN** the balancer keeps the account in `rate_limited`
- **AND** the stale runtime reset guard remains in effect

#### Scenario: Restart-safe rate-limit recovery without a persisted block marker requires a strictly later reset window
- **GIVEN** an account is persisted as `rate_limited`
- **AND** the account record has no persisted block marker
- **WHEN** the latest primary-window usage row is recent enough and reports `used_percent < 100` but its `reset_at` is the same as or earlier than the stored runtime reset guard
- **THEN** the balancer keeps the account in `rate_limited`
- **AND** the stale runtime reset guard remains in effect
