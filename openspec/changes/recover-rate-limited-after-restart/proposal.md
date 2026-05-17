## Why

The 2026-04-14 change `persist-quota-block-recovery-markers` introduced a restart-safe recovery path for `quota_exceeded` accounts by trusting the persisted `blocked_at` marker plus a cooldown threshold. The companion `rate_limited` status was left on a narrower runtime-only behavior — `_state_from_account` in `app/modules/proxy/load_balancer.py` only clears the stale runtime reset guard for `rate_limited` when `runtime.cooldown_until` and `runtime.blocked_at` are both set, and those fields live in the in-memory `RuntimeState` (`app/modules/proxy/load_balancer.py:64`). The inline comment at `app/modules/proxy/load_balancer.py:1065-1067` explicitly acknowledges the gap.

In practice this means a `rate_limited` account can stay stuck after:

- a process restart wipes the runtime cooldown/blocked markers,
- the persisted `Account.reset_at` from the original 429 event is still in the future,
- and the fresh upstream `usage_history` already shows the primary window has rolled over (`used_percent < 100`, newer `reset_at`).

Observed 2026-05-17: `andrewnoble1992@gmail.com` reported `status=rate_limited, reset_at≈+27h, blocked_at≈-4h` while the latest primary usage row had `used_percent=0.0`. The only recovery paths available were waiting for the persisted `reset_at` to pass or the manual `/api/accounts/{id}/reactivate` endpoint. `apply_usage_quota` keeps the account in `rate_limited` on every selection cycle because `effective_runtime_reset` resolves to the stale persisted `reset_at`, and the existing cooldown-clearing branch cannot fire without runtime state.

## What Changes

- Add `RATE_LIMITED_COOLDOWN_SECONDS` to `app/core/balancer/logic.py` and export it from `app/core/balancer/__init__.py`, mirroring the `QUOTA_EXCEEDED_COOLDOWN_SECONDS` precedent.
- Extend the `cooldown_ready` derivation in `app/modules/proxy/load_balancer.py:_state_from_account` so `rate_limited` accounts can become eligible for stale-reset clearing through the persisted `Account.blocked_at` marker plus the new cooldown threshold, in addition to the existing in-memory `runtime.cooldown_until` path.
- Preserve the existing freshness debounce — recovery still requires the most recent `primary_entry.recorded_at` to be strictly newer than `effective_blocked_at`, so stale pre-block usage rows cannot false-recover an account.
- Update the obsolete comment at `app/modules/proxy/load_balancer.py:1062-1067` so it reflects the new behavior.
- Add regression tests in `tests/unit/test_load_balancer.py` mirroring the existing QUOTA_EXCEEDED restart-safe coverage (clears after restart with persisted `blocked_at`, keeps when the persisted `blocked_at` is too recent, keeps when fresh usage is older than the block, keeps when the primary window still reports 100%).

## Impact

- Restart-safe recovery for `rate_limited` accounts closes the symmetric gap with `quota_exceeded`. Stuck accounts no longer require manual reactivation when the upstream window has demonstrably rolled over.
- The freshness debounce keeps the false-recovery guarantees intact: an account cannot return to `active` from `rate_limited` unless a `primary_entry` recorded after the persisted block reports under-capacity usage.
- No change to the 429 ingestion path (`handle_rate_limit`) or to the runtime cooldown duration parsed from `Retry-After`. The new cooldown is a DB-derived fallback used only when the in-memory cooldown is gone.
- No public API surface change. Dashboard `/api/accounts` already reflects `Account.status`, so the badge will simply transition from `rate_limited` to `active` on the next selection cycle once the conditions are met.
