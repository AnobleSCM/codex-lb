## Why

The `POST /api/accounts/{account_id}/probe` endpoint added in `add-account-probe-endpoint` is the operator's manual unblock for accounts stuck behind a lazy `/wham/usage` after OpenAI-side reset events (parent issues https://github.com/Soju06/codex-lb/issues/676 / https://github.com/Soju06/codex-lb/issues/677). Today the only way to invoke it is curl with a dashboard session cookie. Surfacing the action in the accounts dashboard turns the recovery into a single click and brings codex-lb closer to the UX described in issue #677.

## What Changes

- Add `AccountProbeRequestSchema` / `AccountProbeResponseSchema` (camelCase, mirroring backend `DashboardModel` conventions) to `frontend/src/features/accounts/schemas.ts`.
- Add `probeAccount(accountId, model?)` to `frontend/src/features/accounts/api.ts` that posts to `/api/accounts/{id}/probe`.
- Add `probeMutation` to `useAccountMutations` in `frontend/src/features/accounts/hooks/use-accounts.ts`. The mutation invalidates `["accounts", "list"]` + `["dashboard", "overview"]` and emits a result toast that includes the upstream HTTP status and the post-probe status transition (`"rate_limited → active"` etc.).
- Add a `Probe` button (Activity icon) to `frontend/src/features/accounts/components/account-actions.tsx`. The button is rendered for all account statuses except `paused` and `deactivated` (those would return 409 from the backend). Disabled while any account mutation is in flight.
- Wire a new `onProbe(accountId)` callback through `AccountDetail` and the accounts page so the existing call-site composition pattern is preserved.
- No changes to the existing endpoint, no changes to other action buttons.

## Impact

- One-click recovery for stuck-rate-limited / stuck-quota-exceeded accounts directly from `/accounts`. Eliminates the "open a terminal and curl" recovery path that operators have to remember today.
- New button is contextual (hidden on `paused` / `deactivated`), so it never produces a 409 that a user clicked themselves into.
- No backend change required; the endpoint already exists and has its own admission contract.
- No public client surface change.
