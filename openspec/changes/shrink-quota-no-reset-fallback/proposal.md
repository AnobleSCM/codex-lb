## Why

When an upstream quota/usage-limit error arrives with no reset hint,
`handle_quota_exceeded` in `app/core/balancer/logic.py` persists
`reset_at = now + 3600` (1 hour). `select_account` then excludes that account
from selection until `reset_at` passes — it keys on `reset_at` alone and never
re-consults the account's freshest `used_percent`. So a quota error that carried
no `resets_at` / `resets_in_seconds` benches the account for a full hour, even
when the underlying cause was a transient upstream 5xx or a degraded-mode blip
rather than a genuine multi-hour quota exhaustion.

This matters because OpenAI reset events propagate lazily through `/wham/usage`
(https://github.com/Soju06/codex-lb/issues/676): the recovery signal codex-lb
relies on can lag the real upstream state. codex-lb's own recovery machinery —
the background usage refresh (default `usage_refresh_interval_seconds` = 60s) and
the per-status cooldowns (`QUOTA_EXCEEDED_COOLDOWN_SECONDS` = 120s) — brings a
genuinely-available account back well inside 15 minutes once the upstream
limiter catches up. A 1-hour fallback is far longer than that recovery window.

Observed 2026-07-05 (18:40–19:00Z): the pool went fully degraded
(`set_degraded("all upstream accounts are unavailable")`, ~130 log occurrences
in the window) and accounts were held on stale reset horizons noticeably longer
than the upstream limiter actually required; the pool then recovered silently.
Shrinking the no-hint fallback bounds the blast radius of exactly this failure.

## What Changes

- Add `QUOTA_EXCEEDED_NO_RESET_FALLBACK_SECONDS` (default `900`) to
  `app/core/balancer/logic.py`, alongside `QUOTA_EXCEEDED_COOLDOWN_SECONDS` /
  `RATE_LIMITED_COOLDOWN_SECONDS`, and export it from
  `app/core/balancer/__init__.py` (mirroring the existing cooldown-constant
  export precedent).
- Replace the literal `int(time.time() + 3600)` no-reset fallback in
  `handle_quota_exceeded` with `int(time.time() + QUOTA_EXCEEDED_NO_RESET_FALLBACK_SECONDS)`.
- Add regression tests in `tests/unit/test_load_balancer.py`: the shortened
  fallback horizon, the explicit-reset-hint-is-honored guard, and a test that
  reproduces the stale-reset selection block (a QUOTA_EXCEEDED account with a
  future `reset_at` is excluded despite fresh `used_percent` headroom).

## Impact

- A no-reset-hint quota block now benches an account for at most ~15 minutes
  instead of 1 hour, so a transient upstream 5xx misread as quota exhaustion no
  longer removes an account from the failover pool for an hour. When the block
  is genuine, the account is simply re-evaluated ~45 minutes sooner and, if
  still exhausted, re-blocked on the next error — net behavior no worse than a
  client retrying against a hard-capped account today.
- **Scope boundary (intentional):** this change does NOT alter the
  `reset_at`-only selection logic in `select_account`, and it does NOT add an
  active probe to wake a lazily-propagating `/wham/usage`. It only shortens the
  *duration* of the no-hint bench. Actively re-probing a cooled account when the
  pool is fully degraded is tracked as a separate, larger change
  (`auto-probe-on-degradation`) so its guardrails (probe-storm control, cost,
  hot-path isolation) get a focused review.
- No public API, schema, persistence, or upstream-HTTP change. An explicit
  upstream reset hint continues to be honored exactly as before.
