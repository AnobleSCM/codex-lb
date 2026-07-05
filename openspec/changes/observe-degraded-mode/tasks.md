## 1. Degradation manager: transition edge + count

- [x] 1.1 Add `_available_accounts` to `DegradationManager` and an optional
  `available_accounts` keyword on `set_degraded` / `set_normal` (module wrappers
  too); expose `get_available_accounts()`.
- [x] 1.2 Emit the `DEGRADATION_TRANSITION` log only on the normal↔degraded edge
  (WARNING enter / INFO recover); drop the repeated-while-degraded case to debug.
- [x] 1.3 Keep `get_status()` shape unchanged (existing consumers + tests).

## 2. Balancer wiring

- [x] 2.1 Pass `available_accounts=len(selection_inputs.accounts)` at the
  circuit-breaker `set_degraded`, the two `set_normal`, and the
  no-available-accounts `set_degraded` call sites in `LoadBalancer.select_account`.

## 3. /health exposure

- [x] 3.1 Add `DegradationInfo` + `degradation` / `available_accounts` fields to
  `HealthResponse` (`app/modules/health/schemas.py`).
- [x] 3.2 Populate them in `health_check` from the in-memory manager; keep
  `status="ok"` (liveness unchanged, no DB read).

## 4. Tests

- [x] 4.1 `set_degraded` / `set_normal` record `available_accounts`; `get_status()`
  shape unchanged.
- [x] 4.2 `DEGRADATION_TRANSITION` logs exactly once per edge across repeated
  `set_degraded` calls, and once on recovery.
- [x] 4.3 `health_check` reports degraded + normal states with the count.
- [x] 4.4 Existing balancer degraded-path test also asserts the recorded count.
- [x] 4.5 Integration `test_health_endpoint_ok` updated for the enriched shape.

## 5. Validation

- [x] 5.1 `pytest` across degradation/health/load-balancer suites — 175 passed, 3 pre-existing skips.
- [x] 5.2 `ruff check` + `ruff format --check` + `ty check` on changed files — clean.
- [ ] 5.3 `openspec validate --specs` — run in CI (openspec CLI not on local PATH this run).
