## Why

The API-key-authenticated fleet summary omits the reset-credit snapshot that
codex-lb already maintains and shows on its Accounts dashboard. Downstream
read-only fleet viewers therefore fall back to manually recorded counts that
can remain visible after credits expire or are consumed.

## What Changes

- Add a nullable `rateLimitResetCredits` projection to each account returned by
  `GET /api/fleet/summary`.
- Populate it from the same in-memory reset-credit snapshot used by the codex-lb
  Accounts dashboard when the caller's key may view account-pool usage.
- Return `null` when no live snapshot is present so downstream consumers can
  distinguish unavailable data from a confirmed zero.
- Expose only the available count and nearest expiry; never expose credit ids,
  descriptions, tokens, or redemption material.

## Capabilities

### Modified Capabilities

- `fleet-summary`: trusted local fleet consumers receive a minimal,
  policy-gated reset-credit projection alongside each account's capacity
  windows.

## Impact

- Backend: `app/modules/fleet/schemas.py` and `app/modules/fleet/mappers.py`.
- Tests: fleet-summary API contract and sensitive-field coverage.
- No database migration, upstream request, credential change, dashboard UI
  change, or reset redemption.
