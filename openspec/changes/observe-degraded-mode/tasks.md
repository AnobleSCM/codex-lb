## 1. Degradation manager: transition edge + count

- [x] 1.1 Add `_available_accounts` to `DegradationManager` and an optional
  `available_accounts` keyword on `set_degraded` / `set_normal` (module wrappers
  too); expose `get_available_accounts()`.
- [x] 1.2 Emit the `DEGRADATION_TRANSITION` log only on the normal↔degraded edge
  (WARNING enter / INFO recover); drop the repeated-while-degraded case to debug.
- [x] 1.3 Keep `get_status()` shape unchanged (existing consumers + tests).

## 2. Balancer wiring

- [x] 2.1 Drive the degradation signal only from *unscoped* selection cycles
  (`account_ids is None and not exclude`), reporting a **service-wide** present
  count via `_service_available_accounts` (derived from `runtime_accounts`, so a
  per-request model/scope filter cannot shrink it). Enter degraded on the
  circuit-breaker and no-available-accounts paths; recover to normal ONLY on a
  *proven* selection (success path) with the circuit breaker closed — never on
  mere account presence, never on a model-/scope-narrowed routing error, and
  never while the breaker is open.

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

- [x] 5.1 `pytest` across degradation/health/load-balancer suites.
- [x] 5.2 `ruff check` + `ruff format --check` + `ty check` (whole-repo) — clean.
- [ ] 5.3 `openspec validate --specs` — **run-before-merge, NOT a CI gate.** The
  CI workflow (`.github/workflows/ci.yml`) has no OpenSpec step and the CLI is a
  Node package not present in this Python repo's toolchain, so validation is a
  manual/pre-merge step, not automated. (Corrects the earlier claim that CI runs
  it — Cubic P2.) A dedicated CI OpenSpec job is deferred: it touches the
  protected CI workflow and needs its own review.

## 6. Review follow-ups (Cubic on PR #16)

- [x] 6.1 P1 — kill the `degraded->normal->degraded` flap: stop marking normal on
  mere account presence before selection; recover only on a proven selection.
- [x] 6.2 P2 — `/health available_accounts` is service-wide, not request-scoped:
  gate global mutation to unscoped cycles and count via `_service_available_accounts`.
- [x] 6.3 P2 — `set_normal` / `set_degraded` clear `_available_accounts` to `None`
  when a fresh count is omitted, so `/health` never reports a stale pool count.
- [x] 6.4 P3 — `/health` indexes `degradation["level"]` directly (fail loud) via a
  typed `DegradationStatus`; `HealthResponse.degradation` is non-null; integration
  test asserts the full `{level, reason}` shape.
- [x] 6.5 Tests — no-flap across repeated failed cycles, recovery on a successful
  selection, and scoped requests leaving the global signal untouched.

## 7. Review follow-ups round 2 (Cubic on the fix commit)

- [x] 7.1 P2 — a typed/model-scoped routing error no longer clears global
  degraded (removed the `set_normal` on `error_code`); a request for an
  unsupported model can no longer mask a pool-wide outage. Test updated to assert
  degraded persists.
- [x] 7.2 P1/P2 — the success-path recovery is gated on `not
  _is_upstream_circuit_breaker_open()`, so one lucky selection cannot flip
  /health back to normal while the pool-wide breaker is still open. Test added.
- [x] 7.3 Spec — recovery requirement corrected (proven selection + breaker
  closed only) with scenarios for the typed-error and breaker-open cases.

## 8. Review follow-ups round 3 (recovery starvation)

- [x] 8.1 Recovery is no longer gated on `drives_global_health`: any *proven*
  selection that returns an account (scoped or unscoped) recovers to normal while
  the breaker is closed. A returned account disproves "all accounts unavailable"
  regardless of scope; without this a recovered pool that then serves only
  sticky/preferred-account (scoped) traffic would stay falsely degraded forever
  because the scoped preferred-probe short-circuits the unscoped path. Entry into
  degraded stays unscoped-only. Test added (scoped success recovers); the
  scoped-no-mutation test now covers the scoped *failure* case explicitly.
