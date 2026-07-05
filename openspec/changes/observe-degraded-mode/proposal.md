## Why

When the balancer has zero selectable accounts it calls
`set_degraded("all upstream accounts are unavailable")` (`app/modules/proxy/load_balancer.py`)
and clients receive a degraded-mode error. But the degraded state was
effectively invisible to the surrounding ecosystem:

- `GET /health` returned a bare `{"status": "ok"}` even during full degradation,
  so a watchdog/daemon polling it could not pre-check pool health before
  claiming work — it would claim, hit the degraded proxy, and fail.
- `set_degraded` is called on *every* failed selection, and each call logged an
  identical `WARNING "Operating in degraded mode: ..."`. During the 2026-07-05
  18:40–19:00Z incident that produced ~130 near-identical warnings in the
  window, with no single distinct edge event. The transition into (and out of)
  degradation was buried in per-request noise; the outage was noticed ~25
  minutes later via dead downstream tasks rather than a clear signal.

This change makes the degraded state observable without changing selection
behavior or liveness semantics.

## What Changes

- `DegradationManager` (`app/core/resilience/degradation.py`) now records the
  count of accounts the balancer last considered (present, not
  deactivated/paused) via an optional `available_accounts` keyword on
  `set_degraded` / `set_normal`, exposed through a new `get_available_accounts()`
  accessor. `get_status()`'s existing shape is unchanged.
- `DegradationManager` emits the operator-facing `DEGRADATION_TRANSITION` log
  line only on the normal↔degraded **edge** (WARNING on enter, INFO on
  recovery). Repeated `set_degraded` calls while already degraded drop to debug,
  eliminating the per-request warning storm.
- `LoadBalancer.select_account` passes the current pool count at each
  `set_degraded` / `set_normal` call site.
- `GET /health` now returns `degradation` (`level`, `reason`) and
  `available_accounts` alongside `status`. **`status` stays `"ok"`** — liveness
  is unchanged so a degraded upstream cannot evict the process (the same reason
  `/health/ready` deliberately ignores upstream state). The new fields are read
  from the in-memory degradation manager, so `/health` does no extra DB work.

## Impact

- Watchdogs/daemons can read `degradation.level != "normal"` from `/health` to
  pre-check before claiming, and `available_accounts` distinguishes
  "all accounts present but rate/quota-blocked" (transient) from
  "0 accounts present" (all deactivated/paused → needs re-auth).
- Log-based alerting can key on the single `DEGRADATION_TRANSITION` marker
  instead of counting a warning storm.
- **Out of scope (separate staged change `alert-degradation-transitions`):** an
  active push notification (webhook to n8n / a Multica ops issue) on the
  transition edge. That needs a target decision and a live forced-degraded-toggle
  proof, so it lands as its own change on top of the transition edge this change
  establishes.
- No change to selection decisions, account state transitions, persistence, or
  the `/health/live` / `/health/ready` / `/health/startup` contracts.
