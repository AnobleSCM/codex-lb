## Why

The token-refresh singleflight (`_RefreshSingleflight` in `app/modules/accounts/auth_manager.py`) runs `AuthManager.refresh_account` inside a **detached task** that it keeps alive with `asyncio.shield` (so concurrent waiters share one refresh and a cancelled waiter does not abort it). `refresh_account` persists the rotated tokens through `AuthManager`'s bound repo (`update_tokens`, and on permanent failure `get_by_id` / `update_status`).

In the proxy path that bound repo is a **request-scoped** background session: `ProxyService._ensure_fresh` (`app/modules/proxy/service.py`) opens `async with self._repo_factory() as repos` (→ `get_background_session()`) and builds `AuthManager(repos.accounts, ...)`.

When a client disconnects mid-refresh, the request task is cancelled at `await asyncio.shield(task)`. The shield keeps the refresh task running, but the caller unwinds and the `async with` closes the request-scoped session via `get_background_session`'s `finally`. The still-running refresh task then calls `update_tokens` against that **closed, concurrently-finalized** `AsyncSession` — which the codebase documents is not safe for concurrent use (`app/modules/usage/updater.py`: "AsyncSession is not safe for concurrent use"). The result is a background-pool connection that is checked out but never returned.

Over time these stranded checkouts exhaust the background engine pool (`database_background_pool_size=100` + `database_background_max_overflow=100` = 200). Once exhausted, every `/backend-api/codex/*` request blocks the full `database_pool_timeout_seconds` (30s) in the firewall middleware's allowlist lookup (`app/core/middleware/api_firewall.py` → `get_background_session()`), then returns HTTP 500; client retries pile more load on the dead pool.

Live incident 2026-05-21 on `codex-lb:active`: **12,148** `sqlalchemy.exc.TimeoutError: QueuePool limit of size 100 overflow 100 reached, connection timed out, timeout 30.00` over ~9 hours. Onset after ~3 days of uptime (~1 leaked connection per ~20 min), **disconnect-correlated** (Codex CLI / Desktop reconnect storms), and **not per-request** (firewall + auth hit the same pool every request and would exhaust it in minutes if they leaked). `/health` stayed 200 the entire time (that path never touches the pool), so the health-only watchdog never fired and the leak ran unattended for ~9h until a manual `docker restart`.

## What Changes

- `AuthManager.__init__` gains an optional `refresh_repo_factory: Callable[[], AbstractAsyncContextManager[AccountsRepositoryPort]]`. A new `AuthManager._run_refresh` becomes the singleflight body: when a factory is provided it opens a **fresh** accounts repo (its own DB session) for the refresh write, so the detached task's session lifetime is fully independent of the caller's cancellation. When no factory is provided it falls back to the bound repo (callers whose session is not client-cancellable, e.g. the usage refresh scheduler).
- `ProxyService._ensure_fresh` passes `refresh_repo_factory=self._accounts_refresh_scope`, a new `@asynccontextmanager` that yields a fresh `repos.accounts` from the existing `self._repo_factory()`. No new cross-module imports.
- Add a regression test in `tests/unit/test_auth_manager.py` that reproduces the disconnect-during-refresh leak: the caller is cancelled while the refresh is in flight, and the test asserts the refresh wrote through its **own** session (opened and closed) and never the request-scoped repo. The test fails on the pre-fix code and passes after.
- Add an `ADDED Requirements` delta to the `database-backends` capability codifying that detached/shielded background tasks MUST own their DB session lifetime rather than borrow a request-scoped session.

## Impact

- **Operators:** Fixes the slow background-pool connection leak that exhausted the pool (~3-day cadence) and required manual `docker restart`. No new env var, no config change, no API surface change, no migration, and no image-pin / alembic interaction (pure code). The 2026-05-21 watchdog pool-aware trigger remains as defense-in-depth.
- **Clients:** No change to token-refresh behavior on the happy path or for non-cancelled callers. The only behavioral change is that a refresh triggered from the proxy path now writes through its own DB session, so a client disconnect mid-refresh can no longer strand a pooled connection.
- **Behavior unchanged:** Singleflight dedup, refresh admission control, recent-failure cooldown, and `_ensure_chatgpt_account_id` are unchanged. The usage refresh scheduler path is unchanged (it passes no factory; its session is held by the scheduler, not a client-cancellable request).
- **Risk:** Confined to the token-refresh write path. The fresh session is opened/used/closed entirely inside the shielded task, so it cannot be closed out from under the task. Worst case if `refresh_repo_factory` is misconfigured is a fallback to current behavior.
