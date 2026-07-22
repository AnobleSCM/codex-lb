## Context

codex-lb refreshes banked reset credits into a process-local
`RateLimitResetCreditsStore`. Account dashboard summaries already join that
store, while `/api/fleet/summary` deliberately projects a smaller API-key-safe
shape. The latter currently drops reset-credit state entirely.

## Goals / Non-Goals

**Goals:**

- Make the fleet projection use the same live cache as the Accounts dashboard.
- Preserve the fleet key's existing account scope and usage-section policy.
- Distinguish a cached count of zero from an unavailable cache entry.
- Keep the response free of credential and redemption identifiers.

**Non-Goals:**

- No new upstream polling or per-request upstream fetch.
- No reset consumption, account mutation, or dashboard-auth reuse.
- No persistence or schema migration.

## Decisions

### Decision: Project the existing cache instead of calling the dashboard endpoint

The fleet mapper reads the existing per-replica reset-credit store and returns a
minimal typed object. This avoids admin/guest dashboard credentials, avoids N
extra upstream calls per fleet request, and keeps one source of reset-credit
truth inside codex-lb.

### Decision: Nullable object means availability; zero remains a real value

`rateLimitResetCredits: null` means the live cache has no snapshot. An object
with `availableCount: 0` is a confirmed cached zero. Downstream viewers must not
replace `null` with an older manual count.

### Decision: Reuse existing fleet usage authorization

The field is populated only when the API key has both `upstream_limits` and
`account_pool_usage` access and upstream quota visibility is enabled. Otherwise
it is `null`, matching the existing suppression of capacity windows.

## Risks / Trade-offs

- The cache is process-local and can be empty immediately after restart. The
  explicit `null` state keeps that honest until the scheduler repopulates it.
- The snapshot has no independent fetched timestamp today. This change exposes
  the same cache state as the dashboard without claiming a stronger freshness
  guarantee.

## Rollback

Revert the additive response field and redeploy the prior image. No database or
credential rollback is required.
