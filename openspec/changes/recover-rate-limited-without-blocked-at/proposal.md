## Why

The 2026-05-17 change `recover-rate-limited-after-restart` made the `cooldown_ready` derivation in `_state_from_account` (`app/modules/proxy/load_balancer.py`) restart-safe for `rate_limited` accounts that have a persisted `Account.blocked_at` marker. It does not cover accounts that became `rate_limited` via the usage-data path — when `apply_usage_quota` (`app/core/usage/quota.py:42-49`) observes `primary_used >= 100`, it sets `status = AccountStatus.RATE_LIMITED` but does not set `blocked_at`. `_compute_account_state` then writes `next_blocked_at = None` for that status. After a restart, those accounts have `Account.blocked_at = NULL` and the persisted-blocked-at cooldown branch added in the previous change can never fire.

The `quota_exceeded` story already handled this asymmetry through a separate "no-blocked-at" recovery branch (`app/modules/proxy/load_balancer.py:1049-1061`): when `effective_blocked_at is None` and the latest `secondary` usage entry is recent enough, reports `used_percent < 100`, and carries a `reset_at` strictly later than the stale stored runtime reset, the balancer clears `effective_runtime_reset` and `apply_usage_quota` returns `AccountStatus.ACTIVE`. There is no equivalent path for `rate_limited`.

Observed 2026-05-17: `kanso1943@gmail.com` reported `status=rate_limited`, `Account.reset_at≈+2.5h`, `Account.blocked_at=NULL` while the latest primary `usage_history` row had `used_percent=0.0` and `reset_at≈+5h` (a strictly later window than the stale stored guard). The previous `recover-rate-limited-after-restart` change could not recover this account because the persisted-blocked-at cooldown threshold path requires `effective_blocked_at is not None`.

## What Changes

- Add a parallel no-blocked-at recovery branch immediately after the existing `quota_exceeded` branch in `_state_from_account`. The new branch keys on `primary_entry` (mirroring the in-place `rate_limited` freshness check at `app/modules/proxy/load_balancer.py:1092-1093`): when `account.status == AccountStatus.RATE_LIMITED`, `effective_blocked_at is None`, `effective_runtime_reset is not None and > time.time()`, and the latest primary entry is recent, reports `used_percent < 100`, and carries a `reset_at > effective_runtime_reset`, the balancer clears `effective_runtime_reset`.
- Add regression tests in `tests/unit/test_load_balancer.py` mirroring the existing `quota_exceeded` no-blocked-at coverage (recovers when usage shows a new reset window, keeps when fresh usage is missing, keeps when usage stays on the same reset window).
- Document the parallel recovery scenarios under the `query-caching` capability so the spec stays the source of truth.

## Impact

- Accounts that were marked `rate_limited` via the usage-data path (without a recorded `Account.blocked_at`) can now recover automatically once fresh primary usage shows a strictly later reset window. Together with `recover-rate-limited-after-restart`, every `rate_limited` recovery shape that already exists for `quota_exceeded` is now symmetric.
- The new branch is gated on the same four-condition contract as its `quota_exceeded` sibling (`effective_blocked_at is None`, recent enough usage, `used_percent < 100`, strictly later `reset_at`), so it cannot false-recover from a stale pre-block usage row.
- No new public API surface. No persistence change beyond what `apply_usage_quota` already writes.
