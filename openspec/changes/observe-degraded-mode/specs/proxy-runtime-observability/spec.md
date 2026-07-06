## ADDED Requirements

### Requirement: /health surfaces upstream degradation without failing liveness

`GET /health` MUST return `status = "ok"` whenever the process is alive, so a
degraded upstream never evicts the process. Alongside `status`, the response
MUST carry the current degradation `level` and `reason` and the last-known
`available_accounts` count. That count MUST be **service-wide** — the number of
accounts present in the whole pool (not deactivated/paused) at the last unscoped
selection cycle — and MUST NOT be narrowed by a request's account/exclude/model
scope. The `degradation` object MUST always be present (non-null). These fields
MUST be read from in-memory runtime state without an additional database read on
the `/health` path.

#### Scenario: Healthy pool reports normal
- **GIVEN** the balancer is not degraded
- **WHEN** a client calls `GET /health`
- **THEN** the response has `status = "ok"` and `degradation.level = "normal"`
- **AND** `degradation.reason` is null

#### Scenario: Degraded pool is visible but liveness stays ok
- **GIVEN** the balancer has set degraded mode with a reason
- **WHEN** a client calls `GET /health`
- **THEN** the response still has `status = "ok"`
- **AND** `degradation.level = "degraded"` with the reason surfaced
- **AND** `available_accounts` reflects the accounts present at the last selection

### Requirement: Degradation transitions emit a single edge event

The degradation manager MUST emit its operator-facing transition log only on the
normal↔degraded edge — a WARNING when entering degraded mode and an INFO when
returning to normal — even though `set_degraded` is invoked on every failed
selection. Repeated `set_degraded` calls while already degraded MUST NOT emit a
new transition WARNING.

#### Scenario: Repeated set_degraded logs one enter event
- **GIVEN** the manager is in the normal state
- **WHEN** `set_degraded` is called multiple times in succession
- **THEN** exactly one `DEGRADATION_TRANSITION normal->degraded` WARNING is emitted

#### Scenario: Recovery logs one exit event
- **GIVEN** the manager is in the degraded state
- **WHEN** `set_normal` is called
- **THEN** exactly one `DEGRADATION_TRANSITION` recovery event is emitted at INFO

### Requirement: Degradation state tracks proven pool health, only from unscoped cycles

The balancer MUST update the global degradation signal only from **unscoped**
selection cycles (no `account_ids` and no `exclude_account_ids`); a scoped
selection — a preferred-account probe or a scope-restricted API key — sees only a
subset of the pool and MUST NOT change the degradation level or the reported
`available_accounts`. Recovery to normal MUST be driven ONLY by a *proven*
selection that actually returned an account while the pool-wide circuit breaker is
not open. It MUST NOT be inferred from mere account presence before selection,
from a request- or model-scoped routing error (a request for an unsupported model
must not clear a genuine pool-wide outage), or while the upstream circuit breaker
remains open. As a result, repeated failed selections while accounts are present
but none are selectable MUST NOT produce a `degraded->normal->degraded` flap.

#### Scenario: Present-but-unselectable pool does not flap
- **GIVEN** the pool has accounts present but none are currently selectable
- **WHEN** `select_account` is called repeatedly and each call selects nothing
- **THEN** exactly one `DEGRADATION_TRANSITION normal->degraded` WARNING is emitted
- **AND** no `DEGRADATION_TRANSITION degraded->normal` event is emitted between the failures

#### Scenario: A successful selection recovers the degraded state
- **GIVEN** the manager is degraded, the circuit breaker is not open, and an account becomes selectable
- **WHEN** an unscoped `select_account` returns that account
- **THEN** the degradation level returns to normal with one recovery event

#### Scenario: A scoped selection leaves the global signal untouched
- **GIVEN** the manager is degraded with a known `available_accounts` count
- **WHEN** a scoped `select_account` (account_ids or exclude) finds nothing selectable
- **THEN** the degradation level and `available_accounts` are unchanged

#### Scenario: A typed routing error does not clear degraded
- **GIVEN** the manager is degraded
- **WHEN** an unscoped `select_account` returns a typed routing error (e.g. no plan supports the model) instead of an account
- **THEN** the degradation level and reason are unchanged

#### Scenario: A lucky selection does not recover while the breaker is open
- **GIVEN** the upstream circuit breaker is open and the manager is degraded
- **WHEN** an unscoped `select_account` still returns an account
- **THEN** the degradation level stays degraded until the breaker closes
