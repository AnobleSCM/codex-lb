## 1. Schemas

- [ ] 1.1 Add `AccountProbeRequestSchema` (optional `model: string`) and `AccountProbeResponseSchema` (mirroring backend: `status`, `accountId`, `probeStatusCode`, `primaryUsedPercentBefore`/`After`, `secondaryUsedPercentBefore`/`After`, `accountStatusBefore`/`After`) to `frontend/src/features/accounts/schemas.ts`.
- [ ] 1.2 Export the inferred types alongside the schemas.

## 2. API client

- [ ] 2.1 Add `probeAccount(accountId: string, model?: string)` to `frontend/src/features/accounts/api.ts` that posts to `${ACCOUNTS_BASE_PATH}/${encodeURIComponent(accountId)}/probe` with `AccountProbeResponseSchema`. Body carries `{ model }` only when `model` is provided.

## 3. Hook

- [ ] 3.1 Add `probeMutation` to `useAccountMutations` in `frontend/src/features/accounts/hooks/use-accounts.ts`. `mutationFn` accepts `{ accountId: string; model?: string }`.
- [ ] 3.2 On success: emit a single toast with the probe HTTP status code and the account status before/after transition. Invalidate the same query keys as `pauseMutation` / `resumeMutation`.
- [ ] 3.3 On error: emit `toast.error(error.message || "Probe failed")`.
- [ ] 3.4 Export the mutation from `useAccounts` so the accounts page picks it up automatically.

## 4. UI

- [ ] 4.1 Add a `Probe` button (Activity icon from `lucide-react`, outline variant, same sizing as the existing pause/resume buttons) to `frontend/src/features/accounts/components/account-actions.tsx`. Render only when `account.status` is not in `("paused", "deactivated")`. Disabled while `busy`.
- [ ] 4.2 Add `onProbe: (accountId: string) => void` to `AccountActionsProps`.
- [ ] 4.3 Thread `onProbe` through `AccountDetail` (`frontend/src/features/accounts/components/account-detail.tsx`) and the accounts page caller so the click reaches the mutation.

## 5. Tests

- [ ] 5.1 Add `frontend/src/features/accounts/components/account-actions.test.tsx` (or extend the existing test file if present): assert the Probe button renders for `active`, `rate_limited`, `quota_exceeded` and is absent for `paused`, `deactivated`; assert the button calls `onProbe(account.accountId)` on click; assert it's disabled when `busy=true`.

## 6. Lint / build / spec validation

- [ ] 6.1 `cd frontend && bun run lint` clean.
- [ ] 6.2 `cd frontend && bun run typecheck` clean.
- [ ] 6.3 `cd frontend && bun run test -- account-actions` clean.
- [ ] 6.4 `cd frontend && bun run build` (regression check on the production bundle).
