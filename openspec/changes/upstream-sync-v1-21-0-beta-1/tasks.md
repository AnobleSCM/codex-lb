# Tasks — Upstream sync to codex-lb v1.21.0-beta.1

## 1. Reset base

- [x] 1.1 Set the sync branch to upstream `65dc4b75` (`v1.21.0-beta.1`,
  == `origin/main` == upstream HEAD).
- [x] 1.2 Read upstream conventions (AGENTS.md, `.github/CONTRIBUTING.md`,
  `openspec/` change conventions) before writing any carry lane.

## 2. Lane 1 — RATE_LIMITED early recovery (fork #1/#2)

- [x] 2.1 Disposition decided: **RETIRED — upstream-covered.** Not implemented.
  Upstream `background_recovery_state_from_account`
  (`app/modules/proxy/load_balancer.py`) +
  `reconcile_recoverable_account_statuses`
  (`app/core/usage/refresh_scheduler.py`) already provide restart recovery from
  persisted `blocked_at` and fresh-usage clearing of stale reset guards
  (#754 / #928 / #1121). Any exploratory Lane 1 edits reverted cleanly.

## 3. Lane 2 — shrink no-reset quota fallback to 900s (fork fea73d5c)

- [x] 3.1 Add `QUOTA_EXCEEDED_NO_RESET_FALLBACK_SECONDS = 900` in
  `app/core/balancer/logic.py`; use it where `handle_quota_exceeded` fell back to
  `time.time() + 3600`; export it from `app/core/balancer/__init__.py`.
- [x] 3.2 Port regression tests (short fallback used with no hint; explicit reset
  hint still honored; the stale-reset selection-exclusion reproduction).

## 4. Lane 3 — surface degraded mode via /health (fork 9005277b)

- [x] 4.1 `DegradationManager` records `available_accounts` per transition,
  exposes `get_available_accounts()`, and logs one edge per normal<->degraded
  transition (`app/core/resilience/degradation.py`).
- [x] 4.2 `LoadBalancer` passes a service-wide `_service_available_accounts()`
  count into its existing `set_degraded`/`set_normal` calls (observability only;
  the degradation-trigger logic itself is unchanged).
- [x] 4.3 `/health` returns
  `{"status":"ok","degradation":{"level","reason"},"available_accounts":N}` via a
  new `DegradationInfo` schema; readiness/liveness stay infrastructure-only.
- [x] 4.4 Port the degradation-manager + health-shape unit tests and the
  integration/e2e `/health` shape assertions.

## 5. Lane 4 — own/release sessions in non-request borrows (fork d350ce4d #12)

- [x] 5.1 Replace `async for session in get_session()` with
  `async with SessionLocal() as session:` in `leader_election.py`
  (try_acquire + renew), `audit/service.py` (`_write_audit_log`), and
  `health/api.py` (`health_ready`). Confirmed all four sites still use the borrow
  pattern at upstream HEAD; upstream #1127 fixed different leaks.
- [x] 5.2 Add `tests/unit/test_get_session_pool_leak.py` (pool-checkout baseline
  probe + abandoned-generator control) and repoint the health/leader tests that
  patched `get_session` onto `SessionLocal` context-manager fakes.

## 6. Lane 5 — deploy tooling + live-runtime runbook (fork #8/#10/#21/#23/#3)

- [x] 6.1 Carry `scripts/codex-lb-deploy.sh` (post-#23) verbatim; verify its
  `/internal/drain/{start,status,stop}` + `/health` calls and the
  `{draining, bridge_drain_active, in_flight}` status contract exist at upstream
  HEAD (#564 / #729). No path/param changes were needed.
- [x] 6.2 Carry `tests/unit/test_codex_lb_deploy_script.py` (drops the fork's
  compose-bridge-instance-id-pin assertion — upstream compose does not pin that
  env var and changing it is out of scope).
- [x] 6.3 Carry the `.codex -> .agents` symlink verbatim.
- [x] 6.4 Graft the "Live Runtime Discipline (Class C image-pin trap)" section
  onto upstream's AGENTS.md, pointing at the now-carried deploy script.

## 7. Lane 6 — OpenSpec sync record (this change)

- [x] 7.1 `proposal.md` (why + what + impact).
- [x] 7.2 `context.md` (disposition, rollback-is-DB-restore, breaking-config,
  post-cutover VERIFY items).
- [x] 7.3 `tasks.md` (this file).

## 8. Validation

- [x] 8.1 `uv sync` (provisions Python 3.14.x).
- [x] 8.2 `uv run ruff check .` and `uv run ty check` on touched files.
- [x] 8.3 Targeted tests for every ported/added file and touched module
  (balancer/usage selection, health, db sessions, deploy script).
- [ ] 8.4 `openspec validate upstream-sync-v1-21-0-beta-1 --strict` — **not run**:
  no `openspec` CLI is available (not global, not resolvable via `uvx`). Folder
  structure matches existing changes (proposal / context / tasks); validation is
  structural only.

## 9. Post-cutover (live, deferred)

- [ ] 9.1 Re-validate the `gpt-5.6-sol` routed model id against upstream's
  reworked catalog (#1176 / #1163 / #1152).
- [ ] 9.2 Capture one live RATE_LIMITED→ACTIVE recovery via the upstream
  reconciler, confirming Lane 1's retirement is safe in the running system.
