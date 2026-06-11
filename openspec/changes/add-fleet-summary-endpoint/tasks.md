## 1. Response schema

- [ ] 1.1 Add a minimal `FleetAccountSummary` / `FleetSummaryResponse` schema (DashboardModel) projecting only: `account_id`, `display_name`, `email`, `status`, `plan_type`, `primary` and `secondary` windows (`remaining_percent`, `reset_at`, `window_minutes`), `last_refresh_at`. Exclude tokens, auth status, raw credits, request-cost detail.
- [ ] 1.2 Add a mapper from the existing `AccountSummary` to the minimal `FleetAccountSummary` (reuse `AccountUsage.primary_remaining_percent` / `secondary_remaining_percent`, `reset_at_primary`/`secondary`, `window_minutes_primary`/`secondary`).

## 2. Endpoint + auth

- [ ] 2.1 Add `GET /api/fleet/summary` returning `FleetSummaryResponse`, guarded by the existing API-key validation dependency (NOT `validate_dashboard_session`).
- [ ] 2.2 Confirm the route is unreachable without a valid API key (401/403), consistent with how proxy API-key auth already rejects.
- [ ] 2.3 Register the router; ensure no existing route, dependency, or the `0.0.0.0` bind is altered.

## 3. Tests

- [ ] 3.1 Test: request without an API key → rejected (no account data in body).
- [ ] 3.2 Test: request with a valid API key → 200 with the minimal projection for all accounts.
- [ ] 3.3 Test: response contains NONE of the excluded sensitive fields (tokens, auth status, raw credit balances, request-cost detail).
- [ ] 3.4 Test: primary/secondary remaining_percent + reset_at + window_minutes map correctly from a fixture `AccountSummary`.

## 4. OpenSpec sync

- [ ] 4.1 Validate the change: `openspec validate --specs` (and `openspec validate add-fleet-summary-endpoint`).
- [ ] 4.2 On verify, sync the `fleet-summary-read` delta into `openspec/specs/fleet-summary-read/` and archive the change.
