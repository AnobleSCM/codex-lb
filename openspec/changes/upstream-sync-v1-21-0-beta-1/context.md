# Context — Upstream sync to codex-lb v1.21.0-beta.1

## Purpose / scope

Record why the AnobleSCM fork was reset onto upstream `v1.21.0-beta.1`
(`65dc4b75`) and how each pre-existing fork patch was dispositioned. This is a
sync change: it introduces no new capability and links to upstream's own specs
for normative behavior. Per-lane behavior lives in the carry-lane commit
messages.

## Fork patch disposition

### Upstream-obsoleted (already fixed upstream — dropped)

The same problem the fork patch solved is fixed in current upstream, usually
with broader coverage. These are dropped (not carried):

| Fork patch | Upstream resolution |
|-----------|----------------------|
| #4 | #690 |
| #5 / #6 | `63e8deed` + #895 |
| #7 | #772 |
| #9 | #774 |
| #13 | #1128 |
| #19 | #1137 |
| #22 | #1054 |

### Retired (no longer worth carrying — dropped)

- **#11** — lint-debt cleanup specific to the fork's older tree; upstream's tree
  and lint config have moved on, so there is nothing to port.
- **#20** — parity scaffolding that existed only to track fork-vs-upstream
  divergence; the reset makes it obsolete.

### SPLIT — Lane 1 retired, Lane 1b carried (fork #1 `80904ebb` + #2 `55ab5d0c`)

**Lane 1 (restart recovery) — RETIRED, upstream-covered.** A persisted
`blocked_at` account recovers after a process restart via
`background_recovery_state_from_account`
(`app/modules/proxy/load_balancer.py`), seeded from the persisted block marker
and driven by the usage refresh scheduler's
`reconcile_recoverable_account_statuses`
(`app/core/usage/refresh_scheduler.py`). Upstream provenance: #754
(stored-reset recovery), #928 and #1121 (the background reconciler +
restart-without-runtime-state path). Coverage is pinned by upstream's own
tests plus
`test_usage_refresh_scheduler_recovery.py::test_reconcile_recoverable_account_statuses_restores_rate_limited_after_reset_elapses`
and
`test_load_balancer.py::test_background_recovery_state_recovers_rate_limited_after_reset_elapses`.

**Lane 1b (stale-future-reset early recovery) — CARRIED.** A live probe
against `65dc4b75` (2026-07-10) showed the reviewed claim "fresh usage clears
stale reset guards" holds only for QUOTA_EXCEEDED: `_state_from_account`'s
fresh-newer-window guard clear was QUOTA_EXCEEDED-only, and
`apply_usage_quota` held RATE_LIMITED whenever the stored reset lay in the
future — so an account benched by a pessimistic/stale reset hint stayed
benched for the full stored horizon (~2.5h in the original 2026-05 incident)
even when fresh usage proved the window had already rolled. Lane 1b adds the
RATE_LIMITED analogue of upstream's own QUOTA_EXCEEDED clear: recovery only on
positive fresh evidence (recent entry, capacity available, reset strictly
newer than the stored guard, and — when a block marker exists — recorded
after the block). Absence of evidence keeps the stored horizon (fail-closed);
re-blocking refreshes `blocked_at`, which invalidates older evidence, so a
genuinely limited account cannot flap through the clear. Pinned by the
`background_recovery_state` stale-guard tests (2 recovery + 2 fail-closed) and
`test_reconcile_recoverable_account_statuses_restores_rate_limited_on_stale_future_reset`.

The fork's original `RATE_LIMITED_COOLDOWN_SECONDS` cooldown branch remains
retired — its 120s marker-based early-recovery is superseded by the
evidence-gated clear above, and the fork's regression tests no longer match
upstream's evolved `apply_usage_quota`.

### Carried (re-implemented against upstream — Lanes 2-5)

| Lane | Fork origin | Summary |
|------|-------------|---------|
| 2 | `fea73d5c` | No-reset quota fallback 3600s → 900s |
| 3 | `9005277b` | Degraded mode surfaced on `/health` |
| 4 | `d350ce4d` (#12) | Own/close sessions in non-request borrows |
| 5 | #8 `cada1757`, #10 `cbe84e28`, #21 `fdfdbc1d`, #23 `823dd47d`, #3 `704fadd0` | Deploy tooling + `.codex` symlink + Class C runbook |

## Rollback is a database restore, not a code revert

Between the fork base and `v1.21.0-beta.1`, upstream shipped migrations with
**lossy or no-op downgrades**, so `alembic downgrade` cannot faithfully restore
the prior schema/data. Rollback therefore means restoring data, not reverting
code — and the two data assets are distinct:

- **Database (the rollback asset):** the live database is PostgreSQL. The
  rollback asset is the **pre-cutover `pg_dump`**, taken immediately before the
  live cutover (restore path proven 2026-07-10). Rolling back = re-pin the
  prior image + restore that dump.
- **`codex-lb-data` volume (separate asset — NOT touched by the DB rollback):**
  the volume holds `encryption.key` (plus legacy SQLite artifacts). The DB
  rollback does not restore or modify it; it must simply remain intact so the
  restored rows stay decryptable.

**RPO:** restoring the pre-cutover dump discards every write made after the
cutover — usage telemetry, request logs, and any account / API-key / settings
mutations. Mitigation: account, API-key, and settings mutations are **frozen
during the 48h soak window**, so the only accepted loss on rollback is
telemetry (usage / request-log rows).

## Landing mechanics

Landing is an **ours-merge commit**: its tree is byte-identical to the reviewed
sync tip, with parents = old `main` + the sync tip, merged through the normal
gated PR flow. It is **not** a force-push reset — old `main` history stays
reachable, and the landed tree is exactly the reviewed one.

## Breaking config for operators (review before cutover)

Upstream between the fork base and `v1.21.0-beta.1` changed several
operator-facing defaults/contracts:

- **`CODEX_LB_DATA_DIR` pinning** — the data directory is now resolved from this
  variable; a container that relied on the old implicit path must pin it
  explicitly or it will initialize a fresh (empty) data dir.
- **Websocket `trust_env` auto-detect** — the upstream client now auto-detects
  proxy/env trust; deployments that depended on the old fixed behavior should
  confirm outbound routing still matches intent.
- **`smart` transport default** — the downstream-HTTP→upstream transport policy
  defaults to `smart` (route by sticky-session signal). Operators wanting the
  legacy pinned behavior must set `always_http` / `pinned`.
- **Stream-idle default 7200s** — the stream idle timeout default changed; long
  or intentionally-idle stream consumers should confirm the new ceiling.
- **Dashboard loopback session TTL 1 year** — loopback dashboard sessions now
  persist for up to a year; treat local dashboard access accordingly.
- **Python 3.14 image** — the runtime image is Python 3.14 (`uv sync` provisions
  3.14.x locally). Anything pinned to 3.13 assumptions should be re-verified.

## Post-cutover VERIFY items

Deferred to live cutover (cannot be proven from the source tree alone):

1. **`gpt-5.6-sol` model id** — confirm the model id the fleet routes through
   codex-lb still resolves against upstream's reworked model catalog
   (#1176 / #1163 / #1152). Upstream reworked catalog/model-source handling, so
   the exact routed model id must be re-validated against the live `/v1/models`
   / catalog surface.
2. **RATE_LIMITED reconciler soak** — capture at least one live observation of a
   RATE_LIMITED account recovering to ACTIVE via the reconciler
   (`reconcile_recoverable_account_statuses` /
   `background_recovery_state_from_account`), confirming Lane 1's retirement
   (restart recovery) and the Lane 1b evidence-gated stale-guard clear are
   both safe in the running system.

## Example

A current Codex CLI turn that previously 400-ed on the fork (`Field required`,
rejected `instructions`) succeeds against `v1.21.0-beta.1`, and a follow-up turn
carrying `previous_response_id` continues the session instead of missing with
`previous_response_not_found` — the two live symptoms that motivated the reset.
