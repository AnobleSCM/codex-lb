## Why

A sibling read-only dashboard (claude-balances) needs to render a combined "fleet view" across both AI providers — Claude accounts and codex-lb's pooled OpenAI/Codex accounts — answering "which account has the most room right now, and when does it reset?" at a glance. codex-lb already tracks exactly this per-account state, but the only account endpoint (`GET /api/accounts`) is gated by `validate_dashboard_session` and shaped for the dashboard UI. An external read consumer cannot use it without holding the dashboard password and replicating the session/TOTP flow.

codex-lb serves on `0.0.0.0` (see deployment-networking), so account data is protected by authentication, not by network reachability. Therefore the new read endpoint MUST be authenticated. Rather than expose a dashboard session to an external consumer, this reuses the existing API-key mechanism (api-keys) — the consumer holds a scoped key, the same primitive already used to authorize proxy requests — yielding a stable, minimal, machine-readable summary that is safe under the `0.0.0.0` bind.

## What Changes

- Add `GET /api/fleet/summary`, authenticated by a valid codex-lb API key (reusing the existing api-keys validation), returning a minimal read-only projection of each account's capacity state: `account_id`, `display_name`/`email`, `status`, `plan_type`, primary and secondary window `remaining_percent` + `reset_at` + `window_minutes`, and `last_refresh_at`.
- The response is a deliberately minimal projection of the existing `AccountSummary` — it exposes only the headroom/reset/status fields a fleet view needs. It does NOT expose tokens, auth/token status, raw credit balances, request-cost detail, or any field beyond what the dashboard already shows.
- No change to `GET /api/accounts` or any existing route; no change to how API keys are issued or validated; no change to the bind model.

## Capabilities

### New Capabilities
- `fleet-summary-read`: An API-key-authenticated, read-only endpoint exposing a minimal per-account capacity summary for external fleet/aggregation consumers.

### Modified Capabilities
- `none`: The api-keys mechanism is reused as-is (the new route depends on existing key validation); no api-keys requirement changes.

## Impact

- New read route + minimal response schema, mapped from the existing `AccountSummary` (likely a small router under `app/modules/accounts/` or a dedicated `app/modules/fleet/`).
- Reuses the existing API-key authentication dependency; no new auth machinery, no new credential type.
- Unit/integration tests: auth required (401 without a valid key), correct minimal projection, no over-exposure of sensitive fields, stable shape.
- No migration, no schema/DB change, no change to bind/exposure or to existing endpoints.
