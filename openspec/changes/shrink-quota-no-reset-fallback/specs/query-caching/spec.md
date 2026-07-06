## ADDED Requirements

### Requirement: Quota block without a reset hint uses a bounded short fallback

When `handle_quota_exceeded` records a quota/usage-limit failure whose upstream
error carries no reset hint (`resets_at` and `resets_in_seconds` both absent),
the persisted `reset_at` MUST be `now + QUOTA_EXCEEDED_NO_RESET_FALLBACK_SECONDS`
(default 900) rather than a multi-hour horizon. This bounds how long a no-hint
quota block excludes an account from selection, so a transient upstream failure
misread as quota exhaustion is re-evaluated inside codex-lb's auto-recovery
window (background `/wham/usage` refresh + per-status cooldown) instead of
benching the account for an hour. An explicit upstream reset hint, when present,
MUST always be honored instead of the fallback.

#### Scenario: Quota error with no reset hint benches for the short fallback
- **GIVEN** an account transitions to `QUOTA_EXCEEDED`
- **AND** the upstream error carries neither `resets_at` nor `resets_in_seconds`
- **WHEN** `handle_quota_exceeded` records the failure
- **THEN** the account's `reset_at` is `now + QUOTA_EXCEEDED_NO_RESET_FALLBACK_SECONDS`
- **AND** `reset_at` is strictly less than `now + 3600`

#### Scenario: Explicit upstream reset hint overrides the fallback
- **GIVEN** an account transitions to `QUOTA_EXCEEDED`
- **AND** the upstream error carries `resets_in_seconds = 120`
- **WHEN** `handle_quota_exceeded` records the failure
- **THEN** the account's `reset_at` is `now + 120`
- **AND** the no-reset fallback horizon is not applied

#### Scenario: A quota-exceeded account is excluded while its reset is in the future
- **GIVEN** an account has `status = QUOTA_EXCEEDED` and `reset_at` in the future
- **AND** its freshest `used_percent` shows the primary window has headroom
- **WHEN** `select_account` evaluates it as the pool's only candidate
- **THEN** `select_account` returns `account = None`
- **AND** the same account shape is selectable once `reset_at` has passed
