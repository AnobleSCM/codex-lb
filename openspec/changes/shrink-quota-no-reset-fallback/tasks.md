## 1. Implement the shortened fallback

- [x] 1.1 Add `QUOTA_EXCEEDED_NO_RESET_FALLBACK_SECONDS = 900` in
  `app/core/balancer/logic.py`, near `QUOTA_EXCEEDED_COOLDOWN_SECONDS` /
  `RATE_LIMITED_COOLDOWN_SECONDS`, with a comment explaining the recovery-window
  rationale and the 2026-07-05 incident.
- [x] 1.2 Replace `state.reset_at = int(time.time() + 3600)` in
  `handle_quota_exceeded` with the new constant.
- [x] 1.3 Export `QUOTA_EXCEEDED_NO_RESET_FALLBACK_SECONDS` from
  `app/core/balancer/__init__.py` (import list + `__all__`).
- [x] 1.4 Leave `select_account` decision logic and the explicit-reset path
  (`_extract_reset_at`) untouched.

## 2. Tests

- [x] 2.1 `test_handle_quota_exceeded_uses_short_no_reset_fallback`: no reset
  hint → `reset_at == now + 900`, and `< now + 3600`.
- [x] 2.2 `test_handle_quota_exceeded_honors_explicit_reset_over_fallback`:
  `resets_in_seconds=120` → `reset_at == now + 120` (fallback not applied).
- [x] 2.3 `test_select_account_blocks_quota_exceeded_on_future_reset_despite_fresh_headroom`:
  reproduces the stale-reset block (QUOTA_EXCEEDED + future `reset_at` +
  `used_percent=0` → no candidate), and that it is selectable once the horizon
  passes.

## 3. Validation

- [x] 3.1 `.venv/bin/python -m pytest tests/unit/test_load_balancer.py -k 'quota or select_account or handle_quota or fallback or reset'` — clean (58 passed).
- [x] 3.2 `.venv/bin/ruff check` + `ruff format --check` on the changed files — clean.
- [x] 3.3 `.venv/bin/ty check app/core/balancer/logic.py app/core/balancer/__init__.py` — clean.
- [ ] 3.4 `openspec validate --specs` — run in CI (openspec CLI not on the local PATH this run).
