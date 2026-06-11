# Design — fleet summary read endpoint

## Context

claude-balances (a separate localhost viewer for Claude subscription accounts) is gaining a combined "fleet view" that shows Claude and codex-lb accounts on one board, ranked by headroom within each provider. It needs to read codex-lb's per-account capacity state programmatically. This change adds the read surface on the codex-lb side; the claude-balances `/fleet` page (separate repo, separate change) consumes it.

## Key decision: authenticated, not unauthenticated-localhost

The naive design — a small unauthenticated localhost-only read endpoint — is unsafe here. codex-lb's deployment entrypoints bind `0.0.0.0:2455` (`scripts/docker-entrypoint.sh`, `scripts/distroless-entrypoint.py`); account data is protected by `validate_dashboard_session`, not by network reachability. An unauthenticated route added to this codebase would expose account emails and usage on every reachable interface the moment it runs under the repo's own Docker deploy.

Options considered:
1. **Reuse API-key auth (chosen).** The endpoint requires a valid codex-lb API key — the same primitive already used to authorize proxy requests. The consumer (claude-balances) stores one scoped key in the macOS Keychain. Safe under `0.0.0.0`, no new auth machinery, no new credential type, and the credential is a narrow API key rather than the dashboard password.
2. **Reuse `validate_dashboard_session`.** Rejected: forces the consumer to hold the dashboard password and replicate the session/TOTP login — a broader credential and a fragile coupling to the auth flow.
3. **Bind the dashboard/API to loopback, separate from the proxy.** Rejected here: a larger change to the serving/deployment model with broader blast radius; out of scope for adding one read endpoint.

## Data mapping

The response is a minimal projection of the existing `AccountSummary` (`app/modules/accounts/schemas.py`). Per account: `account_id`, `display_name`, `email`, `status`, `plan_type`; primary/secondary windows from `usage.primary_remaining_percent` / `usage.secondary_remaining_percent` paired with `reset_at_primary`/`reset_at_secondary` and `window_minutes_primary`/`window_minutes_secondary`; plus `last_refresh_at`. Excluded by design: `auth` (token status), `capacity_credits_*`/`remaining_credits_*`, `request_usage`, `additional_quotas` detail, and the raw OAuth tokens. The consumer only needs headroom + reset + status to rank accounts and show "use this next."

## Non-goals

- No mutation of any kind (read-only; see spec).
- No change to `/api/accounts`, the dashboard, API-key issuance/validation, or the bind model.
- No new data collection — only re-projects state codex-lb already computes for its own dashboard.
