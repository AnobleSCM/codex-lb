## 1. Response schema

- [x] 1.1 Add a minimal `FleetAccountSummary` / `FleetSummaryResponse` schema (DashboardModel) projecting only: `account_id`, `display_name`, `email`, `status`, `plan_type`, `primary` and `secondary` windows (`remaining_percent`, `reset_at`, `window_minutes`), `last_refresh_at`. Exclude tokens, auth status, raw credits, request-cost detail. — `app/modules/fleet/schemas.py`
- [x] 1.2 Add a mapper from the existing `AccountSummary` to the minimal `FleetAccountSummary` (reuse `AccountUsage.primary_remaining_percent` / `secondary_remaining_percent`, `reset_at_primary`/`secondary`, `window_minutes_primary`/`secondary`). — `app/modules/fleet/mappers.py`

## 2. Endpoint + auth

- [x] 2.1 Add `GET /api/fleet/summary` returning `FleetSummaryResponse`, guarded by an always-enforcing API-key dependency `validate_fleet_api_key` (NOT `validate_dashboard_session`, and deliberately NOT the toggle-dependent `validate_proxy_api_key`). — `app/modules/fleet/api.py`, `app/core/auth/dependencies.py`
- [x] 2.2 Confirm the route is unreachable without a valid API key (401), including when the `api_key_auth_enabled` proxy toggle is disabled. — covered by `tests/integration/test_fleet_summary_api.py`
- [x] 2.3 Register the router; ensure no existing route, dependency, or the `0.0.0.0` bind is altered. — `app/main.py`

## 3. Tests

- [x] 3.1 Test: request without an API key → rejected (no account data in body).
- [x] 3.2 Test: request with a valid API key → 200 with the minimal projection for all accounts.
- [x] 3.3 Test: response contains NONE of the excluded sensitive fields (tokens, auth status, raw credit balances, request-cost detail).
- [x] 3.4 Test: primary/secondary remaining_percent + reset_at + window_minutes map correctly from a fixture `AccountSummary`.

## 4. OpenSpec sync

- [ ] 4.1 Validate the change: `openspec validate --specs` (and `openspec validate add-fleet-summary-endpoint`). — BLOCKED: `openspec` CLI not installed locally (no npx/uv/local bin). Run before merge.
- [ ] 4.2 On verify, sync the `fleet-summary-read` delta into `openspec/specs/fleet-summary-read/` and archive the change. — deferred to verification/merge step per the proposal.
