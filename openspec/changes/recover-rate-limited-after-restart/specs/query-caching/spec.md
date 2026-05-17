## MODIFIED Requirements

### Requirement: Request-path selection uses cached usage snapshots
`LoadBalancer.select_account()` on the proxy request path MUST use persisted usage snapshots that are already available in `usage_history` and MUST NOT run `UsageUpdater.refresh_accounts()` inline. Freshness MUST be provided by the background usage refresh scheduler instead of synchronous per-request refresh.

#### Scenario: Restart-safe rate-limit recovery uses fresh post-block primary usage
- **GIVEN** an account is persisted as `rate_limited`
- **AND** the original blocking process is no longer running, so the in-memory runtime cooldown markers are gone
- **AND** the account record still contains a persisted block marker from when the rate limit was first detected
- **WHEN** a later selection pass sees a fresh primary-window usage row whose `recorded_at` is newer than that persisted block marker
- **AND** the rate-limit debounce interval has expired
- **AND** the fresh primary usage reports `used_percent < 100`
- **THEN** the balancer clears the stale runtime reset guard
- **AND** the account may return to `active` without a manual reactivate action

#### Scenario: Restart-safe rate-limit recovery does not trust stale pre-block usage
- **GIVEN** an account is persisted as `rate_limited`
- **AND** the account record contains a persisted block marker
- **WHEN** selection only has primary-window usage rows whose `recorded_at` is older than or equal to that persisted block marker
- **THEN** the balancer keeps the account in `rate_limited`
- **AND** the stale persisted `reset_at` guard remains in effect

#### Scenario: Restart-safe rate-limit recovery respects the debounce window
- **GIVEN** an account is persisted as `rate_limited`
- **AND** the account record contains a persisted block marker
- **WHEN** the persisted block marker is younger than the rate-limit cooldown threshold
- **THEN** the balancer keeps the account in `rate_limited` regardless of how fresh the latest primary-window usage row is

#### Scenario: An active in-memory rate-limit cooldown is not shortened by the DB-derived fallback
- **GIVEN** an account is persisted as `rate_limited`
- **AND** the in-memory `RuntimeState.cooldown_until` is set to a future time, reflecting a `Retry-After`-derived hold that has not yet expired
- **WHEN** the persisted `blocked_at` marker would otherwise satisfy the DB-derived rate-limit cooldown threshold on its own
- **THEN** the balancer keeps the account in `rate_limited` until the in-memory cooldown also expires
- **AND** the DB-derived fallback only takes effect when the in-memory cooldown is absent (e.g., after a process restart that wiped runtime state)

#### Scenario: Restart-safe rate-limit recovery does not flip an account whose primary window is still saturated
- **GIVEN** an account is persisted as `rate_limited`
- **AND** the account record contains a persisted block marker older than the rate-limit cooldown threshold
- **WHEN** the latest primary-window usage row recorded after the block still reports `used_percent >= 100`
- **THEN** the balancer keeps the account in `rate_limited`
- **AND** the stale runtime reset guard is not cleared
